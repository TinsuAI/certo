"""API: /v1/hub/materials surfaces observed_roles + atomic signals + multi-role
+ btp_sourcing + declared_observed_conflict.

Brief: .ai/features/2026-05-07-catalog-roles-refactor/brief.md (rev 5)
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


@pytest.fixture(autouse=True)
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def cid_with_rework():
    cid = "matrole-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "materials API roles test"),
        )
        # Rework code: declared btp_sx, exported, has own BOM, consumed in PARENT.
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category, btp_sourcing) values "
            "(%s, 'REWORK', 'REWORK', 'Rework code', 'btp_sx', 'self_produced_only')",
            (cid,),
        )
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, 'PARENT', 'PARENT', 'Parent', 'tp')",
            (cid,),
        )
        for art_id, prod in [
            (f"ba_{cid}_rw", "REWORK"),
            (f"ba_{cid}_par", "PARENT"),
        ]:
            cur.execute(
                "insert into hub.bom_artifacts (artifact_id, client_id, "
                "product_code, artifact_no, actor, intent, normalized_hash, "
                "source_bom_kind, flatten_status, flatten_strategy, "
                "source_channel, flatten_method, flatten_method_version, "
                "status, published_at) "
                "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', "
                "%s, 'technical_flattened', 'flattened', 'technical_exploded', "
                "'agency_upload', 'manual', '0.1', 'published', now())",
                (art_id, cid, prod, f"hash_{art_id}"),
            )
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom, level) "
            "values (%s, 1, 'PARENT', 'PARENT', 'REWORK', 1.0, 'PCS', 1)",
            (f"ba_{cid}_par",),
        )
        cur.execute(
            "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
            "declaration_no, declaration_type, direction, registration_date, "
            "customs_code, internal_code, goods_name, payload) "
            "values (%s, 'TXR', '1', 'DECLR', 'E42', 'export', '2026-01-15', "
            "'REWORK', 'REWORK', 'r test', '{}'::jsonb)",
            (cid,),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute("delete from hub.bcct_row_history where client_id=%s", (cid,))
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (cid,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.materials where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _client():
    return TestClient(app)


def test_materials_list_includes_role_fields(cid_with_rework):
    r = _client().get(
        "/v1/hub/materials",
        params={"client_id": cid_with_rework},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    by_code = {it["customs_code"]: it for it in items}
    rew = by_code["REWORK"]

    # Atomic signals
    assert rew["has_imports"] is False
    assert rew["has_exports"] is True
    assert rew["is_consumed_in_bom"] is True
    assert rew["has_own_bom"] is True
    # Derived
    assert sorted(rew["observed_roles"]) == ["btp_sx", "tp"]
    assert rew["is_multi_role"] is True
    assert rew["btp_sourcing"] == "self_produced_only"
    assert rew["declared_observed_conflict"] is False


def test_materials_list_pure_nvl_atomic_signals(cid_with_rework):
    """Add a pure NVL to the same client, verify its signals."""
    cid = cid_with_rework
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, 'NVL_X', 'NVL_X', 'NVL_X', 'nvl')",
            (cid,),
        )
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom, level) "
            "values (%s, 2, 'PARENT', 'PARENT', 'NVL_X', 1.0, 'KG', 1)",
            (f"ba_{cid}_par",),
        )
        cur.execute(
            "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
            "declaration_no, declaration_type, direction, registration_date, "
            "customs_code, internal_code, goods_name, payload) "
            "values (%s, 'TXNVL', '1', 'DECLNVL', 'E11', 'import', '2026-01-10', "
            "'NVL_X', 'NVL_X', 'nvl import', '{}'::jsonb)",
            (cid,),
        )
    r = _client().get("/v1/hub/materials", params={"client_id": cid})
    items = r.json()["items"]
    nvl = next(it for it in items if it["customs_code"] == "NVL_X")

    assert nvl["has_imports"] is True
    assert nvl["is_consumed_in_bom"] is True
    assert nvl["has_own_bom"] is False
    assert nvl["observed_roles"] == ["nvl"]
    assert nvl["is_multi_role"] is False
    assert nvl["btp_sourcing"] is None
    assert nvl["declared_observed_conflict"] is False


def test_materials_get_single_includes_role_fields(cid_with_rework):
    r = _client().get(
        f"/v1/hub/materials/REWORK",
        params={"client_id": cid_with_rework},
    )
    assert r.status_code == 200, r.text
    rew = r.json()
    assert sorted(rew["observed_roles"]) == ["btp_sx", "tp"]
    assert rew["is_multi_role"] is True
    assert rew["has_own_bom"] is True


def test_materials_unrelated_client_does_not_see_signals(cid_with_rework):
    """Cross-client isolation."""
    other = "matother-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (other, "other"),
        )
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, 'REWORK', 'REWORK', 'Rework', 'btp_sx')",
            (other,),
        )
    try:
        r = _client().get("/v1/hub/materials", params={"client_id": other})
        items = r.json()["items"]
        rew = next(it for it in items if it["customs_code"] == "REWORK")
        # Same code name as cid_with_rework's, but no observation in `other`.
        assert rew["observed_roles"] == []
        assert rew["is_multi_role"] is False
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.materials where client_id=%s", (other,))
            cur.execute("delete from hub.clients where client_id=%s", (other,))
