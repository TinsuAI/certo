"""scripts/backfill_johnson_material_group — backfills material_group, excludes
non-declarable rows, idempotent, client-scoped (migration 078). Also pins the
get_rows_for_artifacts exclusion filter.
"""
from __future__ import annotations

import secrets

import openpyxl
import pytest

from app.database import connect
from app.stores.bom import create_artifact, get_rows_for_artifacts
from scripts.backfill_johnson_material_group import parse_code_info, run

_HEADER = ["Phantom item", "Level", "Component number",
           "Object description", "Material Group"]


@pytest.fixture
def cid():
    client_id = "bmg-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (client_id, "backfill mg test"),
        )
        cur.execute(
            "insert into hub.client_material_group_map "
            "(client_id, material_group, item_category, is_declarable) values "
            "(%s,'RD21','metal',true), (%s,'RD07','drawing',false)",
            (client_id, client_id),
        )
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (client_id,))
        cur.execute("delete from hub.bom_audit_events where client_id=%s", (client_id,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (client_id,))
        cur.execute("delete from hub.materials where client_id=%s", (client_id,))
        cur.execute("delete from hub.client_material_group_map where client_id=%s",
                    (client_id,))
        cur.execute("delete from hub.clients where client_id=%s", (client_id,))


def _write_source(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_HEADER)
    ws.append(["",  1, "STEEL-1", "Round Steel", "RD21"])
    ws.append(["X", 1, "REND-1",  "Rendering",   "RD07"])
    f = tmp_path / "PROD-A.XLSX"
    wb.save(f)
    return str(tmp_path)


def _seed_artifact(cid):
    with connect() as conn, conn.cursor() as cur:
        for code in ("STEEL-1", "REND-1"):
            cur.execute(
                "insert into hub.materials (client_id, material_code, name, "
                "category) values (%s,%s,%s,'nvl')", (cid, code, code))
        aid = create_artifact(
            client_id=cid, product_code="PROD-A",
            rows=[{"material_code": "STEEL-1", "qty_per_unit": 1, "uom": "EA"},
                  {"material_code": "REND-1", "qty_per_unit": 1, "uom": "EA"}],
            actor="agency_staff", intent="asserted_technical",
            parent_artifact_id=None,
            context={}, source_upload_id=None, cursor=cur,
        )
    return aid


def test_parse_code_info(tmp_path):
    src = _write_source(tmp_path)
    info = parse_code_info(src)
    assert info["STEEL-1"] == {"material_group": "RD21", "phantom": False}
    assert info["REND-1"] == {"material_group": "RD07", "phantom": True}


def test_backfill_excludes_and_is_idempotent(cid, tmp_path):
    src = _write_source(tmp_path)
    aid = _seed_artifact(cid)

    run(client=cid, source_dir=src, apply=True)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select material_code, material_group from hub.materials "
                    "where client_id=%s order by material_code", (cid,))
        assert dict(cur.fetchall()) == {"STEEL-1": "RD21", "REND-1": "RD07"}
        cur.execute("select material_code, excluded_at, exclusion_reason, "
                    "payload->>'material_group' from hub.bom_artifact_rows "
                    "where artifact_id=%s order by material_code", (aid,))
        by = {r[0]: r[1:] for r in cur.fetchall()}
        # REND-1 (RD07, drawing, not declarable) excluded; STEEL-1 kept.
        assert by["REND-1"][0] is not None
        assert by["REND-1"][1] in ("rac:drawing", "rac:phantom")
        assert by["STEEL-1"][0] is None
        # payload carries material_group on both.
        assert by["STEEL-1"][2] == "RD21"
        rend_excluded_at = by["REND-1"][0]

    # Re-run: no row re-excluded (excluded_at unchanged → idempotent).
    run(client=cid, source_dir=src, apply=True)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select excluded_at from hub.bom_artifact_rows "
                    "where artifact_id=%s and material_code='REND-1'", (aid,))
        assert cur.fetchone()[0] == rend_excluded_at
        # Exactly one audit event (not duplicated on re-run).
        cur.execute("select count(*) from hub.bom_audit_events "
                    "where artifact_id=%s and event_type='rows.excluded'", (aid,))
        assert cur.fetchone()[0] == 1


def _seed_artifact_with_mg(cid):
    """Seed as if a prior FULL backfill ran: materials.material_group set
    (so v_material_classification can classify) + a non-phantom artifact."""
    with connect() as conn, conn.cursor() as cur:
        for code, mg in (("STEEL-1", "RD21"), ("DRAW-1", "RD07")):
            cur.execute(
                "insert into hub.materials (client_id, material_code, name, "
                "category, material_group) values (%s,%s,%s,'nvl',%s)",
                (cid, code, code, mg))
        aid = create_artifact(
            client_id=cid, product_code="PROD-A",
            rows=[{"material_code": "STEEL-1", "qty_per_unit": 1, "uom": "EA"},
                  {"material_code": "DRAW-1", "qty_per_unit": 1, "uom": "EA"}],
            actor="agency_staff", intent="asserted_technical",
            parent_artifact_id=None,
            context={}, source_upload_id=None, cursor=cur,
        )
    return aid


def _excluded_codes(aid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select material_code from hub.bom_artifact_rows "
                    "where artifact_id=%s and excluded_at is not null", (aid,))
        return {r[0] for r in cur.fetchall()}


def test_exclusions_only_runs_from_view_without_source(cid):
    """--exclusions-only re-derives exclusions from v_material_classification
    (live map) with NO source-dir parse, is idempotent, and a map edit
    propagates (un-rác clears the stale exclusion via Phase D3)."""
    aid = _seed_artifact_with_mg(cid)

    # No source_dir needed: derive purely from the view.
    run(client=cid, source_dir=None, apply=True, exclusions_only=True)
    assert _excluded_codes(aid) == {"DRAW-1"}  # RD07 drawing, not declarable

    # Idempotent re-run.
    run(client=cid, source_dir=None, apply=True, exclusions_only=True)
    assert _excluded_codes(aid) == {"DRAW-1"}

    # Staff edits the map: RD07 becomes declarable → re-run must un-exclude.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("update hub.client_material_group_map set is_declarable=true "
                    "where client_id=%s and material_group='RD07'", (cid,))
    run(client=cid, source_dir=None, apply=True, exclusions_only=True)
    assert _excluded_codes(aid) == set()


def test_get_rows_filter_omits_excluded(cid, tmp_path):
    src = _write_source(tmp_path)
    aid = _seed_artifact(cid)
    run(client=cid, source_dir=src, apply=True)

    all_rows = get_rows_for_artifacts([aid])
    filtered = get_rows_for_artifacts([aid], exclude_non_declarable=True)
    all_codes = {r["material_code"] for r in all_rows[aid]}
    filt_codes = {r["material_code"] for r in filtered[aid]}
    assert all_codes == {"STEEL-1", "REND-1"}
    assert filt_codes == {"STEEL-1"}
