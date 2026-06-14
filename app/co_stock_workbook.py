"""Converter: agency trừ-lùi workbook → the system's STANDARD CO stock template.

ADD-ON TOOL ONLY — this module does NOT touch the system DB. It parses an agency
workbook (`.xlsm`) and produces the canonical `co_stock_template` `.xlsx`. The
operator downloads that standard template and ingests it themselves via the
existing "Import tồn CO" upload on the Tồn CO page. Conversion and ingestion are
deliberately decoupled.

Sheet profiles for the agency layouts live in `SHEET_PROFILES`. The parsing half
is shared with the CLI `scripts/convert_co_stock.py`.
"""
from __future__ import annotations

import hashlib
import warnings
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.client_config_store import resolve_allocation_code
from app.co_stock_derivation import cell_text, decimal_to_text
from app.co_stock_template import CO_STOCK_COLUMNS, read_standard_co_stock, write_standard_co_stock

DEFAULT_SHEET = "NK2"

# Agency Save sheet column index (0-based) → standard template key.
# Save is an EVENT LOG: each row = one CO write-down for one export decl.
# Header row at index 0 (data starts row 2).
AGENCY_SAVE_COLUMN_MAP: dict[int, str] = {
    0: "declaration_no",      # A: Số TK
    1: "registration_date",   # B: Ngày ĐK
    2: "declaration_type",    # C: Mã loại hình
    3: "line_no",             # D: STT hàng
    4: "customs_code",        # E: Mã NPL/SP
    5: "hs_code",             # F: Mã HS
    6: "goods_name",          # G: Tên hàng
    7: "origin_country",      # H: Xuất xứ
    8: "unit_price",          # I: Đơn giá
    9: "taxable_unit_price",  # J: Đơn giá tính thuế
    10: "opening_qty",        # K: Tồn-before-this-event (first row's K = true opening per consolidation)
    11: "unit",               # L: Đơn vị tính
    12: "partner",            # M: Tên đối tác
    13: "invoice_no",         # N: Số hóa đơn
    14: "invoice_date",       # O: Ngày hóa đơn
    15: "exchange_rate",      # P: Tỷ giá thanh toán
    19: "used_qty",           # T: Số lượng XUẤT (this row's used qty)
    20: "source_co_no",       # U: Số CO (usually empty — agency tracks via TKX)
    22: "transaction_key",    # W: composite key
}

# Agency NK2 sheet column index (0-based) → standard template key.
# NK2 is the RECONCILED per-lot snapshot: one row per BCCT lot with the
# agency's official `Đã xuất` cumulative used. Header row at index 3
# (data starts row 5).
AGENCY_NK2_COLUMN_MAP: dict[int, str] = {
    0: "declaration_no",      # A: Số TK
    1: "registration_date",   # B: Ngày ĐK
    2: "declaration_type",    # C: Mã loại hình
    3: "line_no",             # D: STT hàng
    4: "customs_code",        # E: Mã NPL/SP
    5: "hs_code",             # F: Mã HS
    6: "goods_name",          # G: Tên hàng
    7: "origin_country",      # H: Xuất xứ
    8: "unit_price",          # I: Đơn giá
    9: "taxable_unit_price",  # J: Đơn giá tính thuế
    10: "opening_qty",        # K: Tổng số lượng (= BCCT raw qty)
    11: "unit",               # L: Đơn vị tính
    12: "partner",            # M: Tên đối tác
    13: "invoice_no",         # N: Số hóa đơn
    14: "invoice_date",       # O: Ngày hóa đơn
    15: "exchange_rate",      # P: Tỷ giá thanh toán
    16: "used_qty",           # Q: Đã xuất (agency snapshot — source of truth)
    17: "ton_workbook",       # R: "Tồn" = K - Q via Excel formula — read for cross-check only
    19: "transaction_key",    # T: TKX Đã cộng dồn (last consuming export decl)
}

# (sheet_name) -> (column_map, data_start_row)
# NOTE: Johnson and Growatt ship DIFFERENT trừ-lùi layouts; add a profile per
# real layout once their sample files are available (see backlog "Review Tồn CO").
SHEET_PROFILES: dict[str, tuple[dict[int, str], int]] = {
    "NK2": (AGENCY_NK2_COLUMN_MAP, 5),
    "Save": (AGENCY_SAVE_COLUMN_MAP, 2),
}

_DECIMAL_KEYS = {"opening_qty", "used_qty", "unit_price", "taxable_unit_price", "exchange_rate", "ton_workbook"}
_DATE_KEYS = {"registration_date", "invoice_date"}


class CoStockWorkbookError(ValueError):
    """Raised when the uploaded workbook can't be parsed (missing/unknown sheet)."""


def _coerce_value(key: str, raw):
    if raw in (None, ""):
        return None
    if key in _DECIMAL_KEYS:
        try:
            return Decimal(str(raw).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
    if key in _DATE_KEYS:
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        return None
    if isinstance(raw, str):
        return raw.strip()
    return raw


def _merge(existing: dict, incoming: dict, *, dup_source_cos: set[str]) -> dict:
    out = dict(existing)
    for key in CO_STOCK_COLUMNS:
        new_value = incoming.get(key)
        if new_value in (None, ""):
            continue
        if key == "used_qty":
            prev = out.get("used_qty") or Decimal("0")
            out["used_qty"] = (prev or Decimal("0")) + new_value
        elif key == "source_co_no":
            text = str(new_value).strip()
            if text and text not in dup_source_cos:
                dup_source_cos.add(text)
                if out.get("source_co_no"):
                    out["source_co_no"] = f"{out['source_co_no']}; {text}"
                else:
                    out["source_co_no"] = text
        elif not out.get(key):
            out[key] = new_value
    return out


def matching_code(goods_name, npl_code) -> str:
    """The code the CO system keys lots on = BCCT `customs_item_code` = the
    "<code>#&description" PREFIX of the goods name.

    Verified against real data + co_stock_rows (Growatt + Johnson, 100%): Data
    Hub derives `customs_item_code` from the name prefix. For Johnson that prefix
    is the unified code (= Mã NPL/SP); for GROWATT it's a category like "DIOT"
    while the Mã NPL/SP column holds the dotted internal/BOM code ("008.x") which
    lives in `allocation_code`, NOT the lot key — so keying on Mã NPL/SP would
    match 0 lots and the trừ-lùi "Đã xuất" would never apply (SAI TỒN). Falls
    back to the Mã NPL/SP column only when the name has no "#&" delimiter.
    """
    name = str(goods_name or "")
    if "#&" in name:
        prefix = name.split("#&", 1)[0].strip()
        if prefix:
            return prefix
    return str(npl_code or "").strip()


def parse_workbook(
    source: bytes | str | Path,
    *,
    sheet: str = DEFAULT_SHEET,
    include_zero_used: bool = True,
) -> tuple[list[dict], dict]:
    """Parse an agency workbook into standard CO-stock rows + a summary.

    Returns `(rows, summary)`. Each row is keyed by the standard-template keys
    (`declaration_no`, `line_no`, `customs_code`, `opening_qty`, `used_qty`, …).
    Rows sharing the (declaration_no, line_no, customs_code) triplet are
    consolidated (used_qty summed). Rows missing the triplet are dropped and
    listed in `summary["dropped"]`.

    `include_zero_used=True` keeps lots with `Đã xuất = 0` (the standard template
    should mirror the whole agency snapshot). The CLI defaults this False for the
    legacy Data-Hub-overlay path.
    """
    warnings.filterwarnings("ignore")
    if isinstance(source, (bytes, bytearray)):
        handle: Any = BytesIO(bytes(source))
    else:
        handle = source
    wb = load_workbook(handle, read_only=True, data_only=True, keep_vba=False)
    try:
        if sheet not in wb.sheetnames:
            raise CoStockWorkbookError(
                f"Sheet '{sheet}' không có trong workbook. Sheets có sẵn: {wb.sheetnames}"
            )
        if sheet not in SHEET_PROFILES:
            raise CoStockWorkbookError(
                f"Sheet '{sheet}' chưa có profile. Hỗ trợ: {list(SHEET_PROFILES.keys())}"
            )
        column_map, data_start_row = SHEET_PROFILES[sheet]
        ws = wb[sheet]
        rows_in = 0
        rows_skipped_zero = 0
        dropped: list[str] = []
        consolidated: OrderedDict[tuple, dict] = OrderedDict()
        dup_tracker: dict[tuple, set[str]] = {}
        iterator = ws.iter_rows(min_row=data_start_row, values_only=True)
        for excel_row, raw_row in enumerate(iterator, start=data_start_row):
            if raw_row is None:
                continue
            if not any(cell not in (None, "") for cell in raw_row):
                continue
            record: dict = {}
            for col_idx, key in column_map.items():
                if col_idx >= len(raw_row):
                    continue
                record[key] = _coerce_value(key, raw_row[col_idx])
            rows_in += 1
            if not include_zero_used and sheet == "NK2":
                used_val = record.get("used_qty")
                if used_val is None or used_val == Decimal("0"):
                    rows_skipped_zero += 1
                    continue
            declaration_no = str(record.get("declaration_no") or "").strip()
            line_no_v = str(record.get("line_no") or "").strip()
            # Key on the BCCT lot code (name "#&" prefix), NOT the Mã NPL/SP
            # column — see matching_code(): Growatt's Mã NPL/SP is the internal
            # code, which is NOT the system's lot key.
            customs_code = matching_code(record.get("goods_name"), record.get("customs_code"))
            if not (declaration_no and line_no_v and customs_code):
                dropped.append(
                    f"Dòng {excel_row}: thiếu declaration_no/line_no/customs_code "
                    f"(decl={declaration_no!r}, line={line_no_v!r}, code={customs_code!r})"
                )
                continue
            record["declaration_no"] = declaration_no
            record["line_no"] = line_no_v
            record["customs_code"] = customs_code
            key = (declaration_no, line_no_v, customs_code)
            dup_tracker.setdefault(key, set())
            if key in consolidated:
                consolidated[key] = _merge(consolidated[key], record, dup_source_cos=dup_tracker[key])
            else:
                consolidated[key] = record
                if record.get("source_co_no"):
                    dup_tracker[key].add(str(record["source_co_no"]).strip())
    finally:
        wb.close()
    rows = list(consolidated.values())
    # Bake remaining = opening − used (post-consolidation) + cross-check the
    # workbook's own "Tồn" column (formula = K−Q); flag rows where they disagree
    # (manual edit / stale formula cache).
    ton_mismatch = 0
    for r in rows:
        opening = _num(r.get("opening_qty"))
        used = _num(r.get("used_qty"))
        remaining = opening - used
        r["remaining_qty"] = remaining
        ton = r.pop("ton_workbook", None)
        if ton not in (None, "") and abs(_num(ton) - remaining) > Decimal("0.001"):
            ton_mismatch += 1
    summary = {
        "sheet": sheet,
        "rows_in": rows_in,
        "rows_unique": len(rows),
        "rows_dropped": len(dropped),
        "rows_skipped_zero_used": rows_skipped_zero,
        "duplicates_merged": rows_in - len(rows) - len(dropped) - rows_skipped_zero,
        "ton_mismatch": ton_mismatch,
        "dropped": dropped,
    }
    return rows, summary


def _num(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    text = cell_text(value)
    if not text:
        return Decimal("0")
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _preview_row(r: dict) -> dict:
    opening = _num(r.get("opening_qty"))
    used = _num(r.get("used_qty"))
    return {
        "declaration_no": cell_text(r.get("declaration_no")),
        "line_no": cell_text(r.get("line_no")),
        "customs_code": cell_text(r.get("customs_code")),
        "goods_name": cell_text(r.get("goods_name")),
        "unit": cell_text(r.get("unit")),
        "opening_qty": decimal_to_text(opening),
        "used_qty": decimal_to_text(used),
        "remaining_qty": decimal_to_text(opening - used),
    }


def convert_to_standard_template(
    source: bytes | str | Path,
    *,
    sheet: str = DEFAULT_SHEET,
    include_zero_used: bool = True,
    preview_limit: int = 25,
) -> tuple[bytes, dict, list[dict]]:
    """Agency workbook → the system's STANDARD CO stock template (.xlsx).

    Returns `(xlsx_bytes, summary, preview_rows)`. Pure conversion — no DB write.
    The operator downloads `xlsx_bytes` and ingests it via the existing
    "Import tồn CO" upload. `preview_rows` show a computed `remaining = opening −
    used` for the operator to eyeball before ingesting.
    """
    standard_rows, summary = parse_workbook(source, sheet=sheet, include_zero_used=include_zero_used)
    xlsx_bytes = write_standard_co_stock(standard_rows)
    preview = [_preview_row(r) for r in standard_rows[: max(0, preview_limit)]]
    return xlsx_bytes, summary, preview


def _source_row(declaration_no: str, line_no: str) -> str:
    """Deterministic per-lot id from the (decl, line) identity. Stable across
    re-imports so `co_stock_claims` (keyed on source_row) survive a re-upload."""
    raw = f"{declaration_no}|{line_no}"
    return "costock-wb-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def stock_rows_from_standard(standard_rows: list[dict], config: dict) -> list[dict]:
    """Map STANDARD CO-stock template rows → self-contained `co_stock_rows` payloads.

    `remaining_qty` is baked (prefer the row's `remaining_qty`, else opening − used);
    `baseline_used_qty = opening − remaining` so the read-time `apply_used_qty` overlay
    honours the baked remaining (`remaining − live ledger`). `allocation_code` is
    resolved per client_config (`resolve_allocation_code`) so BOM matching works
    (Growatt description_regex → dotted; Johnson same_as_customs_code). No fold, no
    BCCT — the template IS the stock (workbook-snapshot model).
    """
    out: list[dict] = []
    for r in standard_rows:
        decl = str(r.get("declaration_no") or "").strip()
        line = str(r.get("line_no") or "").strip()
        code = str(r.get("customs_code") or "").strip()
        if not (decl and line and code):
            continue
        opening = _num(r.get("opening_qty"))
        rq = r.get("remaining_qty")
        remaining = _num(rq) if rq not in (None, "") else opening - _num(r.get("used_qty"))
        baseline_used = opening - remaining
        name = cell_text(r.get("goods_name"))
        alloc = resolve_allocation_code(
            {"item_code": code, "description": name, "material_identity": r.get("material_identity")},
            config,
        )
        usable = alloc.get("status") == "resolved"
        source_row = _source_row(decl, line)
        unit_value = decimal_to_text(_num(r.get("taxable_unit_price"))) if r.get("taxable_unit_price") else (
            decimal_to_text(_num(r.get("unit_price"))) if r.get("unit_price") else ""
        )
        out.append({
            "source_row": source_row,
            "source_transaction_key": str(r.get("transaction_key") or source_row),
            "source_line_ids": [source_row],
            "import_declaration_no": decl,
            "registration_date": cell_text(r.get("registration_date")),
            "line_no": line,
            "declaration_type": cell_text(r.get("declaration_type")),
            "customs_item_code": code,
            "allocation_code": alloc.get("allocation_code", ""),
            "material_code": alloc.get("allocation_code", "") if usable else "",
            "allocation_code_source": alloc.get("source", ""),
            "allocation_code_status": alloc.get("status", ""),
            "allocation_code_confidence": alloc.get("confidence", ""),
            "allocation_code_reason": alloc.get("reason", ""),
            "eligibility_status": "active",
            "eligibility_reason": "co_stock_workbook_import",
            "material_description": name,
            "hs_code": cell_text(r.get("hs_code")),
            "unit": cell_text(r.get("unit")),
            "origin_country": cell_text(r.get("origin_country")),
            "partner": cell_text(r.get("partner")),
            "invoice_no": cell_text(r.get("invoice_no")),
            "invoice_date": cell_text(r.get("invoice_date")),
            # Folded fields written directly (no runtime fold on this path).
            "bcct_qty": decimal_to_text(opening),
            "opening_qty": decimal_to_text(opening),
            "available_qty": decimal_to_text(opening),
            "baseline_used_qty": decimal_to_text(baseline_used),
            "used_qty": decimal_to_text(baseline_used),
            "remaining_qty": decimal_to_text(remaining),
            "unit_value": unit_value,
            "taxable_unit_price": decimal_to_text(_num(r.get("taxable_unit_price"))) if r.get("taxable_unit_price") else "",
            "currency": "VND",
            "value_currency": "VND",
            "exchange_rate_to_vnd": "1",
            "exchange_rate_source": "vnd_native",
            "co_stock_source": "workbook_snapshot",
        })
    return out


def import_standard_snapshot(client: dict, content: bytes, *, config: dict | None = None, filename: str = "") -> dict:
    """Ingest a STANDARD CO stock template as the client's STANDALONE snapshot.

    Sets `co_stock_rows` directly (full-mode) — remaining baked,
    allocation resolved per config, NO overlay-onto-BCCT, NO key-match. Re-import
    REPLACES the snapshot (lots with active claims stay). For onboarding clients
    running the Excel trừ-lùi in parallel — the workbook is the truth.
    """
    from app import co_stock_materializer
    from app.client_config_store import get_client_config
    from app.web.co_case_context import _CO_CASE_SOURCE_CACHE

    if config is None:
        config = get_client_config(client)
    standard_rows, parse_errors = read_standard_co_stock(content)
    stock_rows = stock_rows_from_standard(standard_rows, config)
    materialize = co_stock_materializer.refresh_co_stock_for_client(
        client, lambda: stock_rows, mode="full"
    )
    if not materialize.get("errors"):
        co_stock_materializer.record_refresh_state(
            client["id"],
            snapshot_row_count=materialize.get("rows_persisted", 0),
            bcct_row_count_at_refresh=0,
            last_bcct_server_time="",
        )
        _CO_CASE_SOURCE_CACHE.clear()
    return {
        "filename": filename,
        "parse_errors": parse_errors,
        "rows_ingested": len(stock_rows),
        "materialize": materialize,
    }
