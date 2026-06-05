"""Infer BCCT column → field by VALUE patterns, for headerless files.

When a file has no header row the rigid alias match resolves nothing, so
the operator would otherwise map all columns by hand. This pre-fills the
DISTINCTIVE columns (declaration number, date, declaration type, currency,
HS code, material code, exchange rate, goods name) from the data itself.
The purely-numeric soup (quantity / unit_price / total_value …) is left
unmapped on purpose — the values alone can't tell them apart reliably.
"""
from __future__ import annotations

from datetime import datetime

from app.parsers.bcct import EXPORT_TYPES, IMPORT_TYPES

_DECL_TYPES = IMPORT_TYPES | EXPORT_TYPES
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _is_date(v: str) -> bool:
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(v[:10], fmt)
            return True
        except ValueError:
            continue
    return False


def _is_float(v: str):
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


# Ordered high-confidence column detectors. Each returns True if the column
# (its non-empty sample values) looks like that field. Order matters: more
# specific fields first; each field is assigned to at most one column.
def _frac(values, pred) -> float:
    return sum(1 for v in values if pred(v)) / len(values) if values else 0.0


def _detect(values: list[str]) -> str | None:
    if not values:
        return None
    # Declaration number: 11-12 digit code (tight length avoids colliding
    # with large integer money columns).
    if _frac(values, lambda v: v.isdigit() and 11 <= len(v) <= 12) >= 0.8:
        return "declaration_no"
    if _frac(values, lambda v: v.upper() in _DECL_TYPES) >= 0.8:
        return "declaration_type"
    if _frac(values, _is_date) >= 0.8:
        return "registration_date"
    # Currency: 3 UPPERCASE letters (USD/EUR/JPY) — uppercase guard keeps
    # mixed-case unit codes out.
    if _frac(values, lambda v: len(v) == 3 and v.isalpha() and v.isupper()) >= 0.8:
        return "currency_nt"
    # Goods name FIRST (before customs_code): free text — has a space, the
    # "#&" goods separator, or is long. BCCT goods names embed the material
    # code ("005365-00#&Vòng phanh…"), which would otherwise look like a
    # customs_code; the separator/length tells them apart.
    if _frac(values, lambda v: ("#&" in v or " " in v or len(v) > 20)
             and _is_float(v) is None) >= 0.7:
        return "goods_name"
    if _frac(values, lambda v: v.isdigit() and len(v) == 8) >= 0.8:
        return "hs_code"
    # Material/customs code: SHORT alphanumeric (no spaces, no "#&")
    # containing a non-digit (letter or hyphen), not a date. (Numeric
    # money/rate columns are NOT inferred — their values alone can't be told
    # apart, so the operator fills them.)
    if _frac(values, lambda v: len(v) <= 20 and " " not in v and "#&" not in v
             and any(ch.isdigit() for ch in v)
             and any((ch.isalpha() or ch in "-/") for ch in v)
             and not _is_date(v)) >= 0.8:
        return "customs_code"
    return None


def infer_bcct_columns_by_values(data_rows: list[list]) -> dict[int, str]:
    """Return {0-based col index → field} for the columns whose VALUES match
    a distinctive field pattern. Each field is assigned once (first column
    wins); ambiguous numeric columns are omitted."""
    if not data_rows:
        return {}
    n_cols = max(len(r) for r in data_rows)
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for j in range(n_cols):
        values = [_s(r[j]) for r in data_rows if j < len(r) and _s(r[j])]
        field = _detect(values)
        if field and field not in used:
            mapping[j] = field
            used.add(field)
    return mapping
