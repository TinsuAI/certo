"""Parser for BCCT (customs declaration registry) Excel uploads."""
from __future__ import annotations

from datetime import date, datetime
import secrets

from app.parsers._excel import load_xlsx, header_row, index_headers, iter_data_rows


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
    "unit_price": ["đơn giá tính thuế", "đơn giá", "don gia", "unit price"],
    "total_value": ["tổng trị giá", "trị giá nt", "trị giá", "tri gia", "total value", "value", "customs value"],
    "currency": ["đơn vị tiền tệ", "nguyên tệ", "currency"],
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
}

IMPORT_TYPES = {"E11", "E13", "E15", "E21", "E23", "E31", "E41",
                "A11", "A12", "A41", "A42", "G11", "G12", "G13",
                "H11", "H12", "H13",   # phi mậu dịch (non-commercial) imports
                "C11", "C12"}          # tạm nhập kinh doanh (temporary commercial import)
EXPORT_TYPES = {"E42", "E52", "E54", "E62", "E82",
                "B11", "B12", "B13", "G21", "G22", "G23",
                "H21", "H22", "H23"}   # phi mậu dịch (non-commercial) exports


def parse_bcct_workbook(
    blob: bytes,
    *,
    mapping_override: dict[str, str] | None = None,
) -> list[dict]:
    """Parse a BCCT workbook.

    `mapping_override`: optional dict[header_name → logical_field] to bypass
    the rigid alias-based discovery. Used by the LLM-assisted flow once a
    user has confirmed an LLM-proposed mapping; subsequent uploads with the
    same `file_signature` re-use the stored mapping without an LLM call.
    """
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BcctParseError(f"Cannot open workbook: {e}") from e
    rows: list[dict] = []
    for ws in wb.worksheets:
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
        for raw in iter_data_rows(ws, header_idx):
            decl = _cell_str(raw, cols.get("declaration_no"))
            customs = _cell_str(raw, cols.get("customs_code"))
            if not decl and not customs:
                continue
            line_no = _cell_str(raw, cols.get("line_no")) or "0"
            transaction_key = f"{decl}-{line_no}" if decl else f"{customs}-{secrets.token_hex(4)}"
            decl_type = _cell_str(raw, cols.get("declaration_type"))
            direction = _direction_from(decl_type, _cell_str(raw, cols.get("direction")))
            # Capture ALL source columns by original header name for payload jsonb.
            # Includes both promoted (typed) columns AND any HQ-side fields we don't
            # map to typed columns (importer name, weight, taxable value, etc.).
            payload = {}
            for i, header_name in enumerate(headers):
                if not header_name or i >= len(raw):
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
                "total_value": _cell_num(raw, cols.get("total_value")),
                "currency": _cell_str(raw, cols.get("currency")),
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
                "payload": payload,
            })
    if not rows:
        raise BcctParseError("No BCCT rows recognized; check headers (Số tờ khai / Mã NPL+SP).")
    return rows


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


def _direction_from(decl_type: str | None, explicit: str | None) -> str | None:
    if explicit:
        s = explicit.strip().lower()
        if s.startswith("nh") or s.startswith("import") or s == "i":
            return "import"
        if s.startswith("xu") or s.startswith("export") or s == "e":
            return "export"
    if decl_type:
        if decl_type in IMPORT_TYPES:
            return "import"
        if decl_type in EXPORT_TYPES:
            return "export"
    return None


def _cell_str(row, idx) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    # openpyxl returns numeric cells as float, so str(308449399330.0) →
    # "308449399330.0". For text-of-number fields (declaration_no, line_no,
    # tax codes, …) drop the trailing .0 so the rendered string matches what
    # the customs system actually printed.
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _cell_num(row, idx) -> float | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cell_date(row, idx):
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
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None
