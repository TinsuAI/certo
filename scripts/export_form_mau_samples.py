"""Generate sample HQ bảng kê outputs — one per criterion (LVC/RVC/CTH/PSR).

Writes the resulting .xlsx files under .ai/samples/bang-ke/ so the user can
visually inspect that each criterion uses the matching form template.
"""
from __future__ import annotations

from pathlib import Path

from app.workbook_io import create_hq_bang_ke_workbook

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".ai" / "samples" / "bang-ke"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def make_materials() -> list[dict]:
    return [
        {
            "material_code": "M-001",
            "material_description": "Ống thép cán nóng hàn không hợp kim, đường kính 50mm",
            "hs_code": "73063091",
            "uom": "CAY",
            "bom_qty_per": "2",
            "consumed_qty": "2",
            "unit_value": "18.405315",
            "material_value": "36.810630",
            "origin_status": "origin",
            "origin_country": "VIETNAM",
            "import_declaration_no": "107941819640",
            "import_declaration_date": "29/01/2026",
            "source_document_ref": "",
            "source_document_date": "",
            "import_line_no": "1",
            "import_declaration_type": "E15",
        },
        {
            "material_code": "M-002",
            "material_description": "Bạc lót trục, chất liệu bằng thép, đường kính 12mm",
            "hs_code": "73269099",
            "uom": "PIECES",
            "bom_qty_per": "2",
            "consumed_qty": "2",
            "unit_value": "2.71",
            "material_value": "5.42",
            "origin_status": "non_origin",
            "origin_country": "CHINA",
            "import_declaration_no": "108054120050",
            "import_declaration_date": "16/03/2026",
            "source_document_ref": "CO-2026-44",
            "source_document_date": "20/03/2026",
            "import_line_no": "18",
            "import_declaration_type": "E11",
        },
        {
            "material_code": "M-003",
            "material_description": "Dây hàn ER70S-6, đường kính 1.2mm",
            "hs_code": "83113091",
            "uom": "KILO-GRAMMES",
            "bom_qty_per": "0.005",
            "consumed_qty": "0.005",
            "unit_value": "795",
            "material_value": "3.975",
            "origin_status": "non_origin",
            "origin_country": "CHINA",
            "import_declaration_no": "107356770730",
            "import_declaration_date": "16/07/2025",
            "source_document_ref": "",
            "source_document_date": "",
            "import_line_no": "2",
            "import_declaration_type": "E11",
        },
    ]


def make_case(case_code: str, criterion: str, product_code: str, product_name: str) -> dict:
    return {
        "case_code": case_code,
        "title": f"Mẫu bảng kê {criterion}",
        "customer": "CÔNG TY TNHH SAMPLE EXPORT",
        "customer_tax_code": "0123456789",
        "client_id": "sample",
        "destination_market": "Nhật Bản",
        "shipment": {
            "invoice_no": f"INV-{case_code}",
            "export_declaration_nos": ["308450272340"],
        },
        "products": [
            {
                "code": product_code,
                "name": product_name,
                "finished_hs": "95069100",
                "quantity": "10",
                "unit": "SETS",
                "uom": "SETS",
                "fob": "5000",
                "currency": "USD",
                "incoterm": "FOB",
                "documented_result": criterion,
                "origin_sheet_effective_criteria_text": criterion,
                "origin_sheet_effective_form_code": "AANZFTA",
                "origin_sheet_effective_lvc_threshold": "30" if "LVC" in criterion else ("40" if "RVC" in criterion else ""),
                "source_declaration_no": "308450272340",
                "source_declaration_date": "20/04/2026",
                "source_line_no": "1",
                "materials": make_materials(),
            }
        ],
    }


SAMPLES = [
    ("SAMPLE-LVC", "LVC 30%", "TP-LVC-01", "Hộp điều khiển điện áp cao, model APX 55042-P0-US"),
    ("SAMPLE-RVC", "RVC 35% + CTSH", "TP-RVC-01", "Thiết bị luyện tập thể chất, model MPL0109-39IN"),
    ("SAMPLE-CTH", "CTH", "TP-CTH-01", "Thiết bị luyện tập thể chất, model MPL0108-39"),
    ("SAMPLE-PSR", "PSR", "TP-PSR-01", "Ghế tập đẩy tạ dụng cụ, model MFW0588-23"),
]


def main() -> None:
    for code, criterion, prod_code, prod_name in SAMPLES:
        case = make_case(code, criterion, prod_code, prod_name)
        xlsx = create_hq_bang_ke_workbook(case)
        out = OUT_DIR / f"{code}-bang-ke.xlsx"
        out.write_bytes(xlsx)
        print(f"Wrote {out.relative_to(ROOT)}  ({len(xlsx) // 1024} KB)")


if __name__ == "__main__":
    main()
