"""BOM đơn vị tính ↔ the import lot's đơn vị tính.

CO allocates a BOM demand against customs lots whose unit is whatever the
declaration says. Until now the two were never compared, so a demand in EA was
subtracted from a lot counted in SETS as if 1 EA = 1 SET (prod johnson-vn: 226 of
3,816 allocated lines have differing units, 42 of them across families).

Three outcomes, in order:

- `same_uom` / `uom_alias` — the same unit written another way, including the
  Vietnamese name (EA = PIECES = CÁI). Factor 1, nothing to confirm.
- `uom_family` — the same physical quantity in a different scale (KG → G). The
  factor is arithmetic, not a business judgement, so it is applied directly.
- `unconfirmed` — different quantities (EA ↔ SETS, KG ↔ PIECES). How many pieces a
  set holds is a fact about the material, not about units, so it must come from a
  human: the operator confirms it on the row and it is stored per client
  (`app/uom_factor_store.py`). Until then the row keeps its 1:1 numbers and is
  flagged, so Tính still works and Chốt is blocked.

`resolve_uom_factor` returns the factor to multiply a BOM quantity by to get the
LOT's unit (EA → SETS with 1 SET = 5 EA is 0.2), plus the source label that the
row and the audit trail carry.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Same unit, different spelling or language. Keys are the canonical name.
_ALIASES: dict[str, set[str]] = {
    "PIECES": {
        "PIECES", "PIECE", "PCS", "PCE", "PC", "EA", "EACH", "UNIT", "UNITS", "NOS",
        "CAI", "CÁI", "CHIEC", "CHIẾC", "CON",
    },
    "SETS": {"SETS", "SET", "BO", "BỘ"},
    "PAIRS": {"PAIRS", "PAIR", "PRS", "DOI", "ĐÔI"},
    "ROLLS": {"ROLLS", "ROLL", "CUON", "CUỘN"},
    "SHEETS": {"SHEETS", "SHEET", "TAM", "TẤM"},
    "BOXES": {"BOXES", "BOX", "CARTON", "CARTONS", "CTN", "THUNG", "THÙNG", "HOP", "HỘP"},
    "BAGS": {"BAGS", "BAG", "TUI", "TÚI", "BAO"},
    "KILOGRAMS": {"KILOGRAMS", "KILOGRAM", "KILO-GRAMMES", "KILOGRAMME", "KILOGRAMMES", "KGS", "KG"},
    "GRAMS": {"GRAMS", "GRAM", "GRAMMES", "GRAMME", "GRS", "GR", "G"},
    "METRIC-TONS": {"METRIC-TONS", "METRIC-TON", "TONNES", "TONNE", "TONS", "TON", "MT", "TAN", "TẤN"},
    "METERS": {"METERS", "METER", "METRES", "METRE", "MET", "M"},
    "CENTIMETERS": {"CENTIMETERS", "CENTIMETER", "CM"},
    "MILLIMETERS": {"MILLIMETERS", "MILLIMETER", "MM"},
    "LITERS": {"LITERS", "LITER", "LITRES", "LITRE", "LIT", "L"},
    "MILLILITERS": {"MILLILITERS", "MILLILITER", "ML"},
    "SQUARE-METERS": {"SQUARE-METERS", "SQUARE-METER", "SQM", "M2", "M²"},
}

# Same physical quantity, different scale: value in the family's base unit.
_FAMILIES: dict[str, dict[str, Decimal]] = {
    "mass": {"GRAMS": Decimal("0.001"), "KILOGRAMS": Decimal("1"), "METRIC-TONS": Decimal("1000")},
    "length": {
        "MILLIMETERS": Decimal("0.001"), "CENTIMETERS": Decimal("0.01"), "METERS": Decimal("1"),
    },
    "volume": {"MILLILITERS": Decimal("0.001"), "LITERS": Decimal("1")},
}


def canonical_uom(uom: str) -> str:
    """Canonical name of a unit, or the cleaned input when it is unknown."""
    cleaned = str(uom or "").strip().upper().replace("_", "-")
    if not cleaned:
        return ""
    for canonical, spellings in _ALIASES.items():
        if cleaned in spellings:
            return canonical
    return cleaned


def _family_of(canonical: str) -> tuple[str, Decimal] | None:
    for family, members in _FAMILIES.items():
        if canonical in members:
            return family, members[canonical]
    return None


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def resolve_uom_factor(
    bom_uom: str,
    lot_uom: str,
    *,
    confirmed: dict | None = None,
    material_code: str = "",
) -> tuple[Decimal | None, str]:
    """Factor that turns a BOM quantity into the LOT's unit, plus its source.

    `confirmed` is the client's operator-confirmed map — keys `(bom_uom, lot_uom)` for
    client-wide and `(bom_uom, lot_uom, material_code)` for one material, which wins.
    Returns `(None, "unconfirmed")` when the pair crosses quantities and no human has
    said how they relate."""
    bom_canonical = canonical_uom(bom_uom)
    lot_canonical = canonical_uom(lot_uom)
    # An operator confirmation is authoritative even for a pair we could derive:
    # they are looking at the declaration, we are looking at a table. Keys are matched
    # canonically first (that is how the store writes them) and then as typed, so a map
    # assembled elsewhere with raw spellings still resolves.
    material_key = str(material_code or "").strip()
    bom_raw = str(bom_uom or "").strip().upper()
    lot_raw = str(lot_uom or "").strip().upper()
    candidate_keys = [
        (bom_canonical, lot_canonical, material_key),
        (bom_raw, lot_raw, material_key),
        (bom_canonical, lot_canonical),
        (bom_raw, lot_raw),
    ]
    for key in candidate_keys:
        if not confirmed or (len(key) == 3 and not key[2]):
            continue
        hit = _decimal(confirmed.get(key))
        if hit is not None and hit > 0:
            return hit, "operator_confirmed"
    if not bom_canonical or not lot_canonical:
        # Nothing recorded on one side — there is no mismatch to report, and refusing
        # to allocate would block on missing metadata rather than on a real conflict.
        return Decimal("1"), "uom_unknown"
    if bom_canonical == lot_canonical:
        return Decimal("1"), "same_uom" if str(bom_uom).strip().upper() == str(lot_uom).strip().upper() else "uom_alias"
    bom_family = _family_of(bom_canonical)
    lot_family = _family_of(lot_canonical)
    if bom_family and lot_family and bom_family[0] == lot_family[0]:
        return bom_family[1] / lot_family[1], "uom_family"
    return None, "unconfirmed"
