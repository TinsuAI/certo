"""sap_indented_walk emits Material Group + Phantom/Bulk flags, and they
survive the flatten engine into FlattenedRow (migration 078 / R1 ingest).

Pins the threading: adapter leaf dict -> FlattenedRow.material_group, so the
engine-flattened shapes CO consumes carry the SAP item-type provenance.
"""
from __future__ import annotations

import io

import openpyxl

from hub.app.flatten.engine import flatten
from hub.app.flatten.types import FlattenContext
from hub.app.parsers.bom_adapters.sap_indented_walk import SapIndentedWalkAdapter

_HEADER = [
    "Phantom item", "Bulk Material", "Level", "Component number",
    "Object description", "Component quantity", "Component unit",
    "Material Group",
]


def _xlsx(header, rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_emits_material_group_phantom_bulk():
    blob = _xlsx(_HEADER, [
        ["",  "",  1, "STEEL-1", "Round Steel;20#", 2.0, "EA", "RD21"],
        ["",  "X", 1, "LABEL-1", "EN LABEL",        1.0, "EA", "RD12"],
        ["X", "",  1, "REND-1",  "Rendering",       1.0, "EA", "RD07"],
    ])
    parsed = SapIndentedWalkAdapter().parse(blob, root_code="PROD-A")
    by_code = {r["material_code"]: r for r in parsed["PROD-A"]}

    assert by_code["STEEL-1"]["material_group"] == "RD21"
    assert by_code["STEEL-1"]["phantom"] is False
    assert by_code["STEEL-1"]["bulk"] is False

    assert by_code["LABEL-1"]["material_group"] == "RD12"
    assert by_code["LABEL-1"]["bulk"] is True

    assert by_code["REND-1"]["material_group"] == "RD07"
    assert by_code["REND-1"]["phantom"] is True


def test_absent_material_group_column_yields_none():
    header = [c for c in _HEADER if c != "Material Group"]
    blob = _xlsx(header, [
        ["", "", 1, "X-1", "Some part", 1.0, "EA"],
    ])
    parsed = SapIndentedWalkAdapter().parse(blob, root_code="PROD-B")
    row = parsed["PROD-B"][0]
    assert row["material_group"] is None
    assert row["phantom"] is False
    assert row["bulk"] is False


def test_material_group_survives_flatten_engine():
    """do_not_explode leaves (what the SAP walker emits) carry material_group
    through to FlattenedRow, so the line-1569 version_rows dict can land it in
    payload."""
    blob = _xlsx(_HEADER, [
        ["", "", 1, "STEEL-1", "Round Steel;20#", 2.0, "EA", "RD21"],
        ["X", "", 1, "REND-1", "Rendering",       1.0, "EA", "RD07"],
    ])
    parsed = SapIndentedWalkAdapter().parse(blob, root_code="PROD-A")
    ctx = FlattenContext(
        client_id="t", catalog=lambda c: None, bcct_import=lambda c: False,
        same_upload_btp=lambda *a: None, current_db_btp=lambda *a: None,
        uom=lambda *a: None,
    )
    result = flatten(parsed, ctx)
    rows = [r for v in result.versions for r in v.rows]
    by_code = {r.material_code: r for r in rows}
    assert by_code["STEEL-1"].material_group == "RD21"
    assert by_code["REND-1"].material_group == "RD07"
    assert by_code["REND-1"].phantom is True
