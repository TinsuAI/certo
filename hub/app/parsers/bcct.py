"""Parser for BCCT (customs declaration registry) Excel uploads."""
from __future__ import annotations

from datetime import date, datetime
import secrets

from hub.app.parsers._excel import (
    cell_num,
    cell_str,
    header_row,
    index_headers,
    iter_data_rows,
    load_xlsx,
)


class BcctParseError(RuntimeError):
    pass


ALIASES = {
    "declaration_no": ["số tờ khai", "so to khai", "số tk", "so tk",
                       "declaration no", "declaration_no"],
    "line_no": ["stt hàng", "stt hang", "dòng", "line", "line no"],
    "declaration_type": ["mã loại hình", "ma loai hinh", "loại hình"],
    "direction": ["hướng", "huong", "direction", "nhập/xuất", "nhap xuat"],
    "registration_date": ["ngày đăng ký", "ngay dang ky", "ngày đk", "ngay dk",
                          "registration date", "ngày tk",
                          "declaration date", "declaration_date"],
    "customs_code": ["mã npl/sp", "ma npl sp", "mã hq", "ma hq",
                     "mã hải quan", "customs code", "mã hàng hq"],
    "goods_name": ["tên hàng", "ten hang", "goods name", "description", "mô tả"],
    "hs_code": ["mã hs", "ma hs", "hs code", "hs"],
    "quantity": ["tổng số lượng", "số lượng", "quantity", "qty"],
    "unit": ["đơn vị tính", "don vi tinh", "đvt", "dvt", "unit"],
    "quantity_2": ["tổng số lượng 2", "lượng 2", "qty 2", "số lượng 2"],
    "unit_2": ["đơn vị tính 2", "đvt 2", "unit 2"],
    # Two parallel value/price domains (mig 039 split):
    #   *_value / *_price = VND-converted (taxable, customs-filing
    #   semantic). Always VND regardless of original transaction
    #   currency.
    #   *_value_nt / *_price_nt = "nguyên tệ" — the original
    #   transaction currency amounts (FX-domain). Tagged by
    #   `currency_nt` (e.g. 'USD', 'EUR').
    "unit_price":    ["đơn giá tính thuế"],
    "unit_price_nt": ["đơn giá", "don gia", "unit price"],
    "total_value":   ["tổng trị giá", "trị giá", "tri gia",
                      "total value", "value", "customs value"],
    "total_value_nt": ["trị giá nt", "trị giá nguyên tệ"],
    "currency_nt":   ["đơn vị tiền tệ", "nguyên tệ", "currency"],
    "total_tax":     ["tổng tiền thuế", "tien thue", "total tax"],
    "unloading_location": ["địa điểm dỡ hàng", "dia diem do hang",
                            "unloading location"],
    "origin": ["xuất xứ", "xuat xu", "origin"],
    "invoice_ref": ["số hóa đơn", "so hoa don", "invoice", "invoice ref"],
    # ── 12 CO-essential columns (promoted from payload 2026-05-04) ──
    "exporter_name": ["tên doanh nghiệp", "ten doanh nghiep",
                      "exporter name", "exporter"],
    "exporter_tax_code": ["mã doanh nghiệp", "ma doanh nghiep",
                          "tax code", "exporter tax"],
    "consignee_name": ["tên đối tác", "ten doi tac", "consignee", "buyer"],
    "incoterms": ["điều kiện giá hóa đơn", "dieu kien gia hoa don",
                  "incoterm", "incoterms"],
    "weight": ["trọng lượng", "trong luong", "weight", "gross weight"],
    "weight_unit": ["mã đvt trọng lượng", "ma dvt trong luong", "weight unit"],
    "package_count": ["số lượng kiện", "so luong kien", "package count",
                      "package qty"],
    "package_unit": ["mã đvt kiện", "ma dvt kien", "package unit"],
    "invoice_date": ["ngày hóa đơn", "ngay hoa don", "invoice date"],
    "departure_date": ["ngày khởi hành vận chuyển", "ngay khoi hanh",
                       "departure date", "shipping date"],
    "destination_code": ["mã địa điểm đích", "ma dia diem dich",
                         "destination code"],
    "destination_name": ["tên địa điểm đích cho vận chuyển bảo thuế",
                         "tên địa điểm đích", "ten dia diem dich",
                         "destination", "destination name"],
    "transport_mode": ["mã hiệu ptvc", "ma hieu ptvc", "transport mode",
                       "mode of transport"],
    "exchange_rate": ["tỷ giá thanh toán", "ty gia thanh toan", "tỷ giá",
                      "exchange rate"],
    # ── Tier 2 promotions (mig 040, 2026-05-08) ──
    "contract_no":      ["số hợp đồng", "so hop dong", "contract no"],
    "contract_date":    ["ngày hợp đồng", "ngay hop dong", "contract date"],
    "internal_mgmt_no": ["số quản lý nội bộ", "so quan ly noi bo",
                         "internal management no"],
    "package_marks":    ["ký hiệu và số hiệu bao bì",
                         "ky hieu va so hieu bao bi",
                         "package marks"],
}

# Decision 1357/QĐ-TCHQ (2021) — Vietnam customs declaration type schedule.
# Sets reflect the *current* official catalog. Future schedule revisions
# (expected post-MVP) should migrate this to a `hub.declaration_types`
# lookup table. Listed here as Sprint D backlog item.
#
# Direction is INCLUSIVE of all codes the schedule maps to that side.
# Codes not in either set fall through to `direction=NULL`; downstream
# can flag those rows for manual review rather than silently mis-classify.
IMPORT_TYPES = {
    # E-series (sản xuất xuất khẩu / gia công)
    "E11", "E13", "E15", "E21", "E23", "E31", "E33", "E41",
    # A-series (kinh doanh tiêu dùng + chuyển mục đích)
    "A11", "A12", "A21", "A31", "A41", "A42", "A43", "A44",
    # G-series (tạm nhập)
    "G11", "G12", "G13", "G14",
    # H-series (phi mậu dịch — only H11 is import; H21 is export)
    "H11",
    # C-series (kho ngoại quan — only C11 is import; C12 is export)
    "C11",
    # D11/D13 (chuyển từ kho)
    "D11", "D13",
}
EXPORT_TYPES = {
    # E-series (xuất sản phẩm gia công / SXXK / DNCX)
    "E42", "E52", "E54", "E62", "E82",
    # B-series (xuất kinh doanh / chuyển mục đích)
    "B11", "B12", "B13",
    # G-series (tạm xuất + tái xuất)
    "G21", "G22", "G23", "G24", "G61",
    # H-series (phi mậu dịch — H21 is export)
    "H21",
    # C-series (xuất từ kho ngoại quan)
    "C12",
    # D-series (chuyển vào kho)
    "D21", "D23",
}


# Slice 4: required at form time (mapping page validates these are mapped).
# `declaration_no` + `registration_date` are the original sheet-level
# requirements; `customs_code` keeps row-level meaning. We don't require
# `direction` to be mapped — it can be inferred from declaration_type.
MIN_IDENTIFIER_FIELDS = frozenset({"declaration_no"})
REQUIRED_MAPPED_FIELDS = frozenset({"declaration_no", "registration_date", "customs_code"})

# Logical field set for the mapping-page <select>. Comprehensive: every
# typed column the parser knows about + payload-only is the implicit
# "ignore" choice.
LOGICAL_FIELDS = (
    "declaration_no", "line_no", "declaration_type", "direction",
    "registration_date", "customs_code", "goods_name", "hs_code",
    "quantity", "unit", "quantity_2", "unit_2",
    "unit_price", "unit_price_nt",
    "total_value", "total_value_nt",
    "currency_nt", "total_tax", "unloading_location",
    "origin", "invoice_ref",
    "exporter_name", "exporter_tax_code", "consignee_name", "incoterms",
    "weight", "weight_unit", "package_count", "package_unit",
    "invoice_date", "departure_date",
    "destination_code", "destination_name",
    "transport_mode", "exchange_rate",
    "contract_no", "contract_date", "internal_mgmt_no", "package_marks",
)


def parse_bcct_workbook(
    blob: bytes,
    *,
    mapping_override: dict[str, str] | None = None,
    header_row_override: int | None = None,
    positional_override: dict[int, str] | None = None,
    extra_required_fields: list[str] | None = None,
    return_skipped: bool = False,
):
    """Parse a BCCT workbook.

    `mapping_override`: optional dict[header_name → logical_field] to bypass
    the rigid alias-based discovery.
    `header_row_override`: 1-indexed row to treat as the header row
    (slice-4 flexible-flow override).
    `positional_override`: optional dict[0-based col index → logical_field]
    for files with NO header row — data starts at sheet row 1 and columns
    are mapped by position, so no data row is consumed as a header. Takes
    precedence over `mapping_override`/`header_row_override`.
    `extra_required_fields`: rows missing any of these go to skipped_rows[].
    `return_skipped`: when True, returns `(rows, skipped_rows)` tuple
    (slice-4 flexible-flow contract). Default False keeps backward-compat
    return as `list[dict]`.
    """
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BcctParseError(f"Cannot open workbook: {e}") from e
    extra_required = list(extra_required_fields or [])
    rows: list[dict] = []
    skipped: list[dict] = []
    any_sheet_had_required_cols = False

    for ws in wb.worksheets:
        if positional_override is not None:
            # No header row: data starts at sheet row 1; columns mapped by
            # 0-based position so no data row is consumed as a header.
            n_cols = (max(positional_override) + 1) if positional_override else 0
            headers = [f"Cột {i + 1}" for i in range(n_cols)]
            header_idx = 0
            cols = {field: idx for idx, field in positional_override.items()}
        else:
            if header_row_override is not None:
                header_idx, headers = _read_header_at_row(ws, header_row_override)
                if not headers:
                    continue
            else:
                hdr = header_row(ws, aliases=ALIASES, max_scan=20)
                if not hdr:
                    continue
                header_idx, headers = hdr
            if mapping_override:
                cols = _cols_from_mapping(headers, mapping_override)
            else:
                cols = index_headers(headers, ALIASES)
        # BCCT requires both declaration_no (Số tờ khai) AND a date column. BOM
        # files have neither; settlement workbooks (RVC/LVC summary sheets) may
        # cite a declaration_no but lack the date, so the AND keeps them out.
        if "declaration_no" not in cols or "registration_date" not in cols:
            continue
        any_sheet_had_required_cols = True
        for row_idx_1based, raw in _iter_data_rows_with_index(ws, header_idx):
            decl = _cell_str(raw, cols.get("declaration_no"))
            customs = _cell_str(raw, cols.get("customs_code"))
            if not decl and not customs:
                # Row-level skip — both identifier cells empty.
                skipped.append({
                    "row_index": row_idx_1based,
                    "sheet": ws.title,
                    "reason": "missing_required:declaration_no_or_customs_code",
                    "raw": _build_raw_snapshot(raw, cols, headers),
                })
                continue
            # Optional extra required-field check.
            extra_missing: list[str] = []
            for f in extra_required:
                if not _cell_str(raw, cols.get(f)):
                    extra_missing.append(f)
            if extra_missing:
                skipped.append({
                    "row_index": row_idx_1based,
                    "sheet": ws.title,
                    "reason": "missing_required:" + ",".join(extra_missing),
                    "raw": _build_raw_snapshot(raw, cols, headers),
                })
                continue
            line_no = _cell_str(raw, cols.get("line_no")) or "0"
            transaction_key = f"{decl}-{line_no}" if decl else f"{customs}-{secrets.token_hex(4)}"
            decl_type = _cell_str(raw, cols.get("declaration_type"))
            direction = _direction_from(decl_type, _cell_str(raw, cols.get("direction")))
            # Capture source columns NOT already extracted into typed fields
            # for payload jsonb. Typed-already columns are stored in their
            # respective `bcct_rows.<field>` and stripping from payload
            # avoids duplication (mig 041 pruned existing rows likewise).
            # Result: payload holds tax-detail (Thuế suất*, Tiền thuế*),
            # free-text (Ghi chú), and audit-only fields (STT).
            typed_indices = set(cols.values())
            payload = {}
            for i, header_name in enumerate(headers):
                if not header_name or i >= len(raw):
                    continue
                if i in typed_indices:
                    continue
                value = raw[i]
                if value is None:
                    continue
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                elif not isinstance(value, (str, int, float, bool)):
                    value = str(value)
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        continue
                payload[header_name] = value
            rows.append({
                "transaction_key": transaction_key,
                "line_no": line_no,
                "declaration_no": decl,
                "declaration_type": decl_type,
                "direction": direction,
                "registration_date": _cell_date(raw, cols.get("registration_date")),
                "customs_code": customs,
                "goods_name": _cell_str(raw, cols.get("goods_name")),
                "hs_code": _cell_str(raw, cols.get("hs_code")),
                "quantity": _cell_num(raw, cols.get("quantity")),
                "unit": _cell_str(raw, cols.get("unit")),
                "quantity_2": _cell_num(raw, cols.get("quantity_2")),
                "unit_2": _cell_str(raw, cols.get("unit_2")),
                "unit_price": _cell_num(raw, cols.get("unit_price")),
                "unit_price_nt": _cell_num(raw, cols.get("unit_price_nt")),
                "total_value": _cell_num(raw, cols.get("total_value")),
                "total_value_nt": _cell_num(raw, cols.get("total_value_nt")),
                "currency_nt": _cell_str(raw, cols.get("currency_nt")),
                "total_tax": _cell_num(raw, cols.get("total_tax")),
                "unloading_location": _cell_str(raw, cols.get("unloading_location")),
                "origin": _cell_str(raw, cols.get("origin")),
                "invoice_ref": _cell_str(raw, cols.get("invoice_ref")),
                # 12 CO-essential typed fields (promoted 2026-05-04).
                "exporter_name": _cell_str(raw, cols.get("exporter_name")),
                "exporter_tax_code": _cell_str(raw, cols.get("exporter_tax_code")),
                "consignee_name": _cell_str(raw, cols.get("consignee_name")),
                "incoterms": _cell_str(raw, cols.get("incoterms")),
                "weight": _cell_num(raw, cols.get("weight")),
                "weight_unit": _cell_str(raw, cols.get("weight_unit")),
                "package_count": _cell_num(raw, cols.get("package_count")),
                "package_unit": _cell_str(raw, cols.get("package_unit")),
                "invoice_date": _cell_date(raw, cols.get("invoice_date")),
                "departure_date": _cell_date(raw, cols.get("departure_date")),
                "destination_code": _cell_str(raw, cols.get("destination_code")),
                "destination_name": _cell_str(raw, cols.get("destination_name")),
                "transport_mode": _cell_str(raw, cols.get("transport_mode")),
                "exchange_rate": _cell_num(raw, cols.get("exchange_rate")),
                "contract_no": _cell_str(raw, cols.get("contract_no")),
                "contract_date": _cell_date(raw, cols.get("contract_date")),
                "internal_mgmt_no": _cell_str(raw, cols.get("internal_mgmt_no")),
                "package_marks": _cell_str(raw, cols.get("package_marks")),
                "payload": payload,
            })
    if not rows and not any_sheet_had_required_cols:
        raise BcctParseError("No BCCT rows recognized; check headers (Số tờ khai / Mã NPL+SP).")
    if not rows and not skipped and any_sheet_had_required_cols:
        # Required cols mapped but no data rows at all (truly empty file).
        raise BcctParseError("No BCCT rows recognized; check headers (Số tờ khai / Mã NPL+SP).")

    if return_skipped:
        return rows, skipped
    return rows


def _read_header_at_row(ws, row_no_1based: int) -> tuple[int, list[str]]:
    cells: list[str] = []
    for r_idx, raw in enumerate(
        ws.iter_rows(min_row=row_no_1based, max_row=row_no_1based, values_only=True),
        start=row_no_1based,
    ):
        cells = [str(c).strip() if c is not None else "" for c in raw]
        return r_idx, cells
    return row_no_1based, cells


def _iter_data_rows_with_index(ws, header_row_idx: int):
    for offset, row in enumerate(
        ws.iter_rows(min_row=header_row_idx + 1, values_only=True), start=1,
    ):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield header_row_idx + offset, row


def _build_raw_snapshot(row, cols: dict[str, int], headers: list[str]) -> dict:
    snap: dict = {}
    claimed: set[int] = set()
    for field, idx in cols.items():
        snap[field] = _cell_str(row, idx)
        claimed.add(idx)
    for i, h in enumerate(headers):
        if i in claimed or not h:
            continue
        v = _cell_str(row, i)
        if v is not None:
            snap[f"col_{i}"] = v
    return snap


def _cols_from_mapping(headers: list[str], mapping: dict[str, str]) -> dict[str, int]:
    """Translate a `{header_name: logical_field}` mapping (from cached
    LLM-proposed parser_mappings) into the `{logical_field: col_idx}` shape
    that the row loop expects. Headers that aren't in `mapping` go to the
    payload jsonb (caught later in the row loop)."""
    cols: dict[str, int] = {}
    for i, h in enumerate(headers):
        if h is None:
            continue
        field = mapping.get(h) or mapping.get(h.strip())
        if field and field not in cols:
            cols[field] = i
    return cols


_IMPORT_DIR_TOKENS = {
    "nhập", "nhap", "nhập khẩu", "nhap khau",
    "import", "imp", "i", "n",
}
_EXPORT_DIR_TOKENS = {
    "xuất", "xuat", "xuất khẩu", "xuat khau",
    "export", "exp", "e", "x",
}


def _direction_from(decl_type: str | None, explicit: str | None) -> str | None:
    """Resolve direction from an explicit `Hướng` cell (if any) plus the
    declaration_type code. Explicit cell uses an exact-match token set
    instead of `startswith` to avoid mis-classifying values like
    'Nhà cung cấp' (supplier) as 'import' — older parser had that bug.
    """
    if explicit:
        s = explicit.strip().lower()
        if s in _IMPORT_DIR_TOKENS:
            return "import"
        if s in _EXPORT_DIR_TOKENS:
            return "export"
    if decl_type:
        if decl_type in IMPORT_TYPES:
            return "import"
        if decl_type in EXPORT_TYPES:
            return "export"
    return None


# Backward-compat aliases for the test that imports the underscore-prefixed
# helpers directly. New code should `from hub.app.parsers._excel import cell_str`.
_cell_str = cell_str
_cell_num = cell_num


_DATE_FORMATS = (
    "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d.%m.%Y", "%Y/%m/%d",  # Thái Sơn TS24 + ECUS5 legacy variants
)


def _cell_date(row, idx):
    """Coerce a cell to a date. Returns None for empty/missing cells.

    Raises BcctParseError when a non-empty value can't be parsed in any
    known format — silent None here used to land rows with NULL
    `registration_date` that subsequently failed at INSERT time against
    the GENERATED `year` column with an opaque error far from the
    original cell. Loud-fail at parse time is the better diagnostic.
    """
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise BcctParseError(
        f"unrecognized date format: {s!r} "
        f"(supported: {', '.join(_DATE_FORMATS)})",
    )
