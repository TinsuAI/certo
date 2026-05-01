"""Parser for Materials (Danh Mục NVL/SP/BTP) Excel uploads."""
from __future__ import annotations

from app.parsers._excel import load_xlsx, header_row, index_headers, iter_data_rows


class MaterialsParseError(RuntimeError):
    pass


CATEGORY_MAP = {
    "nvl": "nvl", "nguyen vat lieu": "nvl", "nguyên vật liệu": "nvl",
    "raw material": "nvl", "raw": "nvl",
    "tp": "tp", "thanh pham": "tp", "thành phẩm": "tp", "finished": "tp",
    "btp_sx": "btp_sx", "btp sx": "btp_sx", "ban thanh pham sx": "btp_sx",
    "btp self": "btp_sx", "self produced": "btp_sx",
    "btp_nm": "btp_nm", "btp nm": "btp_nm", "btp nhap mua": "btp_nm",
    "purchased btp": "btp_nm",
    "ccdc": "ccdc", "cong cu dung cu": "ccdc", "công cụ dụng cụ": "ccdc",
    "tool": "ccdc",
}

ALIASES = {
    "customs_code": ["mã hq", "mã hải quan", "ma hq", "ma hai quan",
                     "customs code", "customs_code",
                     "mã"],   # fallback: bare 'Mã' in single-id Danh Mục files
    "product_code": ["mã nội bộ", "ma noi bo", "mã nb", "internal code",
                     "product code", "product_code"],
    "name": ["tên", "ten", "name", "tên hàng", "ten hang", "description"],
    "category": ["loại", "loai", "category", "type", "phân loại", "phan loai"],
    "unit": ["đvt", "dvt", "unit", "đơn vị tính"],
    "hs_code": ["hs", "hs code", "mã hs", "ma hs", "hs_code"],
    "status": ["trạng thái", "trang thai", "status"],
}


def normalize_category(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).strip().lower()
    if s in CATEGORY_MAP:
        return CATEGORY_MAP[s]
    for k, v in CATEGORY_MAP.items():
        if k in s or s in k:
            return v
    return None


# DB CHECK constraint allows only ('active', 'discontinued'). Source files
# carry agency-side lifecycle labels — normalize known VI/EN forms.
STATUS_MAP = {
    "active": "active", "đang dùng": "active", "dang dung": "active",
    "đã duyệt": "active", "da duyet": "active",
    "approved": "active", "in use": "active",
    "discontinued": "discontinued", "ngừng": "discontinued", "ngung": "discontinued",
    "không dùng": "discontinued", "khong dung": "discontinued",
    "chờ duyệt": "discontinued", "cho duyet": "discontinued",
    "pending": "discontinued", "inactive": "discontinued",
}


def normalize_status(value: str | None) -> str:
    if not value:
        return "active"
    s = str(value).strip().lower()
    return STATUS_MAP.get(s, "active")


def parse_materials_workbook(blob: bytes, *, default_category: str = "nvl") -> list[dict]:
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise MaterialsParseError(f"Cannot open workbook: {e}") from e
    rows: list[dict] = []
    for ws in wb.worksheets:
        sheet_default = _category_from_sheet_name(ws.title) or default_category
        hdr = header_row(ws, aliases=ALIASES)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = index_headers(headers, ALIASES)
        # Need at least one identifier column. DS NVL files have Mã HQ;
        # DS SP/TP files often have only product_code (Mã NB / product_code)
        # because the agency assigns HQ codes later during declaration.
        if "customs_code" not in cols and "product_code" not in cols:
            continue
        for row in iter_data_rows(ws, header_idx):
            cc = _cell_str(row, cols.get("customs_code"))
            pc = _cell_str(row, cols.get("product_code"))
            # If only product_code exists, use it as the canonical id (it
            # becomes both customs_code and product_code in the row dict).
            if not cc and pc:
                cc = pc
            if not cc:
                continue
            category_raw = _cell_str(row, cols.get("category"))
            category = normalize_category(category_raw) or sheet_default
            rows.append({
                "customs_code": cc,
                "product_code": pc,
                "name": _cell_str(row, cols.get("name")),
                "category": category,
                "unit": _cell_str(row, cols.get("unit")),
                "hs_code": _cell_str(row, cols.get("hs_code")),
                "status": normalize_status(_cell_str(row, cols.get("status"))),
            })
    if not rows:
        raise MaterialsParseError(
            "No material rows recognized; need at least one identifier column "
            "(Mã HQ / Mã NB / Mã / product_code).")
    return rows


def _category_from_sheet_name(name: str) -> str | None:
    n = name.lower()
    if "nvl" in n or "raw" in n:
        return "nvl"
    if "btp_sx" in n or "btp sx" in n:
        return "btp_sx"
    if "btp_nm" in n or "btp nm" in n:
        return "btp_nm"
    if "tp" in n or "thanh" in n or "finished" in n:
        return "tp"
    if "ccdc" in n or "tool" in n:
        return "ccdc"
    return None


def _cell_str(row, idx) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    s = str(v).strip()
    return s or None
