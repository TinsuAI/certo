"""Generate sample bảng kê outputs via the XML-driven generator (approach A).

Writes to .ai/samples/bang-ke-xml/ so it's side-by-side comparable with the
template-based path in .ai/samples/bang-ke/.
"""
from __future__ import annotations

from pathlib import Path

from app.bang_ke_xml_generator import render_form

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".ai" / "samples" / "bang-ke-xml"
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
        },
    ]


def make_case(criterion: str, product_code: str, product_name: str) -> tuple[dict, dict]:
    case = {
        "case_code": f"SAMPLE-{criterion}",
        "customer": "CÔNG TY TNHH SAMPLE EXPORT",
        "customer_tax_code": "0123456789",
        "shipment": {"export_declaration_nos": ["308450272340"]},
    }
    product = {
        "code": product_code,
        "name": product_name,
        "finished_hs": "95069100",
        "quantity": "10",
        "uom": "SETS",
        "fob": "5000",
        "documented_result": criterion,
        "origin_sheet_effective_criteria_text": criterion,
        "source_declaration_no": "308450272340",
        "source_declaration_date": "20/04/2026",
        "materials": make_materials(),
        "cost_buildup": {
            "labor":    "350.00",   # II — labor wages + benefits
            "overhead": "880.00",   # III — factory rent, depreciation, utilities
            "profit":   "3680.00",  # V — profit margin
            "other":    "40.00",    # VII — freight, warehousing, etc.
        } if criterion.startswith(("LVC", "RVC")) else {},
    }
    return case, product


SAMPLES = [
    ("LVC", "TP-LVC-01", "Hộp điều khiển điện áp cao, model APX 55042-P0-US"),
    ("RVC", "TP-RVC-01", "Thiết bị luyện tập thể chất, model MPL0109-39IN"),
    ("CTH", "TP-CTH-01", "Thiết bị luyện tập thể chất, model MPL0108-39"),
    ("PSR", "TP-PSR-01", "Ghế tập đẩy tạ dụng cụ, model MFW0588-23"),
]


def main() -> None:
    for criterion, code, name in SAMPLES:
        case, product = make_case(criterion, code, name)
        xlsx = render_form(criterion, case, product)
        out = OUT_DIR / f"SAMPLE-{criterion}-bang-ke.xlsx"
        out.write_bytes(xlsx)
        print(f"Wrote {out.relative_to(ROOT)}  ({len(xlsx) // 1024} KB)")


if __name__ == "__main__":
    main()
