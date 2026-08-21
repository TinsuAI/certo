"""UOM conversion — pure. Lookup precedence per spec §9 lives in the
injected `UomLookup` callable (app/stores/uom.py builds it). This module
just normalizes alias strings + applies a returned ConversionMatch.
"""
from __future__ import annotations

import unicodedata
from decimal import Decimal

from hub.app.flatten.types import ConversionMatch, UomLookup


def normalize_uom_alias(s: str | None) -> str:
    """Lowercase + NFC + strip whitespace. Used as the lookup key against
    hub.uom_aliases. Returns '' for None/empty."""
    if not s:
        return ""
    n = unicodedata.normalize("NFC", str(s)).strip().lower()
    # Collapse internal whitespace.
    return " ".join(n.split())


def convert_qty(
    qty: Decimal | float | int | None,
    from_uom: str | None,
    to_uom: str | None,
    *,
    material_code: str | None,
    lookup: UomLookup,
) -> tuple[Decimal | None, ConversionMatch | None, str | None]:
    """Convert `qty from_uom → to_uom`, returning (qty', match, error).

    Cases:
    - qty None / 0 → (Decimal(0), None, None) — nothing to convert.
    - to_uom None or empty → (qty, None, 'canonical_uom_missing') — caller
      decides whether to surface as unresolved or accept as-is.
    - from_uom alias-equals to_uom (after normalize) → (qty, alias_match, None).
    - lookup returns a ConversionMatch → multiply factor.
    - lookup returns None → (None, None, 'uom_conversion_missing').
    """
    if qty is None:
        return Decimal(0), None, None
    q = qty if isinstance(qty, Decimal) else Decimal(str(qty))

    if to_uom is None or to_uom == "":
        # Caller decides whether canonical_uom_missing is fatal. We
        # propagate the original quantity unmodified.
        return q, None, "canonical_uom_missing"

    fnorm = normalize_uom_alias(from_uom)
    tnorm = normalize_uom_alias(to_uom)

    if fnorm == tnorm and fnorm != "":
        return q, ConversionMatch(
            factor=Decimal(1), from_uom=from_uom or "", to_uom=to_uom,
            source="alias",
        ), None

    match = lookup(material_code or "", from_uom, to_uom)
    if match is None:
        return None, None, "uom_conversion_missing"
    return q * match.factor, match, None
