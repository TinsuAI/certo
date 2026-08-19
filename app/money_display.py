"""How many decimals a money cell on the bảng kê shows.

Operator, 2026-08-19: "Đơn giá và giá trị mà VNĐ mà để nhiều số sau dấu phẩy khó
chịu quá". A VND figure is filed in whole đồng, so six decimals on it is noise —
but the same column also carries USD lots where six decimals are the number.

So the count follows the currency the CELL is printed in (a sheet on the nguyên-tệ
lane mixes VND and USD rows), not the sheet:

- VND → 0
- anything else → 6 for an đơn giá, 2 for a trị giá

with one guard that is not optional: a NON-ZERO value never renders as "0". Real
data has đơn giá 0.078 VND (johnson-vn 1000096510), and a cell reading "0" is how
this app says "thiếu đơn giá" — printing that over a priced row would send the
operator hunting a defect that is not there. Such a cell keeps enough decimals to
show its first significant digit.

The operator can override the count per bảng kê (`display_decimals` on the sheet
state). This is a screen setting only: the exported file keeps the full value and
takes its number format from the HQ template (`bang_ke_xml_generator`), which is the
agency's business, not a display preference.

Mirrored in `co_case.html` as `fmtMoney` — the browser reformats these cells when the
Tiền tệ lane is switched, so both sides must agree.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

MAX_DECIMALS = 8
UNIT_DECIMALS = 6
AMOUNT_DECIMALS = 2


def _decimal(value) -> Decimal | None:
    text = "" if value is None else str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def normalize_display_decimals(value) -> str:
    """Sanitise the per-sheet override. "" means automatic."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = int(Decimal(text))
    except (InvalidOperation, ValueError):
        return ""
    return str(max(0, min(number, MAX_DECIMALS)))


def money_decimals(currency: str = "", kind: str = "amount", override: str = "") -> int:
    fixed = normalize_display_decimals(override)
    if fixed:
        return int(fixed)
    if str(currency or "").strip().upper() == "VND":
        return 0
    return UNIT_DECIMALS if kind == "unit" else AMOUNT_DECIMALS


def _visible_decimals(number: Decimal, start: int) -> tuple[int, bool]:
    """Decimals to actually use, and whether the small-value guard had to widen them.

    Anchored on the first significant decimal place, found by TRUNCATION — rounding
    would say 0.078 is visible at one decimal ("0,1"), which is a different number.
    One extra place after it keeps a second digit: 0.078 → "0,078".
    """
    magnitude = abs(number)
    if magnitude == 0:
        return start, False
    quant = Decimal("1").scaleb(-start)
    if magnitude.quantize(quant, rounding=ROUND_DOWN) > 0:
        return start, False
    # adjusted() is the exponent of the leading digit: 0.078 → -2 → first significant
    # decimal place is the 2nd.
    first_significant = -magnitude.adjusted()
    return min(first_significant + 1, MAX_DECIMALS), True


def format_money(value, currency: str = "", kind: str = "amount", override: str = "") -> str:
    """Vietnamese convention — "." groups thousands, "," starts the decimals.

    Trailing zeros are kept so a money column stays aligned; only a cell widened by
    the small-value guard is trimmed, because its extra places exist to show one
    number, not to match the column.
    """
    number = _decimal(value)
    if number is None:
        return "" if value is None or str(value).strip() == "" else str(value)
    decimals, guarded = _visible_decimals(number, money_decimals(currency, kind, override))
    quant = Decimal("1").scaleb(-decimals)
    rounded = number.quantize(quant, rounding=ROUND_HALF_UP)
    text = f"{rounded:,.{decimals}f}"
    if not decimals:
        return text.replace(",", ".")
    whole, _, fraction = text.partition(".")
    if guarded:
        fraction = fraction.rstrip("0")
    return f"{whole.replace(',', '.')}{',' + fraction if fraction else ''}"
