"""UOM lookup builder. Returns a UomLookup callable that the flatten
engine consumes. Implements the precedence stack from spec §9 +
Phase-2 tier-A default (mig 055 / brief 2026-05-12 decision 6):

  1. client_uom_overrides exact (client_id, material_code, from, to)
  2. client_uom_overrides client-wide (client_id, NULL, from, to)
  3. alias-equivalent canonical (factor 1.0, source='alias')
  4. uom_canonical same-family factor (source='global')
  5. tier-A cross-family default — both canonicals in
     {count, count_packaging, assembly} but different families →
     factor=1.0 source='unconfirmed_default' (caller is expected to
     mark the produced derived artifact has_uom_drift=true reason
     `unconfirmed_default_1to1`)
  6. None → engine emits uom_conversion_missing (tier-B hard-block:
     count↔mass, mass↔length, etc. — staff must populate factor
     before refresh succeeds).

Multiple step-4 matches with the same precedence → never ambiguous
because canonical units in a family share a single base_factor;
ambiguity in client_uom_overrides is blocked by the PK constraint.
"""
from __future__ import annotations

from dataclasses import dataclass
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


# Phase 2 (brief decision 6): cross-family pairs whose families both
# belong to this set get a 1.0 default factor with source
# 'unconfirmed_default'. Other cross-family pairs (count↔mass, etc.)
# return None to force staff to populate an explicit factor row.
_TIER_A_FAMILIES = frozenset({"count", "count_packaging", "assembly"})


def _canonical_lookup(cur, from_canonical: str,
                      to_canonical: str) -> tuple[Decimal | None, str, str]:
    """Resolve canonical UoMs to (same-family factor or None, from_family,
    to_family). When same family: factor = from.base_factor /
    to.base_factor. When cross family: factor=None and caller decides
    tier-A vs tier-B."""
    cur.execute(
        "select uom_code, family, base_factor from hub.uom_canonical "
        "where uom_code = any(%s)",
        ([from_canonical, to_canonical],),
    )
    rows = {r[0]: (r[1], Decimal(str(r[2]))) for r in cur.fetchall()}
    f_row = rows.get(from_canonical)
    t_row = rows.get(to_canonical)
    if f_row is None or t_row is None:
        return None, "", ""
    f_fam, f_base = f_row
    t_fam, t_base = t_row
    if f_fam != t_fam:
        return None, f_fam, t_fam
    if t_base == 0:
        return None, f_fam, t_fam
    return f_base / t_base, f_fam, t_fam


def resolve_conversion(cur, client_id: str, material_code: str | None,
                       from_uom: str | None,
                       to_uom: str | None) -> ConversionMatch | None:
    """The 6-tier cascade body, on an already-open cursor. Single factor
    authority shared by `make_uom_lookup` (per-call connection) and
    `classify_uom_relation` (batches many pairs on one cursor)."""
    if not from_uom or not to_uom:
        return None
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
    # Step 3+: canonical resolution. Without canonical on either side,
    # caller has no way to convert anyway → bail with None.
    from_canon = _alias_to_canonical(cur, from_uom)
    to_canon = _alias_to_canonical(cur, to_uom)
    if not from_canon or not to_canon:
        return None
    # Step 3: alias-equivalent canonical (PIECES ≡ pcs).
    if from_canon == to_canon:
        return ConversionMatch(
            factor=Decimal(1),
            from_uom=from_uom, to_uom=to_uom,
            source="alias",
        )
    # Step 4: same-family base_factor conversion (gam → kg).
    factor, from_fam, to_fam = _canonical_lookup(cur, from_canon, to_canon)
    if factor is not None:
        return ConversionMatch(
            factor=factor,
            from_uom=from_uom, to_uom=to_uom,
            source="global",
        )
    # Step 5: tier-A cross-family default (Phase 2). Both families in
    # {count, count_packaging, assembly} → plausible packaging-synonym
    # case, default 1:1. Caller marks resulting derived artifact stale
    # with reason `unconfirmed_default_1to1`.
    if from_fam in _TIER_A_FAMILIES and to_fam in _TIER_A_FAMILIES:
        return ConversionMatch(
            factor=Decimal(1),
            from_uom=from_uom, to_uom=to_uom,
            source="unconfirmed_default",
        )
    # Step 6: tier-B hard-block. count↔mass, mass↔length, etc. Defaulting
    # 1:1 here would silently corrupt by orders of magnitude. Staff must
    # populate factor first.
    return None


def make_uom_lookup(client_id: str) -> UomLookup:
    """Build a closure that takes (material_code, from_uom, to_uom) and
    returns a ConversionMatch | None."""
    def lookup(material_code: str, from_uom: str | None,
               to_uom: str | None) -> ConversionMatch | None:
        # Guard before connecting — the flatten engine calls this per edge
        # and many leaf rows carry no uom; opening a connection just to
        # return None would be a needless round-trip on the hot path.
        if not from_uom or not to_uom:
            return None
        with connect() as conn, conn.cursor() as cur:
            return resolve_conversion(
                cur, client_id, material_code, from_uom, to_uom,
            )
    return lookup


@dataclass(frozen=True)
class UomRelation:
    """Convertibility verdict between two UoMs (A.4.4). `relation` drives
    severity/chip color everywhere; `confirmed` is False only for the
    tier-A 1:1 *assumption* so the UI can render it distinctly."""
    relation: str                  # 'equivalent' | 'convertible' | 'incompatible'
    factor: Decimal | None         # directional: from `a` to `b`
    to_canonical: str | None       # canonical `b` normalizes to (display)
    via: str | None                # identity|alias|same_family_base_factor|client_override|tier_a_default
    confirmed: bool                # False only for tier_a_default
    remediation: str | None        # 'add_factor' | 'add_alias' | None


# ConversionMatch.source → (relation, via, confirmed).
_SOURCE_TO_RELATION = {
    "alias": ("equivalent", "alias", True),
    "global": ("convertible", "same_family_base_factor", True),
    "client_specific": ("convertible", "client_override", True),
    "client_wide": ("convertible", "client_override", True),
    "unconfirmed_default": ("convertible", "tier_a_default", False),
}


def classify_uom_relation(a: str | None, b: str | None, *,
                          client_id: str,
                          material_code: str | None = None) -> UomRelation:
    """Classify the relationship between two UoM strings as
    equivalent / convertible / incompatible. Acceptance is symmetric;
    the reported `factor` is directional (a → b)."""
    na = (a or "").strip().lower()
    nb = (b or "").strip().lower()
    if not na or not nb:
        return UomRelation("incompatible", None, None, None, False, None)
    # Identity short-circuits before any lookup so novel/unseeded tokens
    # that are literally the same string don't false-positive as drift.
    if na == nb:
        return UomRelation("equivalent", Decimal(1), None, "identity", True, None)

    with connect() as conn, conn.cursor() as cur:
        to_canonical = _alias_to_canonical(cur, b)
        match = resolve_conversion(cur, client_id, material_code, a, b)
        if match is not None:
            relation, via, confirmed = _SOURCE_TO_RELATION[match.source]
            return UomRelation(relation, match.factor, to_canonical, via,
                               confirmed, None)
        # Symmetric acceptance: a one-directional override row may only
        # exist for b → a. If so, the pair IS convertible; invert the
        # factor for the a → b display direction.
        rev = resolve_conversion(cur, client_id, material_code, b, a)
        if rev is not None:
            relation, via, confirmed = _SOURCE_TO_RELATION[rev.source]
            factor = Decimal(1) / rev.factor if rev.factor else None
            return UomRelation(relation, factor, to_canonical, via,
                               confirmed, None)
        # Incompatible: distinguish "can't resolve a canonical" (fix by
        # adding an alias) from "known canonicals, no factor" (add factor).
        from_canon = _alias_to_canonical(cur, a)
        remediation = "add_factor" if (from_canon and to_canonical) else "add_alias"
        return UomRelation("incompatible", None, to_canonical, None, False,
                           remediation)
