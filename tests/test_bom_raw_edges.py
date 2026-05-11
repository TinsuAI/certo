from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from app.parsers.bom_edges import parse_raw_edges_with_fallback
from app.stores import bom as bom_store


CLIENT = "raw_bom_test_client"


@pytest.fixture(autouse=True)
def setup_client():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, %s) on conflict (client_id) do nothing
                """,
                (CLIENT, "raw bom test"),
            )
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


@pytest.fixture
def auth_client():
    client = TestClient(app, follow_redirects=False)
    resp = client.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
    )
    assert resp.status_code in (200, 303)
    return client


def _xlsx(sheets: dict[str, list[tuple]]) -> bytes:
    wb = openpyxl.Workbook()
    default = wb.active
    wb.remove(default)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_growatt_factory_raw_parser_keeps_direct_edges():
    blob = _xlsx({
        "整机": [
            ("工厂", "成品物料", "组件物料", "单位", "标准用量"),
            ("6180", "TP-A", "BTP-B", "ST", 2),
        ],
        "B700": [
            ("工厂", "成品物料", "组件物料", "单位", "标准用量"),
            ("6180", "BTP-B", "NVL-C", "KG", 3),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="TP-A")

    assert adapter == "growatt_factory_technical"
    assert [(e["parent_code"], e["child_code"], e["qty_per_parent"]) for e in edges] == [
        ("TP-A", "BTP-B", 2.0),
        ("BTP-B", "NVL-C", 3.0),
    ]
    assert not any(e["parent_code"] == "TP-A" and e["child_code"] == "NVL-C" for e in edges)
    assert edges[1]["node_path"] == "TP-A > BTP-B > NVL-C"


def test_growatt_factory_raw_parser_computes_unit_qty_when_missing():
    blob = _xlsx({
        "B700": [
            ("工厂", "顶层物料编码", "顶层基本数量", "子项物料号", "子项数量", "子件单位", "单位用量"),
            ("6180", "BTP-B", "1,000.000", "NVL-C", "2,000.000", "PCS", None),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="BTP-B")

    assert adapter == "growatt_factory_technical"
    assert edges[0]["parent_code"] == "BTP-B"
    assert edges[0]["child_code"] == "NVL-C"
    assert edges[0]["qty_per_parent"] == 2.0


def test_growatt_factory_raw_parser_splits_disconnected_roots():
    blob = _xlsx({
        "整机": [
            ("工厂", "成品物料", "组件物料", "单位", "标准用量"),
            ("6180", "TP-A", "BTP-B", "ST", 1),
            ("6180", "TP-X", "NVL-X", "ST", 2),
        ],
        "B700": [
            ("工厂", "成品物料", "组件物料", "单位", "标准用量"),
            ("6180", "BTP-B", "NVL-C", "KG", 3),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="TP-A")

    assert adapter == "growatt_factory_technical"
    by_pair = {(e["parent_code"], e["child_code"]): e for e in edges}
    assert by_pair[("TP-A", "BTP-B")]["root_code"] == "TP-A"
    assert by_pair[("BTP-B", "NVL-C")]["root_code"] == "TP-A"
    assert by_pair[("TP-X", "NVL-X")]["root_code"] == "TP-X"


def test_johnson_sap_raw_parser_keeps_level_edges():
    blob = _xlsx({
        "Sheet1": [
            ("Level", "Component number", "Comp. Qty (CUn)", "Component unit"),
            (1, "BTP-B", 2, "EA"),
            (2, "NVL-C", 3, "KG"),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="ASM-001")

    assert adapter == "sap_indented_raw"
    assert [(e["parent_code"], e["child_code"], e["qty_per_parent"]) for e in edges] == [
        ("ASM-001", "BTP-B", 2.0),
        ("BTP-B", "NVL-C", 3.0),
    ]
    assert edges[1]["level"] == 2
    assert edges[1]["node_path"] == "ASM-001 > BTP-B > NVL-C"


def test_johnson_sap_raw_parser_extracts_object_description():
    blob = _xlsx({
        "Sheet1": [
            ("Level", "Component number", "Comp. Qty (CUn)",
             "Component unit", "Object description"),
            (1, "BTP-B", 2, "EA", "Sub-assembly bracket"),
            (2, "NVL-C", 3, "KG", "Steel plate 5mm"),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="ASM-001")

    assert adapter == "sap_indented_raw"
    desc_by_child = {e["child_code"]: e["payload"].get("description") for e in edges}
    assert desc_by_child == {
        "BTP-B": "Sub-assembly bracket",
        "NVL-C": "Steel plate 5mm",
    }


def test_johnson_sap_raw_parser_works_without_description_column():
    blob = _xlsx({
        "Sheet1": [
            ("Level", "Component number", "Comp. Qty (CUn)", "Component unit"),
            (1, "X", 1, "EA"),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="ASM-X")
    assert adapter == "sap_indented_raw"
    assert "description" not in edges[0]["payload"]


def test_sap_indented_walk_adapter_propagates_description_to_leaf():
    from app.parsers.bom_adapters.sap_indented_walk import SapIndentedWalkAdapter
    blob = _xlsx({
        "Sheet1": [
            ("Level", "Component number", "Comp. Qty (CUn)",
             "Component unit", "Object description"),
            (1, "BTP-B", 2, "EA", "Sub-assembly"),
            (2, "NVL-C", 3, "KG", "Steel plate"),
        ],
    })
    by_root = SapIndentedWalkAdapter().parse(blob, root_code="ASM-001")
    leaves = by_root["ASM-001"]
    by_code = {r["material_code"]: r.get("description") for r in leaves}
    # BTP-B is intermediate (has child NVL-C), so only NVL-C is a leaf.
    assert by_code == {"NVL-C": "Steel plate"}


def test_sap_indented_raw_parser_picks_per_parent_qty_over_cumulative():
    # SAP exports carry two qty columns: 'Component quantity' (MENGE) is
    # per-immediate-parent; 'Comp. Qty (CUn)' (MNGKO) is cumulative through
    # ancestors. qty_per_parent must reflect MENGE.
    blob = _xlsx({
        "Sheet1": [
            ("Level", "Component number",
             "Component quantity", "Comp. Qty (CUn)", "Component unit"),
            (1, "BTP-B", 2, 2, "EA"),
            # MENGE=5 per BTP-B; MNGKO=10 (2×5) cumulative from root.
            (2, "NVL-C", 5, 10, "KG"),
        ],
    })

    edges, adapter = parse_raw_edges_with_fallback(blob, root_code="ASM-001")

    assert adapter == "sap_indented_raw"
    by_child = {e["child_code"]: e for e in edges}
    assert by_child["BTP-B"]["qty_per_parent"] == 2.0
    assert by_child["NVL-C"]["qty_per_parent"] == 5.0, (
        "Parser must pick 'Component quantity' (MENGE) — got the cumulative "
        "MNGKO value, which inflates qty_per_parent and fragments BTP "
        "slices across parent-TP contexts."
    )


def test_sap_indented_walk_adapter_picks_per_parent_qty_over_cumulative():
    # Same invariant as the raw-edges parser, exercised on the legacy
    # walk adapter used by the WebUI upload route.
    from app.parsers.bom_adapters.sap_indented_walk import SapIndentedWalkAdapter
    blob = _xlsx({
        "Sheet1": [
            ("Level", "Component number",
             "Component quantity", "Comp. Qty (CUn)", "Component unit"),
            (1, "BTP-B", 2, 2, "EA"),
            (2, "NVL-C", 5, 10, "KG"),
        ],
    })
    by_root = SapIndentedWalkAdapter().parse(blob, root_code="ASM-001")
    nvl = next(r for r in by_root["ASM-001"] if r["material_code"] == "NVL-C")
    # _qty_raw is the per-immediate-parent cell value before multiplication.
    assert nvl["_qty_raw"] == "5"
    # qty_per_unit = MENGE walked through ancestors = 1 × 2 × 5 = 10.
    # Picking MNGKO double-cumulates: 1 × 2 × 10 = 20.
    assert nvl["qty_per_unit"] == 10.0


def test_create_raw_artifact_persists_edges_without_flat_rows():
    artifact_id = bom_store.create_raw_artifact(
        client_id=CLIENT,
        product_code="TP-A",
        edges=[
            {
                "root_code": "TP-A",
                "parent_code": "TP-A",
                "child_code": "BTP-B",
                "qty_per_parent": 2,
                "uom": "EA",
                "level": 1,
                "node_path": "TP-A > BTP-B",
            },
            {
                "root_code": "TP-A",
                "parent_code": "BTP-B",
                "child_code": "NVL-C",
                "qty_per_parent": 3,
                "uom": "KG",
                "level": 2,
                "node_path": "TP-A > BTP-B > NVL-C",
            },
        ],
        actor="agency_staff",
        intent="asserted_technical",
        parent_artifact_id=None,
        context={"profile": "technical_raw"},
        source_upload_id=None,
    )

    data = bom_store.get_artifact_with_rows(artifact_id)
    assert data["artifact"]["source_bom_kind"] == "technical_raw"
    assert data["artifact"]["flatten_status"] == "non_flattened"
    assert data["artifact"]["flatten_strategy"] == "no_strategy"
    assert data["rows"] == []
    assert [(e["parent_code"], e["child_code"]) for e in data["edges"]] == [
        ("TP-A", "BTP-B"),
        ("BTP-B", "NVL-C"),
    ]


def test_technical_raw_upload_confirm_materializes_edges(auth_client):
    blob = _xlsx({
        "整机": [
            ("工厂", "成品物料", "组件物料", "单位", "标准用量"),
            ("6180", "RT_TP", "RT_BTP", "ST", 1),
        ],
        "B700": [
            ("工厂", "成品物料", "组件物料", "单位", "标准用量"),
            ("6180", "RT_BTP", "RT_NVL", "KG", 4),
        ],
    })
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_raw"},
        files={"file": ("RT_TP.xlsx", blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303
    assert "/bom/preview/" in resp.headers["location"]
    pending_id = resp.headers["location"].split("/")[-1]

    resp = auth_client.post(f"/clients/{CLIENT}/bom/preview/{pending_id}/confirm")
    assert resp.status_code == 303

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select v.source_bom_kind, count(e.*), count(r.*)
                from hub.bom_artifacts v
                left join hub.bom_edges e on e.artifact_id = v.artifact_id
                left join hub.bom_artifact_rows r on r.artifact_id = v.artifact_id
                where v.client_id = %s and v.product_code = 'RT_TP'
                group by v.artifact_id, v.source_bom_kind
                """,
                (CLIENT,),
            )
            row = cur.fetchone()
    assert row == ("technical_raw", 2, 0)
