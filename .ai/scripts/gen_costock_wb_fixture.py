"""Generate a synthetic agency NK2 trừ-lùi workbook for the co-stock snapshot
e2e. Layout: 3 preamble rows + header row 4 + data from row 5. Writes to the
path given as argv[1] (a scratch /tmp path, not committed)."""
import sys
from datetime import date
from openpyxl import Workbook

# Growatt-shaped: Mã NPL/SP = dotted internal code, but the system's lot key is
# the "<PREFIX>#&..." name prefix (converter must key on that, not the column).
rows = [
    {"declaration_no": "107700688100", "registration_date": date(2025, 11, 12), "declaration_type": "E11",
     "line_no": "1", "customs_code": "008.0035900", "hs_code": "39079940",
     "goods_name": "DIOT#&Đi ốt 16A/650V, nhà sản xuất Infineon. Hàng mới 100%. (008.0035900)",
     "origin_country": "CHINA", "taxable_unit_price": 52000, "opening_qty": 500, "unit": "PIECES", "used_qty": 197.631},
    # Zero-used lot → still carries its full opening.
    {"declaration_no": "107700688100", "registration_date": date(2025, 11, 12), "declaration_type": "E11",
     "line_no": "2", "customs_code": "B700.0092002", "hs_code": "85340000",
     "goods_name": "PCBA#&Bản mạch PCBA, mạch điện tử tích hợp, 110V. Hàng mới 100%. (B700.0092002)",
     "origin_country": "CHINA", "taxable_unit_price": 31000, "opening_qty": 1000, "unit": "PIECES", "used_qty": 0},
    {"declaration_no": "107700957930", "registration_date": date(2025, 11, 5), "declaration_type": "E11",
     "line_no": "3", "customs_code": "010.0024300", "hs_code": "40069090",
     "goods_name": "BBD#&Bóng bán dẫn - tranzito, 75A/650V, nhà sản xuất ON. (010.0024300)",
     "origin_country": "THAILAND", "taxable_unit_price": 88000, "opening_qty": 200, "unit": "PIECES", "used_qty": 80},
    # Over-reconciled lot → signed remaining = -2.
    {"declaration_no": "107701234560", "registration_date": date(2025, 11, 8), "declaration_type": "E11",
     "line_no": "5", "customs_code": "015.0056500", "hs_code": "85365000",
     "goods_name": "AP#&Aptomat, bộ ngắt mạch tự động, 25A/600V, nsx Santon. (015.0056500)",
     "origin_country": "VIETNAM", "taxable_unit_price": 1200, "opening_qty": 10, "unit": "PIECES", "used_qty": 12},
    {"declaration_no": "107701234560", "registration_date": date(2025, 11, 8), "declaration_type": "E11",
     "line_no": "6", "customs_code": "012.0004500", "hs_code": "39269099",
     "goods_name": "DAYTINHIEU#&Dây tín hiệu - bộ phận điện trở, 15K-ôm/75V. (012.0004500)",
     "origin_country": "VIETNAM", "taxable_unit_price": 4500, "opening_qty": 2392, "unit": "PIECES", "used_qty": 7.524},
]

wb = Workbook()
ws = wb.active
ws.title = "NK2"
for _ in range(3):
    ws.append([None] * 22)
ws.append([
    "Số TK", "Ngày ĐK", "Mã loại hình", "STT hàng", "Mã NPL/SP", "Mã HS", "Tên hàng", "Xuất xứ",
    "Đơn giá", "Đơn giá tính thuế", "Tổng số lượng", "Đơn vị tính", "Tên đối tác", "Số hóa đơn",
    "Ngày hóa đơn", "Tỷ giá thanh toán", "Đã xuất", "Tồn", "Check", "TKX",
])
for r in rows:
    ws.append([
        r.get("declaration_no"), r.get("registration_date"), r.get("declaration_type"), r.get("line_no"),
        r.get("customs_code"), r.get("hs_code"), r.get("goods_name"), r.get("origin_country"),
        r.get("unit_price"), r.get("taxable_unit_price"), r.get("opening_qty"), r.get("unit"),
        r.get("partner"), r.get("invoice_no"), r.get("invoice_date"), r.get("exchange_rate"),
        r.get("used_qty"), None, None, r.get("transaction_key"),
    ])
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/costock-wb-e2e.xlsm"
wb.save(out)
print(f"wrote {out} ({len(rows)} NK2 lots)")
