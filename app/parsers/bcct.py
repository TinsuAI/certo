"""Parser for BCCT (customs declaration registry) Excel uploads."""
from __future__ import annotations

from datetime import date, datetime
import secrets

from app.parsers._excel import load_xlsx, header_row, index_headers, iter_data_rows


class BcctParseError(RuntimeError):
    pass


ALIASES = {
    "declaration_no": ["số tờ khai", "so to khai", "declaration no", "declaration_no"],
    "line_no": ["dòng", "line", "stt"],
    "declaration_type": ["mã loại hình", "ma loai hinh", "loại hình"],
    "direction": ["hướng", "huong", "direction", "nhập/xuất", "nhap xuat"],
    "registration_date": ["ngày đăng ký", "ngay dang ky", "registration date", "ngày tk"],
    "customs_code": ["mã npl/sp", "ma npl sp", "mã hq", "ma hq",
                     "mã hải quan", "customs code", "mã hàng hq"],
    "goods_name": ["tên hàng", "ten hang", "goods name", "description", "mô tả"],
    "hs_code": ["hs", "mã hs", "ma hs", "hs code"],
    "quantity": ["tổng số lượng", "số lượng", "quantity", "qty"],
    "unit": ["đvt", "dvt", "unit"],
    "quantity_2": ["lượng 2", "qty 2", "số lượng 2"],
    "unit_2": ["đvt 2", "unit 2"],
    "unit_price": ["đơn giá", "don gia", "unit price"],
    "total_value": ["trị giá", "tri gia", "total value", "value"],
    "currency": ["nguyên tệ", "currency", "tt"],
    "origin": ["xuất xứ", "xuat xu", "origin"],
    "invoice_ref": ["số hóa đơn", "so hoa don", "invoice"],
}

IMPORT_TYPES = {"E11", "E15", "E13"}
EXPORT_TYPES = {"E42", "E62", "E52"}


def parse_bcct_workbook(blob: bytes) -> list[dict]:
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BcctParseError(f"Cannot open workbook: {e}") from e
    rows: list[dict] = []
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = index_headers(headers, ALIASES)
        if "customs_code" not in cols and "declaration_no" not in cols:
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
            })
    if not rows:
        raise BcctParseError("No BCCT rows recognized; check headers (Số tờ khai / Mã NPL+SP).")
    return rows


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
