"""Sprint C2: JWT auth on /v1/hub/* read API.

Default mode (api_auth_strict=false): accept JWT or any-non-empty (legacy).
Strict mode: JWT only.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app import auth
from app import jwt_issuer, settings_store
from app.database import connect
from app.main import app


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_off():
    """Default state. Cleanup any flag set by other tests."""
    settings_store.set_many({"api_auth_strict": "false"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def strict_mode_on():
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


# Use list_clients endpoint as a stand-in for any /v1/hub/* route.
ENDPOINT = "/v1/hub/dncxs"


def _client():
    return TestClient(app)


def test_no_bearer_returns_401():
    r = _client().get(ENDPOINT)
    assert r.status_code == 401


def test_auth_disabled_env_skips_bearer_check(monkeypatch, strict_mode_off):
    """DATA_HUB_API_AUTH_DISABLED=1 — dev kill-switch makes bearer optional."""
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")
    r = _client().get(ENDPOINT)
    assert r.status_code == 200


def test_auth_disabled_env_ignored_when_strict(monkeypatch, strict_mode_on):
    """Strict mode wins — disabled flag is suppressed, prod stays safe."""
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")
    r = _client().get(ENDPOINT)
    assert r.status_code == 401


def test_legacy_bearer_accepted_in_default_mode(strict_mode_off):
    """Permissive default keeps existing dev callers working."""
    r = _client().get(ENDPOINT, headers={"authorization": "Bearer not-a-jwt"})
    assert r.status_code == 200


def test_legacy_bearer_rejected_in_strict_mode(strict_mode_on):
    r = _client().get(ENDPOINT, headers={"authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_valid_jwt_accepted_in_default_mode(strict_mode_off):
    out = jwt_issuer.make_token(
        user_id="u_test", email="t@e", role="admin",
        display_name="T",
    )
    r = _client().get(
        ENDPOINT, headers={"authorization": f"Bearer {out['access_token']}"},
    )
    assert r.status_code == 200


def test_valid_jwt_accepted_in_strict_mode(strict_mode_on):
    out = jwt_issuer.make_token(
        user_id="u_test", email="t@e", role="admin",
        display_name="T",
    )
    r = _client().get(
        ENDPOINT, headers={"authorization": f"Bearer {out['access_token']}"},
    )
    assert r.status_code == 200


def test_valid_jwt_filters_clients_by_acl(strict_mode_on):
    user_id = "u_read_api_acl"
    allowed_client = "read-api-allowed"
    blocked_client = "read-api-blocked"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, %s, %s, %s, 'staff')
                on conflict (user_id) do update set role = excluded.role
                """,
                (user_id, "read-api-acl@test.local", "Read API ACL", auth.hash_password("test")),
            )
            cur.execute(
                """
                insert into hub.clients (client_id, name) values (%s, %s), (%s, %s)
                on conflict (client_id) do nothing
                """,
                (allowed_client, "Allowed", blocked_client, "Blocked"),
            )
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, 'read', %s)
                on conflict (user_id, client_id) do update set scope = excluded.scope
                """,
                (user_id, allowed_client, user_id),
            )
    try:
        out = jwt_issuer.make_token(
            user_id=user_id,
            email="read-api-acl@test.local",
            role="staff",
            display_name="Read API ACL",
        )
        list_response = _client().get(
            ENDPOINT,
            headers={"authorization": f"Bearer {out['access_token']}"},
        )
        blocked_response = _client().get(
            f"/v1/hub/dncxs/{blocked_client}",
            headers={"authorization": f"Bearer {out['access_token']}"},
        )

        ids = {row.get("id") or row.get("client_id") for row in list_response.json()["items"]}
        assert allowed_client in ids
        assert blocked_client not in ids
        assert blocked_response.status_code == 403
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.user_client_access where user_id = %s", (user_id,))
                cur.execute("delete from hub.users where user_id = %s", (user_id,))
                cur.execute("delete from hub.clients where client_id in (%s, %s)", (allowed_client, blocked_client))


def test_materials_endpoint_returns_next_cursor(strict_mode_on):
    client_id = "read-api-page-materials"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'Paged Materials') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.materials (client_id, material_code, name, category, status)
                values (%s, 'M-001', 'M1', 'nvl', 'active'), (%s, 'M-002', 'M2', 'nvl', 'active')
                on conflict do nothing
                """,
                (client_id, client_id),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_page_admin",
            email="page-admin@test.local",
            role="admin",
            display_name="Page Admin",
        )["access_token"]

        first = _client().get(
            f"/v1/hub/materials?client_id={client_id}&limit=1",
            headers={"authorization": f"Bearer {token}"},
        )
        second = _client().get(
            f"/v1/hub/materials?client_id={client_id}&limit=1&cursor={first.json()['next_cursor']}",
            headers={"authorization": f"Bearer {token}"},
        )

        assert [row["material_code"] for row in first.json()["items"]] == ["M-001"]
        assert first.json()["next_cursor"] == "1"
        assert [row["material_code"] for row in second.json()["items"]] == ["M-002"]
        assert second.json()["next_cursor"] is None
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.materials where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_client_config_and_source_summary_endpoints(strict_mode_on):
    """New /client-config endpoint + slimmed /source-summary (Hướng B)."""
    client_id = "read-api-summary"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name, code_resolution_mode) values (%s, 'Summary Client', 'simple_mapping') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.materials (client_id, material_code, name, category, status)
                values (%s, 'M-SUM-1', 'Material', 'nvl', 'active'), (%s, 'P-SUM-1', 'Product', 'tp', 'active')
                on conflict do nothing
                """,
                (client_id, client_id),
            )
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no, declaration_type,
                   direction, registration_date, customs_code, goods_name, payload)
                values
                  (%s, 'SUM_IMPORT', '1', 'SI001', 'E11', 'import', '2025-01-01', 'M-SUM-1', 'Material', '{}'::jsonb),
                  (%s, 'SUM_EXPORT', '1', 'SX001', 'E42', 'export', '2025-01-02', 'P-SUM-1', 'Product', '{}'::jsonb)
                on conflict do nothing
                """,
                (client_id, client_id),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_summary_admin",
            email="summary-admin@test.local",
            role="admin",
            display_name="Summary Admin",
        )["access_token"]

        # New endpoint: master config only.
        config = _client().get(
            f"/v1/hub/dncxs/{client_id}/client-config",
            headers={"authorization": f"Bearer {token}"},
        )
        assert config.status_code == 200
        body = config.json()
        assert body["client_id"] == client_id
        assert body["preset_key"] is None  # not yet configured
        assert body["eligible_import_declaration_types"] == []
        assert body["fiscal_year_start_month"] == 1
        assert body["config_version"] == 0  # virtual default
        assert body["config_hash"]  # populated even for virtual default
        assert "co_stock" not in body
        assert "allocation_code" not in body

        # Deprecated endpoint still works during grace window + carries headers.
        legacy = _client().get(
            f"/v1/hub/dncxs/{client_id}/co-config",
            headers={"authorization": f"Bearer {token}"},
        )
        assert legacy.status_code == 200
        assert legacy.headers.get("Deprecation") == "true"
        assert "Sunset" in legacy.headers
        assert legacy.json()["allocation_code"]["data_hub_code_resolution_mode"] == "simple_mapping"

        summary = _client().get(
            f"/v1/hub/dncxs/{client_id}/source-summary",
            headers={"authorization": f"Bearer {token}"},
        )
        assert summary.status_code == 200
        sbody = summary.json()
        assert sbody["material_catalog"]["published_row_count"] == 1
        assert sbody["product_catalog"]["published_row_count"] == 1
        assert sbody["bcct"]["published_row_count"] == 2
        # CO stock counters were dropped 2026-05-02.
        assert "co_stock_row_count" not in sbody
        assert "co_stock_row_count_semantics" not in sbody
        # client_config sub-payload now matches /client-config shape.
        assert sbody["client_config"]["client_id"] == client_id
        assert sbody["client_config"]["fiscal_year_start_month"] == 1
        assert "co_stock" not in sbody["client_config"]
        # bom block (no BOM artifacts seeded here → all-zero, but the
        # exported product P-SUM-1 has no BOM → exported_without_bom == 1).
        bom = sbody["bom"]
        assert bom["exported_total"] == 1
        assert bom["exported_with_bom"] == 0
        assert bom["exported_without_bom"] == 1
        assert bom["product_count"] == 0
        assert bom["stale_count"] == 0
        assert bom["multi_version_count"] == 0
        assert bom["last_published_at"] is None
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
                cur.execute("delete from hub.materials where client_id = %s", (client_id,))
                cur.execute("delete from hub.client_config where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def _insert_bom_artifact(cur, *, client_id, artifact_id, product_code,
                          lineage_root_id, flatten_status="flattened",
                          is_stale=False, published_at="2026-01-01",
                          tombstoned=False):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, context, "
        "normalized_hash, row_count, source_bom_kind, flatten_status, "
        "flatten_strategy, source_channel, bom_variant_id, lineage, "
        "flatten_method, flatten_method_version, published_at, is_stale, "
        "stale_reasons, lineage_root_id, tombstoned_at) values "
        "(%s, %s, %s, 1, 'published', 'agency_staff', 'asserted_technical', "
        "'{}', %s, 0, 'technical_flattened', %s, 'technical_exploded', "
        "'staff_form', 'default', '{}', 'as_provided', 'v1', %s, %s, "
        "'[]'::jsonb, %s, %s)",
        (artifact_id, client_id, product_code, f"h_{artifact_id}",
         flatten_status, published_at, is_stale, lineage_root_id,
         "2026-04-01" if tombstoned else None),
    )


def test_source_summary_bom_block_aggregates(strict_mode_on):
    """`bom` block rolls up company-level BOM signals for CO."""
    client_id = "read-api-bom-summary"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'BOM Summary') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.materials (client_id, material_code, name, category, status)
                values (%s, 'P1', 'Prod 1', 'tp', 'active'),
                       (%s, 'P2', 'Prod 2', 'tp', 'active'),
                       (%s, 'P3', 'Prod 3', 'tp', 'active'),
                       (%s, 'B1', 'Btp 1', 'btp_sx', 'active')
                on conflict do nothing
                """,
                (client_id, client_id, client_id, client_id),
            )
            # P1: two alive flattened artifacts, distinct lineage roots
            #     → multi-version; latest published 2026-03-01.
            _insert_bom_artifact(cur, client_id=client_id, artifact_id="ba_p1a",
                                 product_code="P1", lineage_root_id="L1a",
                                 flatten_status="flattened", published_at="2026-01-01")
            _insert_bom_artifact(cur, client_id=client_id, artifact_id="ba_p1b",
                                 product_code="P1", lineage_root_id="L1b",
                                 flatten_status="flattened", published_at="2026-03-01")
            # P2: non_flattened + stale.
            _insert_bom_artifact(cur, client_id=client_id, artifact_id="ba_p2",
                                 product_code="P2", lineage_root_id="L2",
                                 flatten_status="non_flattened", is_stale=True,
                                 published_at="2026-02-01")
            # B1 (btp): flattened — counts in product_count, NOT tp_with_bom.
            _insert_bom_artifact(cur, client_id=client_id, artifact_id="ba_b1",
                                 product_code="B1", lineage_root_id="LB1",
                                 flatten_status="flattened", published_at="2026-01-15")
            # P3: tombstoned → excluded everywhere.
            _insert_bom_artifact(cur, client_id=client_id, artifact_id="ba_p3",
                                 product_code="P3", lineage_root_id="L3",
                                 flatten_status="flattened", tombstoned=True)
            # Exports: P1 (has BOM) + PX (no BOM) → exported_without_bom == 1.
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no, declaration_type,
                   direction, registration_date, customs_code, goods_name, payload)
                values
                  (%s, 'BS_X1', '1', 'SX1', 'E42', 'export', '2025-01-02', 'P1', 'Prod 1', '{}'::jsonb),
                  (%s, 'BS_X2', '1', 'SX2', 'E42', 'export', '2025-01-03', 'PX', 'No Bom', '{}'::jsonb)
                on conflict do nothing
                """,
                (client_id, client_id),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_bomsum", email="bomsum@test.local", role="admin",
            display_name="BOM Sum",
        )["access_token"]
        r = _client().get(
            f"/v1/hub/dncxs/{client_id}/source-summary",
            headers={"authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        bom = r.json()["bom"]
        # Headline over BCCT export codes: P1 (has BOM) + PX (no BOM).
        assert bom["exported_total"] == 2
        assert bom["exported_with_bom"] == 1      # P1
        assert bom["exported_without_bom"] == 1   # PX
        # Secondary internal-coverage metrics.
        assert bom["product_count"] == 3          # P1, P2, B1 (P3 tombstoned)
        assert bom["stale_count"] == 1            # P2
        assert bom["multi_version_count"] == 1    # P1 has 2 lineage roots
        assert bom["last_published_at"].startswith("2026-03-01")
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.bom_artifacts where client_id = %s", (client_id,))
                cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
                cur.execute("delete from hub.materials where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_bcct_endpoint_returns_next_cursor(strict_mode_on):
    client_id = "read-api-page-bcct"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'Paged BCCT') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no, declaration_type,
                   direction, registration_date, customs_code, goods_name, payload)
                values
                  (%s, 'PAGE_BCCT_1', '1', 'D001', 'E11', 'import', '2025-01-02', 'M-001', 'M1', '{}'::jsonb),
                  (%s, 'PAGE_BCCT_2', '1', 'D002', 'E11', 'import', '2025-01-01', 'M-002', 'M2', '{}'::jsonb)
                on conflict do nothing
                """,
                (client_id, client_id),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_page_admin",
            email="page-admin@test.local",
            role="admin",
            display_name="Page Admin",
        )["access_token"]

        first = _client().get(
            f"/v1/hub/bcct?client_id={client_id}&limit=1",
            headers={"authorization": f"Bearer {token}"},
        )
        second = _client().get(
            f"/v1/hub/bcct?client_id={client_id}&limit=1&cursor={first.json()['next_cursor']}",
            headers={"authorization": f"Bearer {token}"},
        )

        assert [row["transaction_key"] for row in first.json()["items"]] == ["PAGE_BCCT_1"]
        assert first.json()["next_cursor"] == "1"
        assert [row["transaction_key"] for row in second.json()["items"]] == ["PAGE_BCCT_2"]
        assert second.json()["next_cursor"] is None
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_invoice_matches_endpoint_matches_export_invoice(strict_mode_on):
    client_id = "read-api-invoice"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'Invoice Client') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no, declaration_type,
                   direction, registration_date, customs_code, goods_name,
                   quantity, unit, invoice_ref, payload)
                values
                  (%s, 'INV_EXPORT_1', '1', 'X001', 'E42', 'export', '2025-01-02', 'P-001', 'Product', 2, 'PCS', 'INV-001/2026', '{}'::jsonb),
                  (%s, 'INV_EXPORT_2', '1', 'X002', 'E42', 'export', '2025-01-03', 'P-002', 'Product 2', 1, 'PCS', 'OTHER', '{}'::jsonb)
                on conflict do nothing
                """,
                (client_id, client_id),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_invoice_admin",
            email="invoice-admin@test.local",
            role="admin",
            display_name="Invoice Admin",
        )["access_token"]

        response = _client().get(
            f"/v1/hub/bcct/invoice-matches?client_id={client_id}&invoice_no=INV-001&declaration_types=E42",
            headers={"authorization": f"Bearer {token}"},
        )
        no_match = _client().get(
            f"/v1/hub/bcct/invoice-matches?client_id={client_id}&invoice_no=INV-999&declaration_types=E42",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        # Legacy consumers depend on this subset staying stable. Newer
        # additive fields (invoice_date, market_hint, …) are tested in
        # test_invoice_market_fields.
        legacy_subset = {
            "declaration_no": "X001",
            "line_no": "1",
            "declaration_type": "E42",
            "item_code": "P-001",
            "description": "Product",
            "hs_code": None,
            "quantity": 2.0,
            "unit": "PCS",
            "invoice_ref": "INV-001/2026",
            "transaction_key": "INV_EXPORT_1",
        }
        assert legacy_subset.items() <= items[0].items()
        assert no_match.status_code == 200
        assert no_match.json()["items"] == []
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_invoice_matches_filters_invoice_before_limit(strict_mode_on):
    client_id = "read-api-invoice-limit"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'Invoice Limit Client') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no, declaration_type,
                   direction, registration_date, customs_code, goods_name,
                   quantity, unit, invoice_ref, payload)
                values
                  (%s, 'INV_OLD_TARGET', '1', 'X-OLD', 'E42', 'export', '2025-01-01', 'P-OLD', 'Old Product', 1, 'PCS', 'INV-OLD-001', '{}'::jsonb)
                on conflict do nothing
                """,
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no, declaration_type,
                   direction, registration_date, customs_code, goods_name,
                   quantity, unit, invoice_ref, payload)
                select
                  %s,
                  'INV_FILLER_' || g::text,
                  '1',
                  'X-FILLER-' || g::text,
                  'E42',
                  'export',
                  date '2026-01-01' + (g * interval '1 day'),
                  'P-FILLER',
                  'Filler Product',
                  1,
                  'PCS',
                  'OTHER-' || g::text,
                  '{}'::jsonb
                from generate_series(1, 501) as g
                on conflict do nothing
                """,
                (client_id,),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_invoice_limit_admin",
            email="invoice-limit-admin@test.local",
            role="admin",
            display_name="Invoice Limit Admin",
        )["access_token"]

        response = _client().get(
            f"/v1/hub/bcct/invoice-matches?client_id={client_id}&invoice_no=INV-OLD&declaration_types=E42",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert [row["transaction_key"] for row in response.json()["items"]] == ["INV_OLD_TARGET"]
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_bom_proposal_api_requires_edit_access(strict_mode_on):
    user_id = "u_bom_read_only"
    client_id = "read-api-bom-client"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, 'bom-read-only@test.local', 'BOM Read Only', %s, 'staff')
                on conflict (user_id) do update set role = excluded.role
                """,
                (user_id, auth.hash_password("test")),
            )
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'BOM Client') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, 'read', %s)
                on conflict (user_id, client_id) do update set scope = excluded.scope
                """,
                (user_id, client_id, user_id),
            )
    try:
        token = jwt_issuer.make_token(
            user_id=user_id,
            email="bom-read-only@test.local",
            role="staff",
            display_name="BOM Read Only",
        )["access_token"]

        response = _client().post(
            "/v1/hub/products/P-001/bom/proposals",
            headers={"authorization": f"Bearer {token}"},
            json={"client_id": client_id, "rows": [{"material_code": "M-001"}]},
        )

        assert response.status_code == 403
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.user_client_access where user_id = %s", (user_id,))
                cur.execute("delete from hub.users where user_id = %s", (user_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_bom_proposal_api_rejects_legacy_bearer_in_default_mode(strict_mode_off):
    client_id = "read-api-bom-legacy-bearer"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'Legacy Bearer BOM') on conflict (client_id) do nothing",
                (client_id,),
            )
    try:
        response = _client().post(
            "/v1/hub/products/P-001/bom/proposals",
            headers={"authorization": "Bearer not-a-jwt"},
            json={"client_id": client_id, "rows": [{"material_code": "M-001"}]},
        )

        assert response.status_code == 401
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_co_bom_proposal_requires_parent_artifact_id(strict_mode_on):
    client_id = "read-api-bom-parent-required"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, 'Parent Required BOM') on conflict (client_id) do nothing",
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.materials (client_id, material_code, name, category, status)
                values (%s, 'M-PARENT-REQ', 'Parent Material', 'nvl', 'active')
                on conflict do nothing
                """,
                (client_id,),
            )
    try:
        token = jwt_issuer.make_token(
            user_id="u_bom_parent_admin",
            email="bom-parent-admin@test.local",
            role="admin",
            display_name="BOM Parent Admin",
        )["access_token"]

        response = _client().post(
            "/v1/hub/products/P-001/bom/proposals",
            headers={"authorization": f"Bearer {token}"},
            json={
                "client_id": client_id,
                "actor": "co_system",
                "intent": "modified_for_case",
                "rows": [{"material_code": "M-PARENT-REQ", "qty_per_unit": "1"}],
            },
        )

        assert response.status_code == 400
        assert "parent_artifact_id" in response.json()["detail"]
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    delete from hub.bom_artifact_rows
                    where artifact_id in (
                        select artifact_id from hub.bom_artifacts where client_id = %s
                    )
                    """,
                    (client_id,),
                )
                cur.execute("delete from hub.bom_audit_events where client_id = %s", (client_id,))
                cur.execute("delete from hub.bom_change_requests where client_id = %s", (client_id,))
                cur.execute("delete from hub.bom_artifacts where client_id = %s", (client_id,))
                cur.execute("delete from hub.materials where client_id = %s", (client_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def test_expired_jwt_always_rejected(strict_mode_off):
    """Expired tokens always 401, even in permissive default mode.

    Construct a token with iat/exp far in the past so the 60-sec leeway
    can't save it."""
    from datetime import datetime, timezone
    # Build a token by hand with explicit iat/exp.
    kid = jwt_issuer.get_active_kid()
    priv, _ = jwt_issuer._load_or_create_keypair(kid)
    long_past = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    payload = {
        "iss": jwt_issuer.get_issuer_url(),
        "sub": "u_test", "iat": long_past, "exp": long_past + 60,
        "email": "t@e", "role": "admin", "name": "T",
    }
    expired = pyjwt.encode(payload, priv, algorithm="EdDSA",
                           headers={"kid": kid, "typ": "JWT"})
    r = _client().get(
        ENDPOINT, headers={"authorization": f"Bearer {expired}"},
    )
    assert r.status_code == 401


def test_empty_bearer_returns_401():
    r = _client().get(ENDPOINT, headers={"authorization": "Bearer "})
    assert r.status_code == 401
