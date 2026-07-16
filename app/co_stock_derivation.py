from __future__ import annotations

import hashlib
import re

from app.client_config_store import resolve_allocation_code
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def co_stock_rows_from_bcct(
    rows: list[dict],
    client_config: dict,
    customs_fx_rows: list[dict] | None = None,
) -> list[dict]:
    """Derive per-lot CO stock rows from raw BCCT.

    `customs_fx_rows` enables FX backfill when the BCCT row's own `ty_gia_thanh_toan`
    column is empty — pre-load once via `get_customs_fx_store().rows()` and pass
    it through (avoid per-row DB hits inside the loop). Leave None to skip FX
    resolution (output rows get `exchange_rate_source="missing"`).
    """
    lot_policy = client_config["co_stock"].get("lot_policy")
    output = []
    for row in rows:
        if row.get("direction") != "import":
            continue
        quantity = row.get("quantity", "")
        source_row = row.get("import_row_id") or import_row_id(row["transaction_key"])
        value_fields = co_stock_value_fields(row, quantity)
        registration_date = (
            row.get("registration_date")
            or row.get("declaration_date")
            or row.get("import_declaration_date")
            or ""
        )
        fx_fields = co_stock_fx_fields(row, value_fields, registration_date, customs_fx_rows)
        eligibility = resolve_stock_eligibility(row, client_config)
        allocation = resolve_allocation_code(row, client_config)
        if lot_policy == "manual_review":
            allocation = review_allocation(allocation, "manual_stock_review")
        usable = eligibility["status"] == "active" and allocation["status"] == "resolved"
        output.append({
            "source_row": source_row,
            "source_transaction_key": row.get("transaction_key", ""),
            "source_line_ids": [source_row],
            "import_declaration_no": row.get("declaration_no", ""),
            "registration_date": registration_date,
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "customs_item_code": row.get("item_code", ""),
            "allocation_code": allocation["allocation_code"],
            "material_code": allocation["allocation_code"] if usable else "",
            "allocation_code_source": allocation["source"],
            "allocation_code_status": allocation["status"],
            "allocation_code_confidence": allocation["confidence"],
            "allocation_code_reason": allocation["reason"],
            "eligibility_status": eligibility["status"],
            "eligibility_reason": eligibility["reason"],
            "eligibility_config_version": client_config.get("config_version", ""),
            "eligibility_config_hash": client_config.get("config_hash", ""),
            "material_description": row.get("material_description") or row.get("description") or row.get("goods_name", ""),
            "hs_code": row.get("hs_code", ""),
            "unit": row.get("unit", ""),
            "origin_country": row.get("origin_country", ""),
            "consignee_name": row.get("consignee_name") or row.get("partner_name", ""),
            "available_qty": quantity,
            "used_qty": "0",
            "remaining_qty": quantity if usable else "0",
            **value_fields,
            **fx_fields,
        })
    if lot_policy == "aggregate_by_declaration_and_allocation_code":
        return aggregate_co_stock_rows(output)
    return output
def co_stock_fx_fields(
    row: dict,
    value_fields: dict,
    registration_date: str,
    customs_fx_rows: list[dict] | None,
) -> dict:
    """Resolve `exchange_rate_to_vnd` + `exchange_rate_source` for one BCCT row.

    Priority:
      1. `value_currency == "VND"` → rate = 1, source = "vnd_native".
      2. BCCT row's own `exchange_rate` (= "ty_gia_thanh_toan", the rate the
         importer declared on the customs form) → "bcct_declared".
      3. `customs_fx_store.lookup_exchange_rate` against the row's registration
         date (weekly granularity — picks the most recent rate ≤ that date) →
         "customs_lookup".
      4. None of the above → rate = 1, source = "missing" (UI shows a chip
         warning; downstream callers may opt-out of VND mode).
    """
    currency = (value_fields.get("value_currency") or value_fields.get("currency") or "").strip().upper()
    if not currency:
        return {"exchange_rate_to_vnd": "", "exchange_rate_source": "missing"}
    if currency == "VND":
        return {"exchange_rate_to_vnd": "1", "exchange_rate_source": "vnd_native"}
    bcct_rate = normalize_decimal(row.get("exchange_rate"))
    if bcct_rate:
        return {"exchange_rate_to_vnd": bcct_rate, "exchange_rate_source": "bcct_declared"}
    if customs_fx_rows:
        from app.customs_fx_store import lookup_exchange_rate
        hit = lookup_exchange_rate(customs_fx_rows, currency, registration_date)
        if hit and hit.get("rate_vnd_per_unit"):
            return {
                "exchange_rate_to_vnd": str(hit["rate_vnd_per_unit"]),
                "exchange_rate_source": "customs_lookup",
            }
    return {"exchange_rate_to_vnd": "", "exchange_rate_source": "missing"}
def co_stock_value_fields(row: dict, quantity: str) -> dict:
    taxable_unit_price = first_normalized_decimal(
        row.get("taxable_unit_price"),
        row.get("unit_price"),
    )
    customs_value = first_normalized_decimal(
        row.get("customs_value"),
        row.get("total_value"),
    )
    foreign_currency_value = first_normalized_decimal(row.get("foreign_currency_value"))
    value_currency = "VND" if customs_value or taxable_unit_price else row.get("currency", "") if foreign_currency_value else ""
    customs_value = customs_value or foreign_currency_value
    quantity_value = decimal_text_value(quantity)
    unit_value = taxable_unit_price
    unit_value_source = "bcct_taxable_unit_price" if unit_value else ""

    if not unit_value and customs_value:
        unit_value = unit_value_from_total(customs_value, quantity)
        unit_value_source = "bcct_customs_value_per_qty" if unit_value else ""
    if not customs_value and unit_value and quantity_value is not None:
        unit_decimal = decimal_text_value(unit_value)
        if unit_decimal is not None:
            customs_value = decimal_to_text(unit_decimal * quantity_value)

    return {
        "customs_value": customs_value,
        "taxable_unit_price": taxable_unit_price,
        "unit_value": unit_value,
        "unit_value_source": unit_value_source,
        "currency": value_currency,
        "value_currency": value_currency,
    }
def first_normalized_decimal(*values) -> str:
    for value in values:
        text = normalize_decimal(value)
        if text:
            return text
    return ""
def resolve_stock_eligibility(row: dict, client_config: dict) -> dict:
    eligible_types = set(client_config["bcct"].get("eligible_import_declaration_types", []))
    if not eligible_types:
        return {"status": "active", "reason": "no_declaration_type_filter"}
    if row.get("declaration_type") in eligible_types:
        return {"status": "active", "reason": "included_by_declaration_type_config"}
    return {"status": "inactive", "reason": "excluded_by_declaration_type_config"}
def review_allocation(allocation: dict, reason: str) -> dict:
    # Keep the wrapped `source` (how the code WOULD derive) — only the status
    # flips to the canonical unresolved because lot_policy holds it for review.
    return {
        **allocation,
        "status": "unresolved",
        "confidence": "low",
        "reason": reason,
    }
def aggregate_co_stock_rows(rows: list[dict]) -> list[dict]:
    grouped = {}
    for row in rows:
        key = (
            row["import_declaration_no"],
            row["allocation_code"],
            row["unit"],
            row.get("currency", ""),
            row["origin_country"],
            row.get("consignee_name", ""),
            row["eligibility_status"],
            row["eligibility_reason"],
            row["allocation_code_status"],
        )
        current = grouped.get(key)
        if current is None:
            grouped[key] = {**row, "source_line_ids": list(row["source_line_ids"])}
            continue
        current["source_line_ids"].extend(row["source_line_ids"])
        current["source_row"] = ",".join(current["source_line_ids"])
        current["line_no"] = ",".join(filter(None, [current.get("line_no", ""), row.get("line_no", "")]))
        current["available_qty"] = sum_decimal_text(current["available_qty"], row["available_qty"])
        current["remaining_qty"] = sum_decimal_text(current["remaining_qty"], row["remaining_qty"])
        if current.get("customs_value") or row.get("customs_value"):
            current["customs_value"] = sum_decimal_text(current.get("customs_value", ""), row.get("customs_value", ""))
        current["taxable_unit_price"] = (
            current.get("taxable_unit_price", "")
            if current.get("taxable_unit_price", "") == row.get("taxable_unit_price", "")
            else ""
        )
        unit_value = unit_value_from_total(current.get("customs_value", ""), current.get("available_qty", ""))
        if unit_value:
            current["unit_value"] = unit_value
            current["unit_value_source"] = "bcct_customs_value_per_qty"
    return list(grouped.values())
def sum_decimal_text(left: str, right: str) -> str:
    left_value = decimal_text_value(left)
    right_value = decimal_text_value(right)
    if left_value is None or right_value is None:
        return cell_text(left) or cell_text(right)
    value = left_value + right_value
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")
def decimal_text_value(value) -> Decimal | None:
    text = normalize_decimal(value)
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None
def unit_value_from_total(customs_value: str, quantity: str) -> str:
    total = decimal_text_value(customs_value)
    qty = decimal_text_value(quantity)
    if total is None or qty is None or qty == 0:
        return ""
    return decimal_to_text(total / qty)
def decimal_to_text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")
def display_bcct_row(row: dict) -> dict:
    return {
        "period": row.get("coverage_period", ""),
        "declaration_no": row.get("declaration_no", ""),
        "direction": "Nhập khẩu" if row.get("direction") == "import" else "Xuất khẩu",
        "declaration_type": row.get("declaration_type", ""),
        "item_code": row.get("item_code", ""),
        "hs_code": row.get("hs_code", ""),
        "qty": row.get("quantity", ""),
        "unit": row.get("unit", ""),
        "customs_value": row.get("customs_value", ""),
        "invoice_ref": row.get("invoice_ref", ""),
        "origin_country": row.get("origin_country", ""),
        "line_no": row.get("line_no", ""),
        "transaction_key": row.get("transaction_key", ""),
        "review_status": row.get("review_status", ""),
    }
def import_row_id(transaction_key_value: str) -> str:
    return f"import-row-{hashlib.sha1(transaction_key_value.encode('utf-8')).hexdigest()[:16]}"
def normalize_decimal(value) -> str:
    text = cell_text(value)
    if not text:
        return ""
    decimal_text = normalize_numeric_text(text)
    try:
        decimal = Decimal(decimal_text)
    except InvalidOperation:
        return text
    if decimal == decimal.to_integral():
        return str(decimal.quantize(Decimal("1")))
    return format(decimal.normalize(), "f")
def normalize_numeric_text(text: str) -> str:
    compact = text.replace(" ", "")
    if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", compact):
        return compact.replace(",", "")
    return text
def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
