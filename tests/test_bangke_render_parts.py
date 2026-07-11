"""Render-split fan-out machinery (VN-origin ticket #7, part B).

A material whose allocation lines resolve to distinct (origin_status,
bang_ke_origin_text) keys renders one row per group; with uniform keys (all of
today's data — the per-line fields land with the resolver/column-9 tickets)
exactly one row renders and it is the material dict itself, so rendering stays
byte-identical.
"""
from __future__ import annotations

from app.bang_ke_rows import material_render_parts


def _line(**extra):
    base = {
        "import_declaration_no": "NK-1",
        "import_line_no": "1",
        "allocated_qty": "2",
        "material_value": "20",
        "material_value_native": "20",
        "material_value_vnd": "20",
        "unit_value": "10",
        "source_row": "ROW-1",
    }
    base.update(extra)
    return base


def _material(lines, **extra):
    base = {
        "material_code": "NVL-1",
        "material_sequence": "3",
        "origin_status": "non_origin",
        "consumed_qty": "4",
        "material_value": "40",
        "allocation_lines": lines,
    }
    base.update(extra)
    return base


def test_uniform_keys_yield_identity():
    material = _material([_line(), _line(source_row="ROW-2")])
    parts = material_render_parts(material)
    assert len(parts) == 1
    assert parts[0] is material  # the exact dict — rendering byte-identical


def test_no_lines_yield_identity():
    material = _material([])
    assert material_render_parts(material) == [material]


def test_distinct_origin_status_fans_out():
    material = _material([
        _line(origin_status="origin", material_value="20", allocated_qty="2"),
        _line(source_row="ROW-2", import_declaration_no="NK-2", import_line_no="2",
              origin_status="non_origin", material_value="20", allocated_qty="2"),
    ])
    parts = material_render_parts(material)
    assert len(parts) == 2
    by_status = {part["origin_status"]: part for part in parts}
    assert by_status["origin"]["consumed_qty"] == "2"
    assert by_status["non_origin"]["consumed_qty"] == "2"
    # money: qualifying part carries no VNM; non-origin part keeps its own value
    assert by_status["origin"]["material_value"] == "20"
    assert by_status["origin"]["non_origin_cif_value"] == ""
    assert by_status["non_origin"]["non_origin_cif_value"] == "20"
    # merged-declaration behaviour WITHIN each part
    assert by_status["origin"]["import_declaration_no"] == "NK-1"
    assert by_status["non_origin"]["import_declaration_no"] == "NK-2"
    # parts sum exactly to the line totals
    assert sum(float(p["consumed_qty"]) for p in parts) == 4.0
    assert sum(float(p["material_value"]) for p in parts) == 40.0


def test_split_identity_key_shape():
    material = _material([
        _line(origin_status="origin", bang_ke_origin_text="Việt Nam"),
        _line(source_row="ROW-2", origin_status="non_origin", bang_ke_origin_text="Trung Quốc"),
    ])
    parts = material_render_parts(material)
    keys = {part["render_part_key"] for part in parts}
    assert keys == {"3:origin:Việt Nam", "3:non_origin:Trung Quốc"}
    assert all(part["render_part_count"] == 2 for part in parts)


def test_distinct_column9_text_splits_within_same_status():
    # Country mode: CHINA vs TAIWAN lots split even though both are non_origin —
    # one rule, no mode conditional.
    material = _material([
        _line(bang_ke_origin_text="Trung Quốc"),
        _line(source_row="ROW-2", bang_ke_origin_text="Đài Loan"),
    ])
    parts = material_render_parts(material)
    assert len(parts) == 2
    assert {p["bang_ke_origin_text"] for p in parts} == {"Trung Quốc", "Đài Loan"}


def test_shortfall_rides_the_default_part():
    # consumed 10, allocated 2+2 → residual 6 rides the part matching the
    # material's own (non_origin, "") key; the qualifying part stays exact.
    material = _material(
        [
            _line(origin_status="origin"),
            _line(source_row="ROW-2", origin_status="non_origin"),
        ],
        consumed_qty="10",
    )
    parts = material_render_parts(material)
    by_status = {part["origin_status"]: part for part in parts}
    assert by_status["origin"]["consumed_qty"] == "2"
    assert by_status["non_origin"]["consumed_qty"] == "8"
    assert sum(float(p["consumed_qty"]) for p in parts) == 10.0


def test_missing_line_value_makes_part_value_empty():
    material = _material([
        _line(origin_status="origin", material_value=""),
        _line(source_row="ROW-2", origin_status="non_origin"),
    ])
    parts = material_render_parts(material)
    by_status = {part["origin_status"]: part for part in parts}
    assert by_status["origin"]["material_value"] == ""
    assert by_status["non_origin"]["material_value"] == "20"


def test_part_value_is_partial_sum_like_the_material_total():
    # A part mixing valued and unvalued lines sums the PRESENT values — the same
    # partial-sum rule the material builder uses, so Σ(parts) == material total.
    material = _material([
        _line(origin_status="origin", material_value="20"),
        _line(source_row="ROW-2", origin_status="origin", material_value=""),
        _line(source_row="ROW-3", origin_status="non_origin", material_value="5"),
    ])
    parts = material_render_parts(material)
    by_status = {part["origin_status"]: part for part in parts}
    assert by_status["origin"]["material_value"] == "20"
    assert by_status["non_origin"]["material_value"] == "5"


def test_web_template_wires_render_parts():
    # Divergent per-line keys cannot be produced by a real Tính until the
    # column-9/resolver tickets land, so the web grid's split rows are covered
    # here as wiring (the Jinja global + the template block) and end-to-end by
    # the column-9 ticket's country-mode split test.
    from pathlib import Path
    from app.web.templating import templates

    assert templates.env.globals["material_render_parts"] is material_render_parts
    source = (Path("app/templates/co_case.html")).read_text()
    assert "material_render_parts(material)" in source
    assert "data-origin-split-row" in source


def test_renderer_emits_one_row_per_part():
    from openpyxl import Workbook
    from app.bang_ke_renderer import load_form_config, render_into_sheet

    cfg = load_form_config("LVC")
    wb = Workbook()
    ws = wb.active
    material = {
        "material_code": "NVL-1", "material_sequence": "1", "material_description": "Thép",
        "origin_status": "non_origin", "hs_code": "73182200", "uom": "PCE",
        "bom_qty_per": "1", "consumed_qty": "4", "unit_value": "10", "material_value": "40",
        "allocation_lines": [
            _line(origin_status="origin", bang_ke_origin_text="Việt Nam", origin_country="VIETNAM"),
            _line(source_row="ROW-2", import_declaration_no="NK-2",
                  origin_status="non_origin", bang_ke_origin_text="Trung Quốc", origin_country="CHINA"),
        ],
    }
    product = {"code": "P1", "materials": [material]}
    render_into_sheet(ws, cfg, case={"case_code": "C", "products": [product]}, product=product, sheet_title="P1")
    cols, start = cfg["body"]["columns"], cfg["body"]["start_row"]
    assert ws[f"{cols['country']}{start}"].value == "VIETNAM"
    assert ws[f"{cols['country']}{start + 1}"].value == "CHINA"
    assert ws[f"{cols['stt']}{start}"].value == 1
    assert ws[f"{cols['stt']}{start + 1}"].value == 2
    # the two part rows carry the split money: origin part → origin column,
    # non-origin part → non-origin column
    assert ws[f"{cols['origin_value']}{start}"].value == "20"
    assert ws[f"{cols['non_origin_value']}{start + 1}"].value == "20"
