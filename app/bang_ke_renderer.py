"""Config-driven HQ bảng kê renderer.

Reads a JSON config (one per criterion: LVC/RVC/CTH/CTSH/PSR) describing
how to map a CO case + product onto cells of the form-mau xlsx template.
The xlsx file remains the visual master (legal form mẫu per TT 05/2018);
this engine only fills cells, clears example data, writes the body, and
applies footer totals — it never re-implements styling.

Schema reference: see config/bang-ke-forms/lvc.json for the canonical
example. The same engine handles both compact (LVC) and wide (CTH/RVC/PSR)
layouts — layout differences are pure config.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.bang_ke_rows import material_render_parts
from app.origin_material_filters import is_bom_technical_noise, material_override_key

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config" / "bang-ke-forms"


@lru_cache(maxsize=None)
def load_form_config(criterion: str) -> dict:
    """Load and cache the JSON config for a criterion code (LVC/RVC/CTH/...)."""
    path = CONFIG_DIR / f"{criterion.lower()}.json"
    if not path.exists():
        raise FileNotFoundError(f"No bảng kê config for criterion {criterion!r} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def render_into_sheet(
    ws,
    config: dict,
    *,
    case: dict,
    product: dict,
    sheet_title: str,
) -> None:
    """Apply the config to a worksheet already cloned from the form-mau template.

    Caller is responsible for: opening the combined template workbook,
    copying the criterion's sheet, renaming it, and (afterwards) saving the
    workbook to bytes. This keeps the engine pure and easy to test.
    """
    fields = _build_field_table(case, product)
    _apply_header(ws, config.get("header_cells", []), fields)
    _apply_currency_labels(ws, config.get("currency_cells", []), product)
    _clear_cells(ws, config.get("clear_cells", []))
    _clear_body_range(ws, config["body"])
    last_row, totals = _write_body(ws, config["body"], product)
    _apply_footer(ws, config.get("footer", {}), last_row, totals, fields)
    _hide_unused_helpers(ws, config["body"], last_row)
    _apply_print_area(ws, config.get("print_area_template"), sheet_title)


def _clear_body_range(ws, body_cfg: dict) -> None:
    """Wipe every body cell before writing fresh material rows.

    The form-mau templates ship with worked example BOM data at rows 16-end
    (e.g. TEM/TUI/PALLET demo lines for LVC). Without clearing, any row index
    not overwritten by the new material list keeps the template's example
    values and they leak into the export. _hide_unused_helpers later hides
    the still-empty rows; we clear values too so unhiding doesn't reveal
    placeholder data.
    """
    start_row = int(body_cfg.get("start_row", 16))
    end_row = int(body_cfg.get("end_row", start_row))
    last_col_letter = "Y"  # cover both LVC (A-N) and wide layout helper cols (A-Y)
    last_col = _column_index(last_col_letter)
    for row in ws.iter_rows(min_row=start_row, max_row=end_row, max_col=last_col):
        for cell in row:
            cell.value = None


def _column_index(letter: str) -> int:
    result = 0
    for ch in letter.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


# ---- helpers --------------------------------------------------------------


def _build_field_table(case: dict, product: dict) -> dict[str, Any]:
    quantity = _decimal(product.get("quantity") or 0)
    fob = _decimal(product.get("fob") or 0)
    unit_price = fob / quantity if quantity else fob
    declaration_no = product.get("source_declaration_no") or _first_non_empty(
        (case.get("shipment") or {}).get("export_declaration_nos") or []
    )
    declaration_date = (
        product.get("source_declaration_date")
        or product.get("export_declaration_date")
        or ""
    )
    criterion_text = (
        product.get("origin_sheet_effective_criteria_text")
        or product.get("documented_result")
        or ""
    )
    materials = product.get("materials") or []
    overrides = product.get("origin_sheet_material_overrides") or {}
    material_count = _count_visible_materials(materials, overrides)
    return {
        "merchant": (
            case.get("customer_legal_name")
            or case.get("customer", "")
            or case.get("client_name", "")
            or case.get("client_id", "")
        ),
        "tax_code": case.get("customer_tax_code", "") or case.get("client_tax_code", ""),
        "criterion_text": criterion_text,
        "product_name": product.get("name", ""),
        "product_code": product.get("code", ""),
        "finished_hs": product.get("finished_hs", ""),
        "quantity": product.get("quantity", "") or "0",
        "quantity_decimal": quantity,
        "uom": product.get("uom") or product.get("unit") or product.get("export_unit", ""),
        "fob": product.get("fob", "") or "0",
        "fob_decimal": fob,
        "unit_price": unit_price,
        "incoterm": product.get("incoterm", "FOB") or "FOB",
        "source_declaration_no": declaration_no,
        "declaration": {"no": declaration_no, "date": declaration_date},
        "material_count": material_count,
    }


def _apply_header(ws, header_cells: list[dict], fields: dict[str, Any]) -> None:
    for entry in header_cells:
        cell = entry["cell"]
        field = entry.get("field")
        raw = fields.get(field) if field else entry.get("value")
        # `format` template (used for composite values like declaration).
        if "format" in entry and isinstance(raw, dict):
            try:
                rendered = entry["format"].format(**raw)
            except KeyError:
                rendered = ""
            if entry.get("skip_if_empty") and not _has_real_content(raw):
                continue
            ws[cell] = rendered
            continue
        if entry.get("skip_if_empty") and (raw in (None, "", 0, Decimal(0))):
            continue
        if "default" in entry and raw in (None, "", 0):
            raw = entry["default"]
        if "prefix" in entry:
            ws[cell] = f"{entry['prefix']}{_text(raw)}"
        else:
            ws[cell] = raw


def _pick_currency_value(material: dict, base_key: str, use_vnd: bool, product: dict | None = None) -> str:
    """Resolve display value in the target currency.

    Target = "VND" when use_vnd; else product.fob_currency (the export
    invoice currency — the "nguyên tệ" the bảng kê is filed in).

    Direction matrix:
      row.currency == target          → row[base_key]            (no-op)
      target == "VND"                 → row[base_key + "_vnd"]   (canonical)
      target is non-VND, row is VND   → row[base_key + "_vnd"] / fob_fx_rate
                                         (cross-convert VND base into nguyên tệ)

    Falls back to native value when the conversion can't be completed (missing
    fx_rate, missing *_vnd field on legacy data, etc.). The renderer should
    surface an FX-source chip elsewhere so the operator sees the warning."""
    target = _resolve_target_currency(product, use_vnd)
    row_currency = (material.get("currency") or "VND").strip().upper() or "VND"
    if target == row_currency:
        return material.get(base_key, "")
    if target == "VND":
        vnd = material.get(f"{base_key}_vnd")
        return vnd if vnd not in (None, "") else material.get(base_key, "")
    # target is non-VND and row stored in VND (the common growatt case):
    # divide canonical VND value by fob_fx_rate to get the nguyên tệ figure.
    vnd_value = material.get(f"{base_key}_vnd") or material.get(base_key, "")
    fx_rate = (product or {}).get("fob_fx_rate") or ""
    try:
        if vnd_value and fx_rate:
            converted = Decimal(str(vnd_value)) / Decimal(str(fx_rate))
            return _decimal_text(converted)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        pass
    return material.get(base_key, "")


def _resolve_target_currency(product: dict | None, use_vnd: bool) -> str:
    if use_vnd:
        return "VND"
    if not product:
        return "VND"
    raw = product.get("fob_currency") or product.get("currency") or "VND"
    return str(raw).strip().upper() or "VND"


def _decimal_text(value: Decimal) -> str:
    """Match the decimal_text() format used elsewhere — strip trailing zeros."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _apply_currency_labels(ws, cells: list[dict | str], product: dict) -> None:
    """Overwrite template's hardcoded "USD" cells with the product's currency.

    The form-mau template ships with "USD" hardcoded at L10/L11 + "Trị giá (USD)"
    at H13. Without this override, a VND/EUR/etc. case still prints "USD" on
    the bảng kê HQ — a regulatory mismatch the user explicitly flagged.

    Config entry shapes:
        "L10"                          → write currency code verbatim
        {"cell": "H13", "format": "Trị giá ({currency})"}  → templated
    """
    currency_mode = (product.get("origin_sheet_currency_mode") or "native").strip().lower()
    currency = _resolve_target_currency(product, currency_mode == "vnd")
    if not currency:
        return
    for entry in cells:
        if isinstance(entry, str):
            ws[entry] = currency
        elif isinstance(entry, dict) and entry.get("cell"):
            template = entry.get("format") or "{currency}"
            ws[entry["cell"]] = template.format(currency=currency)


def _clear_cells(ws, cells: list[str]) -> None:
    for cell in cells:
        ws[cell].value = None


def _write_body(ws, body_cfg: dict, product: dict) -> tuple[int, dict]:
    cols = body_cfg["columns"]
    start_row = body_cfg["start_row"]
    materials = product.get("materials") or []
    overrides = product.get("origin_sheet_material_overrides") or {}

    row_index = start_row
    counter = 1
    sum_origin = Decimal("0")
    sum_non_origin = Decimal("0")

    def put(key: str, value) -> None:
        col_letter = cols.get(key)
        if not col_letter:
            return
        ws[f"{col_letter}{row_index}"] = value

    currency_mode = (product.get("origin_sheet_currency_mode") or "native").strip().lower()
    use_vnd = currency_mode == "vnd"
    for index, material in enumerate(materials):
        row_key = material_override_key(material, index)
        override = overrides.get(row_key) if isinstance(overrides.get(row_key), dict) else {}
        if override.get("deleted") or is_bom_technical_noise(material):
            continue
        # Render-split fan-out: one row per (origin_status, column-9 text) group
        # of the material's lots; with uniform keys (all of today's data) the
        # single part IS the material dict, so rendering is unchanged.
        for part in material_render_parts(material):
            material_code = override.get("material_code") or part.get("material_code", "")
            # Bảng kê hiện mã HQ (customs_item_code của lô khớp); mã allocation/nội bộ
            # chỉ để tra cứu/khớp tồn (giữ cho decl_mat_key). Fallback nội bộ khi NVL
            # chưa khớp lô.
            hq_code = override.get("customs_material_code") or part.get("customs_material_code") or material_code
            material_name = override.get("name") or part.get("material_description", "")
            norm = override.get("norm_per_unit") or part.get("bom_qty_per", "0")
            consumed_qty = _decimal(part.get("consumed_qty") or norm)
            unit_price = _decimal(_pick_currency_value(part, "unit_value", use_vnd, product))
            material_value = _decimal(_pick_currency_value(part, "material_value", use_vnd, product))
            is_origin = str(part.get("origin_status") or "non_origin") == "origin"
            origin_value = material_value if is_origin else Decimal("0")
            non_origin_value = material_value if not is_origin else Decimal("0")
            sum_origin += origin_value
            sum_non_origin += non_origin_value

            put("stt", counter)
            put("name", material_name)
            put("material_code", hq_code)
            put("hs", part.get("hs_code", ""))
            put("uom", part.get("uom", ""))
            put("norm", _text(norm))
            put("qty", _text(consumed_qty))
            put("unit_price", _text(unit_price))
            put("origin_value", _text(origin_value))
            put("non_origin_value", _text(non_origin_value))
            put("country", part.get("bang_ke_origin_text") or part.get("origin_country", ""))
            put("import_decl_no", part.get("import_declaration_no", ""))
            put(
                "import_decl_date",
                part.get("import_declaration_date")
                or part.get("declaration_date")
                or part.get("registration_date")
                or "",
            )
            # Cột M-N ("C/O ưu đãi nhập khẩu / Bản khai báo của nhà SX / NCC NVL
            # trong nước") — pure reader of the text materialized at Tính; the
            # VN-origin resolver ticket fills the content for qualifying rows.
            put("co_doc_no", part.get("bang_ke_co_doc_no", ""))
            put("co_doc_date", part.get("bang_ke_co_doc_date", ""))
            # Legacy helper columns (only present on wide layouts).
            put("import_line_no", part.get("import_line_no", ""))
            put("decl_mat_key", f"{product.get('source_declaration_no', '')}{material_code}")
            put("decl_type", part.get("import_declaration_type", ""))
            put("product_code", product.get("code", ""))
            put("product_line", product.get("source_line_no", ""))
            put("product_qty", product.get("quantity", ""))

            row_index += 1
            counter += 1

    # Added-row overrides at the end.
    for key, value in overrides.items():
        if not key.startswith("added_") or not isinstance(value, dict):
            continue
        put("stt", counter)
        put("name", value.get("name", ""))
        put("material_code", value.get("material_code", ""))
        put("hs", value.get("hs_code", ""))
        put("uom", value.get("uom", ""))
        put("norm", _text(value.get("norm_per_unit", "0")))
        put("product_code", product.get("code", ""))
        row_index += 1
        counter += 1

    totals = {
        "origin": sum_origin,
        "non_origin": sum_non_origin,
        "fob": _decimal(product.get("fob") or "0"),
        "start_row": start_row,
        "last_row": max(row_index - 1, start_row),
    }
    return row_index, totals


def _apply_footer(ws, footer_cfg: dict, last_row: int, totals: dict, fields: dict) -> None:
    sources = {
        "origin": _text(totals["origin"]),
        "non_origin": _text(totals["non_origin"]),
        "fob": _text(totals["fob"]),
    }
    for entry in footer_cfg.get("sums", []):
        cell = entry["cell"]
        if "formula" in entry:
            ws[cell] = entry["formula"].format(
                start=totals["start_row"], last=totals["last_row"]
            )
        elif "source" in entry:
            value = sources.get(entry["source"])
            if entry["source"] == "ratio":
                value = _compute_ratio(totals)
            ws[cell] = value
        elif "value" in entry:
            ws[cell] = entry["value"]

    conclusion = footer_cfg.get("conclusion")
    if conclusion:
        for clear_cell in conclusion.get("also_clear", []):
            ws[clear_cell].value = None
        fob = totals["fob"]
        if conclusion.get("requires_fob") and fob <= 0:
            return
        params = {
            "ratio_percent": _ratio_percent(totals),
            "criterion": fields.get("criterion_text", ""),
            "merchant": fields.get("merchant", ""),
        }
        try:
            text = conclusion["template"].format(**params)
        except KeyError as exc:
            raise ValueError(f"Conclusion template references unknown field {exc!r}") from exc
        ws[conclusion["cell"]] = text


def _hide_unused_helpers(ws, body_cfg: dict, first_blank_row: int) -> None:
    if not body_cfg.get("hide_unused_rows"):
        return
    body_end = body_cfg["end_row"]
    for row in range(max(first_blank_row, body_cfg["start_row"]), body_end + 1):
        ws.row_dimensions[row].hidden = True
    for col_letter in body_cfg.get("hidden_helper_cols", []):
        ws.column_dimensions[col_letter].hidden = True


def _apply_print_area(ws, template: str | None, sheet_title: str) -> None:
    if not template:
        return
    ws.print_area = template.format(sheet_name=sheet_title)


# ---- value coercion -------------------------------------------------------


def _decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _first_non_empty(values) -> str:
    for value in values or []:
        text = _text(value).strip()
        if text:
            return text
    return ""


def _has_real_content(composite: dict) -> bool:
    return any(_text(v).strip() for v in composite.values())


def _ratio_percent(totals: dict) -> str:
    fob = totals["fob"]
    if fob <= 0:
        return "0.00"
    ratio = (fob - totals["non_origin"]) / fob
    return str((ratio * Decimal("100")).quantize(Decimal("0.01")))


def _compute_ratio(totals: dict) -> str:
    fob = totals["fob"]
    if fob <= 0:
        return "0"
    return str(((fob - totals["non_origin"]) / fob).quantize(Decimal("0.0001")))


def _count_visible_materials(materials: list[dict], overrides: dict) -> int:
    count = 0
    for index, _material in enumerate(materials):
        row_key = material_override_key(_material, index)
        override = overrides.get(row_key) if isinstance(overrides.get(row_key), dict) else {}
        if not override.get("deleted"):
            count += len(material_render_parts(_material))
    count += sum(
        1
        for key, value in overrides.items()
        if key.startswith("added_") and isinstance(value, dict) and not value.get("deleted")
    )
    return count
