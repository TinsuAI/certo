from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from re import sub


@dataclass(frozen=True)
class RvcResult:
    fob: Decimal
    non_origin_value: Decimal
    threshold: Decimal
    percentage: Decimal
    passed: bool


@dataclass(frozen=True)
class TariffShiftResult:
    rule: str
    finished_key: str
    input_keys: tuple[str, ...]
    passed: bool
    skipped: bool = False


@dataclass(frozen=True)
class CombinedResult:
    rvc: RvcResult
    tariff_shift: TariffShiftResult
    passed: bool


def money(value: str | int | float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return Decimal("0")
    return Decimal(cleaned)


def percent(value: str | int | float | Decimal) -> Decimal:
    return money(value)


def calculate_rvc(
    fob: str | int | float | Decimal,
    non_origin_value: str | int | float | Decimal,
    threshold: str | int | float | Decimal = "35",
) -> RvcResult:
    fob_value = money(fob)
    non_origin = money(non_origin_value)
    threshold_value = percent(threshold)
    if fob_value <= 0:
        percentage = Decimal("0.00")
    else:
        percentage = ((fob_value - non_origin) / fob_value * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    return RvcResult(
        fob=fob_value,
        non_origin_value=non_origin,
        threshold=threshold_value,
        percentage=percentage,
        passed=percentage >= threshold_value,
    )


def normalize_hs(value: str) -> str:
    return sub(r"\D", "", value or "")


def hs_key(value: str, rule: str) -> str:
    hs = normalize_hs(value)
    levels = {"CC": 2, "CTH": 4, "CTSH": 6}
    return hs[: levels.get(rule.upper(), 6)]


def evaluate_tariff_shift(finished_hs: str, input_hs_values: list[str], rule: str = "CTSH") -> TariffShiftResult:
    finished_key = hs_key(finished_hs, rule)
    input_keys = tuple(hs_key(value, rule) for value in input_hs_values if hs_key(value, rule))
    if not finished_key or not input_keys:
        return TariffShiftResult(
            rule=rule.upper(),
            finished_key=finished_key,
            input_keys=input_keys,
            passed=False,
            skipped=True,
        )
    return TariffShiftResult(
        rule=rule.upper(),
        finished_key=finished_key,
        input_keys=input_keys,
        passed=all(input_key != finished_key for input_key in input_keys),
    )


def evaluate_rvc_ctsh(product: dict) -> CombinedResult:
    non_origin_value = product.get("non_origin_value")
    if non_origin_value in (None, ""):
        non_origin_value = sum(
            money(row.get("non_origin_cif_value", "0"))
            for row in product.get("materials", [])
            if row.get("origin_status") == "non_origin"
        )
    rvc = calculate_rvc(product["fob"], non_origin_value, product.get("rvc_threshold", "35"))
    non_origin_hs = [
        row["hs_code"]
        for row in product.get("materials", [])
        if row.get("origin_status") == "non_origin"
    ]
    tariff_shift = evaluate_tariff_shift(product.get("finished_hs", ""), non_origin_hs, "CTSH")
    return CombinedResult(rvc=rvc, tariff_shift=tariff_shift, passed=rvc.passed and tariff_shift.passed)
