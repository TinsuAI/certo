"""UOM lookup builder. Returns a UomLookup callable that the flatten
engine consumes. Implements the precedence stack from spec §9:

  1. client_uom_overrides exact (client_id, material_code, from, to)
  2. client_uom_overrides client-wide (client_id, NULL, from, to)
  3. uom_canonical family-based factor
  4. alias normalization → same canonical → factor 1.0
  5. None → engine emits uom_conversion_missing.

Multiple step-3 matches with the same precedence → the engine surfaces
`uom_conversion_ambiguous` (here we never return ambiguous because
canonical units in a family share a single base_factor; ambiguity arises
only in client_uom_overrides if the same (client, mat, from, to) is
duplicated, which the PK constraint prevents).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from app.database import connect
from app.flatten.types import ConversionMatch, UomLookup
from app.flatten.uom import normalize_uom_alias


def _alias_to_canonical(cur, alias: str) -> str | None:
    if not alias:
        return None
    cur.execute(
        "select uom_code from hub.uom_aliases where alias_norm = %s",
        (normalize_uom_alias(alias),),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _canonical_factor(cur, from_canonical: str, to_canonical: str) -> Decimal | None:
    """Return factor s.t. qty_in_from * factor = qty_in_to, when both belong
    to the same family. Computed via base_factor: qty_base = qty * base_factor;
    qty_to = qty_base / to.base_factor; ⇒ factor = from.base_factor / to.base_factor.
    """
    cur.execute(
        "select uom_code, family, base_factor from hub.uom_canonical "
        "where uom_code = any(%s)",
        ([from_canonical, to_canonical],),
    )
    rows = {r[0]: (r[1], Decimal(str(r[2]))) for r in cur.fetchall()}
    if from_canonical not in rows or to_canonical not in rows:
        return None
    f_fam, f_base = rows[from_canonical]
    t_fam, t_base = rows[to_canonical]
    if f_fam != t_fam:
        return None
    if t_base == 0:
        return None
    return f_base / t_base


def make_uom_lookup(client_id: str) -> UomLookup:
    """Build a closure that takes (material_code, from_uom, to_uom) and
    returns a ConversionMatch | None."""
    def lookup(material_code: str, from_uom: str | None,
               to_uom: str | None) -> ConversionMatch | None:
        if not from_uom or not to_uom:
            return None
        with connect() as conn:
            with conn.cursor() as cur:
                # Step 1: client + material exact override.
                if material_code:
                    cur.execute(
                        """
                        select factor from hub.client_uom_overrides
                        where client_id = %s
                          and material_code_key = %s
                          and from_uom = %s and to_uom = %s
                        """,
                        (client_id, material_code, from_uom, to_uom),
                    )
                    row = cur.fetchone()
                    if row:
                        return ConversionMatch(
                            factor=Decimal(str(row[0])),
                            from_uom=from_uom, to_uom=to_uom,
                            source="client_specific",
                        )
                # Step 2: client-wide override (material_code IS NULL → key '').
                cur.execute(
                    """
                    select factor from hub.client_uom_overrides
                    where client_id = %s
                      and material_code_key = ''
                      and from_uom = %s and to_uom = %s
                    """,
                    (client_id, from_uom, to_uom),
                )
                row = cur.fetchone()
                if row:
                    return ConversionMatch(
                        factor=Decimal(str(row[0])),
                        from_uom=from_uom, to_uom=to_uom,
                        source="client_wide",
                    )
                # Step 3: global canonical family-based.
                from_canon = _alias_to_canonical(cur, from_uom)
                to_canon = _alias_to_canonical(cur, to_uom)
                if not from_canon or not to_canon:
                    return None
                # Step 4: alias-equivalent canonical.
                if from_canon == to_canon:
                    return ConversionMatch(
                        factor=Decimal(1),
                        from_uom=from_uom, to_uom=to_uom,
                        source="alias",
                    )
                factor = _canonical_factor(cur, from_canon, to_canon)
                if factor is None:
                    return None
                return ConversionMatch(
                    factor=factor,
                    from_uom=from_uom, to_uom=to_uom,
                    source="global",
                )
    return lookup
