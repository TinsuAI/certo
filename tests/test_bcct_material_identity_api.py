"""Provider tests for /v1/hub/bcct + /v1/hub/bcct/invoice-matches —
additive `material_identity` field per CO API request 2026-05-07.

Brief: .ai/features/2026-05-07-bcct-product-identity/brief.md
"""
from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


@pytest.fixture(autouse=True)
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded():
    """Throwaway Growatt-shaped client with one resolved row + one
    structured-field row + one missing row."""
    cid = "pid-api-" + secrets.token_hex(4)
    invoice = "INV-PID-A"
    rows = [
        # Resolved via goods_name embedded code.
        ("DECLAA", "1", "E42", "2026-01-15",
         "BIENTAN.17",
         "BIENTAN.17#&Thiết bị (PV01.0117500)#&VN",
         invoice),
        # Resolved via structured_field (customs_code IS the BOM product).
        ("DECLBB", "1", "E42", "2026-01-16",
         "PV01.0117500",
         "PV01.0117500#&Plain description#&VN",
         invoice),
        # Missing — no embedded code, no BOM match.
        ("DECLCC", "1", "E42", "2026-01-17",
         "UNKNOWN.99",
         "UNKNOWN.99#&Plain text#&VN",
         invoice),
        # IMPORT row — should not appear in invoice-matches export query.
        ("DECLDD", "1", "E11", "2026-01-18",
         "BIENTAN.17",
         "BIENTAN.17#&Imported (PV01.0117500)#&VN",
         invoice),
    ]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, 'PID API Test', "
            "'batch_aggregate_resolution', 'auto')",
            (cid,),
        )
        # Materials catalog must contain canonical codes — resolver
        # validates against materials, not bom_artifacts directly.
        cur.execute(
            "insert into hub.materials (client_id, customs_code, "
            "internal_code, name, category) values "
            "(%s, 'PV01.0117500', 'PV01.0117500', 'Test TP', 'tp') "
            "on conflict do nothing",
            (cid,),
        )
        # Seed BOM artifact for PV01.0117500.
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, actor, intent, normalized_hash, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, flatten_method, flatten_method_version, "
            "status, published_at) "
            "values (%s, %s, 'PV01.0117500', 1, 'agency_staff', "
            "'asserted_technical', 'h_pid_api', 'technical_flattened', "
            "'flattened', 'technical_exploded', 'agency_upload', "
            "'manual', '0.1', 'published', now())",
            (f"ba_{cid}_pv01", cid),
        )
        for (decl, line, dtype, regdate, code, gname, invref) in rows:
            direction = "import" if dtype == "E11" else "export"
            cur.execute(
                """insert into hub.bcct_rows
                   (client_id, transaction_key, line_no, declaration_no,
                    declaration_type, direction, registration_date,
                    customs_code, goods_name, invoice_ref,
                    payload)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (cid, f"{decl}-{line}", line, decl, dtype, direction,
                 regdate, code, gname, invref, "{}"),
            )
            # NULL material_identity — exercises lazy-fill path on read.
    yield {"client_id": cid, "invoice_no": invoice}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id = %s", (cid,))
        cur.execute("delete from hub.bcct_row_history where client_id = %s", (cid,))
        cur.execute("delete from hub.bom_artifacts where client_id = %s", (cid,))
        cur.execute("delete from hub.materials where client_id = %s", (cid,))
        cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _client():
    return TestClient(app)


# ─── /v1/hub/bcct ────────────────────────────────────────────────────


def test_bcct_default_omits_material_identity(seeded):
    """Per D7: /bcct default include_material_identity=false."""
    r = _client().get("/v1/hub/bcct", params={"client_id": seeded["client_id"]})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    for it in items:
        assert "material_identity" not in it


def test_bcct_with_include_returns_material_identity(seeded):
    r = _client().get(
        "/v1/hub/bcct",
        params={"client_id": seeded["client_id"], "include_material_identity": "true"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    by_decl = {it["declaration_no"]: it for it in items}
    assert "material_identity" in by_decl["DECLAA"]
    pid_a = by_decl["DECLAA"]["material_identity"]
    assert pid_a["resolution_status"] == "resolved"
    assert pid_a["resolved_code"] == "PV01.0117500"
    assert pid_a["bom_product_code"] == "PV01.0117500"  # TP w/BOM
    assert pid_a["product_kind"] == "tp"
    # Stage 1 (structured_field) for DECL.B.
    pid_b = by_decl["DECLBB"]["material_identity"]
    assert pid_b["resolution_status"] == "resolved"
    assert pid_b["resolution_source"] == "structured_field"
    # DECL.C → missing.
    pid_c = by_decl["DECLCC"]["material_identity"]
    assert pid_c["resolution_status"] == "missing"
    assert pid_c["resolved_code"] is None
    assert pid_c["bom_product_code"] is None
    assert pid_c["product_kind"] is None


# ─── /v1/hub/bcct/invoice-matches ────────────────────────────────────


def test_invoice_matches_default_includes_material_identity(seeded):
    """Per D7: /invoice-matches default include_material_identity=true."""
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded["client_id"],
            "invoice_no": seeded["invoice_no"],
            "declaration_types": "E42",
        },
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, items
    for it in items:
        assert "material_identity" in it
        assert it["material_identity"]["line_key"]["client_id"] == seeded["client_id"]
    # IMPORT row (E11) excluded — only 3 export rows expected.
    decl_set = {it["declaration_no"] for it in items}
    assert "DECLDD" not in decl_set


def test_invoice_matches_explicit_false_omits(seeded):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded["client_id"],
            "invoice_no": seeded["invoice_no"],
            "declaration_types": "E42",
            "include_material_identity": "false",
        },
    )
    assert r.status_code == 200
    items = r.json()["items"]
    for it in items:
        assert "material_identity" not in it


# ─── Error contract ──────────────────────────────────────────────────


def test_invalid_candidate_limit_returns_400(seeded):
    r = _client().get(
        "/v1/hub/bcct",
        params={
            "client_id": seeded["client_id"],
            "include_material_identity": "true",
            "material_identity_candidate_limit": "999",
        },
    )
    assert r.status_code == 400
    assert "invalid_material_identity_candidate_limit" in r.json()["detail"]


def test_non_integer_candidate_limit_returns_400(seeded):
    """Per CO spec: non-integer candidate_limit returns 400, not 422."""
    r = _client().get(
        "/v1/hub/bcct",
        params={
            "client_id": seeded["client_id"],
            "include_material_identity": "true",
            "material_identity_candidate_limit": "abc",
        },
    )
    assert r.status_code == 400
    assert "invalid_material_identity_candidate_limit" in r.json()["detail"]


def test_unknown_client_returns_404_with_pid_field(seeded):
    r = _client().get(
        "/v1/hub/bcct",
        params={"client_id": "nope-nope-nope", "include_material_identity": "true"},
    )
    assert r.status_code == 404


# ─── Lazy-fill (NULL material_identity rows) ──────────────────────────


def test_lazy_fill_resolves_at_read_time(seeded):
    """All seeded rows have material_identity=NULL in DB. Read endpoint
    resolves on the fly when include_material_identity=true."""
    # Sanity: rows are NULL in DB.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bcct_rows "
            "where client_id=%s and material_identity is null",
            (seeded["client_id"],),
        )
        (n_null,) = cur.fetchone()
    assert n_null > 0

    r = _client().get(
        "/v1/hub/bcct",
        params={
            "client_id": seeded["client_id"],
            "include_material_identity": "true",
        },
    )
    items = r.json()["items"]
    # All should have a material_identity now (computed at read time).
    assert all("material_identity" in it for it in items)
    # Resolved ones have non-null bom_product_code.
    a = next(it for it in items if it["declaration_no"] == "DECLAA")
    assert a["material_identity"]["resolved_code"] == "PV01.0117500"
    assert a["material_identity"]["bom_product_code"] == "PV01.0117500"
