"""Damage/benefit computation for supplier evidence flips (ticket #11).

Computed ON DEMAND from locked sheet snapshots — Tính materialized
`supplier_key` (and, once the resolver ticket lands, per-line origin_status)
onto every allocation line, so locked sheets are self-contained and no extra
persistence is needed. Flipping a flag never modifies any sheet; these lists
only tell the operator what the flip means legally.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.origin_country import is_vietnam_origin


def supplier_damage_list(cases: list[dict], supplier_key: str) -> list[dict]:
    """ON→OFF confirm material: locked sheets whose snapshots counted this
    supplier's rows as ORIGINATING (case, sheet, originating amount). Issued
    dossiers keep standing on evidence the agency no longer holds — the
    operator must see that before confirming."""
    return _scan_locked_sheets(cases, supplier_key, mode="damage")


def supplier_benefit_list(cases: list[dict], supplier_key: str) -> list[dict]:
    """OFF→ON info material: locked sheets carrying VN lots of this supplier
    that were NOT counted originating — re-opening + re-Tính would raise their
    RVC."""
    return _scan_locked_sheets(cases, supplier_key, mode="benefit")


def _scan_locked_sheets(cases: list[dict], supplier_key: str, *, mode: str) -> list[dict]:
    key = str(supplier_key or "").strip()
    if not key:
        return []
    hits: list[dict] = []
    for case in cases or []:
        states = case.get("origin_sheet_states")
        if not isinstance(states, dict):
            continue
        locked_codes = {
            str(code)
            for code, state in states.items()
            if isinstance(state, dict) and state.get("status") == "locked"
        }
        if not locked_codes:
            continue
        case_code = str(case.get("case_code") or case.get("case_id") or "")
        case_id = str(case.get("case_id") or case.get("persisted_case_id") or "")
        for product in case.get("products") or []:
            product_code = str(product.get("code") or "")
            if product_code not in locked_codes:
                continue
            amount = Decimal("0")
            matched = False
            for material in product.get("materials") or []:
                if material.get("deleted"):
                    continue
                for line in material.get("allocation_lines") or []:
                    if str(line.get("supplier_key") or "") != key:
                        continue
                    line_status = str(line.get("origin_status") or material.get("origin_status") or "non_origin")
                    if mode == "damage" and line_status == "origin":
                        matched = True
                        amount += _decimal(line.get("material_value"))
                    elif mode == "benefit" and line_status != "origin" and is_vietnam_origin(line.get("origin_country")):
                        matched = True
                        amount += _decimal(line.get("material_value"))
            if matched:
                hits.append({
                    "case_id": case_id,
                    "case_code": case_code,
                    "product_code": product_code,
                    "originating_amount": _text(amount),
                })
    return hits


def _decimal(value) -> Decimal:
    text = str(value if value is not None else "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")
