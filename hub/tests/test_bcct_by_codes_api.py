"""Provider tests for `GET /v1/hub/clients/{c}/bcct/by-codes`.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.

Two fixture flavors:
- `seeded` (auth-disabled): exercises the codes filter, direction
  combine, pagination, material_identity attach, error cases.
- `strict_mode_on` + service token: exercises scope + client whitelist
  enforcement.
"""
from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.app import jwt_issuer, settings_store
from hub.app.database import connect
from hub.app.main import app
from hub.app.stores import service_accounts as sa_store


def _client() -> TestClient:
    return TestClient(app)


def _auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _url(client_id: str) -> str:
    return f"/v1/hub/clients/{client_id}/bcct/by-codes"


# ─── Auth-disabled fixture ───────────────────────────────────────────


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(auth_disabled):
    """Throwaway client with:
    - 3 import rows under MAT-A, MAT-B, MAT-C
    - 1 export row under MAT-A (direction combine test)
    - 1 row with mixed-case + URL-unsafe customs_code: 'a b/c' →
      uppercased index 'A B/C'.
    - resolver setup so include_material_identity has something to
      attach (PV01.x → BOM product).
    """
    cid = "bcct-by-codes-" + secrets.token_hex(4)
    rows = [
        # (decl, line, dtype, direction, regdate, customs_code, goods_name)
        ("DECL01", "1", "E11", "import", "2026-01-10", "MAT-A", "MAT-A#&desc#&VN"),
        ("DECL02", "1", "E11", "import", "2026-01-11", "MAT-B", "MAT-B#&desc#&VN"),
        ("DECL03", "1", "E11", "import", "2026-01-12", "MAT-C", "MAT-C#&desc#&VN"),
        ("DECL04", "1", "E42", "export", "2026-01-13", "MAT-A", "MAT-A#&export#&VN"),
        # Mixed-case + URL-unsafe customs_code. Stored upper for query.
        ("DECL05", "1", "E11", "import", "2026-01-14", "A B/C", "A B/C#&desc#&VN"),
        # Row that should resolve via material_identity (PV01.x).
        ("DECL06", "1", "E11", "import", "2026-01-15", "PV01.0117500",
         "PV01.0117500#&Plain#&VN"),
    ]
    from hub.app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, %s, 'simple_mapping', 'auto')",
            (cid, "BCCT by-codes test"),
        )
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, category) "
            "values (%s, 'PV01.0117500', 'Resolved TP', 'tp') "
            "on conflict do nothing",
            (cid,),
        )
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, actor, intent, normalized_hash, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, flatten_method, flatten_method_version, "
            "status, published_at) "
            "values (%s, %s, 'PV01.0117500', 1, 'agency_staff', "
            "'asserted_technical', 'h_by_codes', 'technical_flattened', "
            "'flattened', 'technical_exploded', 'agency_upload', "
            "'manual', '0.1', 'published', now())",
            (f"ba_{cid}_pv01", cid),
        )
        for (decl, line, dtype, direction, regdate, code, gname) in rows:
            cur.execute(
                """insert into hub.bcct_rows
                   (client_id, transaction_key, line_no, declaration_no,
                    declaration_type, direction, registration_date,
                    customs_code, goods_name, payload)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (cid, f"{decl}-{line}", line, decl, dtype, direction,
                 regdate, code, gname, "{}"),
            )
    yield {"client_id": cid}
    clear_rules_cache()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.materials where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ─── Codes filter ────────────────────────────────────────────────────


def test_single_code_filter(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"codes": "MAT-A"})
    assert r.status_code == 200
    items = r.json()["items"]
    customs_codes = {it["customs_code"] for it in items}
    assert customs_codes == {"MAT-A"}
    # 2 rows: import DECL01 + export DECL04. No direction filter applied.
    assert len(items) == 2


def test_multi_code_filter(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "MAT-A,MAT-B"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    customs_codes = {it["customs_code"] for it in items}
    assert customs_codes == {"MAT-A", "MAT-B"}
    # MAT-A → 2 rows (import + export), MAT-B → 1 row.
    assert len(items) == 3


def test_direction_combines_with_codes(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "MAT-A", "direction": "import"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["declaration_no"] == "DECL01"
    assert items[0]["direction"] == "import"


def test_unknown_codes_returns_200_empty(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "NOPE-1,NOPE-2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_mixed_case_codes_match(seeded):
    # Stored 'A B/C', queried lowercase 'a b/c' → matched.
    r = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "a b/c"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["customs_code"] == "A B/C"


def test_url_decoded_codes(seeded):
    # FastAPI auto-decodes query string. Caller pre-encodes '/' and ' '.
    r = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "a%20b%2Fc"},
    )
    # `requests` re-encodes when given via params dict so we'd send
    # `a%2520b%252Fc` — go through the raw path instead.
    r = _client().get(
        _url(seeded["client_id"]) + "?codes=a%20b%2Fc",
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["customs_code"] == "A B/C"


# ─── Row shape ───────────────────────────────────────────────────────


def test_row_shape_mirrors_bcct_endpoint(seeded):
    """Same column set as /v1/hub/bcct so CO can reuse parsing."""
    r = _client().get(_url(seeded["client_id"]), params={"codes": "MAT-A"})
    assert r.status_code == 200
    item = r.json()["items"][0]
    expected = {
        "client_id", "year", "transaction_key", "line_no", "declaration_no",
        "declaration_type", "direction", "registration_date",
        "customs_code", "goods_name", "hs_code",
        "quantity", "unit",
        "unit_price", "unit_price_nt",
        "total_value", "total_value_nt",
        "currency_nt", "total_tax", "unloading_location",
        "origin", "invoice_ref",
        "exporter_name", "exporter_tax_code", "consignee_name", "incoterms",
        "weight", "weight_unit", "package_count", "package_unit",
        "invoice_date", "departure_date",
        "destination_code", "destination_name",
        "transport_mode", "exchange_rate",
        "artifact_id", "indexed_at",
    }
    assert expected.issubset(set(item.keys()))
    assert "material_identity" not in item


def test_include_material_identity_attaches(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "PV01.0117500", "include_material_identity": "true"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    mid = items[0]["material_identity"]
    assert mid["resolution_status"] == "resolved"
    assert mid["resolved_code"] == "PV01.0117500"


# ─── Pagination ──────────────────────────────────────────────────────


def test_cursor_pagination_round_trip(seeded):
    # MAT-A has 2 rows; limit=1 → one page, then cursor → second page.
    r1 = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "MAT-A", "limit": 1},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert len(body1["items"]) == 1
    assert body1["next_cursor"] is not None

    r2 = _client().get(
        _url(seeded["client_id"]),
        params={"codes": "MAT-A", "limit": 1, "cursor": body1["next_cursor"]},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2["items"]) == 1
    assert body2["next_cursor"] is None

    # Different rows across pages.
    assert (body1["items"][0]["transaction_key"]
            != body2["items"][0]["transaction_key"])


# ─── Errors ──────────────────────────────────────────────────────────


def test_empty_codes_returns_400(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"codes": ""})
    assert r.status_code == 400
    assert "missing codes" in r.json()["detail"]


def test_codes_param_omitted_returns_400(seeded):
    r = _client().get(_url(seeded["client_id"]))
    assert r.status_code == 400


def test_only_whitespace_codes_returns_400(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"codes": " , , "})
    assert r.status_code == 400


def test_too_many_codes_returns_400(seeded):
    codes = ",".join(f"C{n:03d}" for n in range(101))
    r = _client().get(_url(seeded["client_id"]), params={"codes": codes})
    assert r.status_code == 400
    assert "too many codes" in r.json()["detail"]


def test_exactly_100_codes_allowed(seeded):
    codes = ",".join(f"C{n:03d}" for n in range(100))
    r = _client().get(_url(seeded["client_id"]), params={"codes": codes})
    assert r.status_code == 200
    # All unknown → empty.
    assert r.json()["items"] == []


def test_unknown_client_returns_404(seeded):
    r = _client().get(_url("nope-nope-nope"), params={"codes": "MAT-A"})
    assert r.status_code == 404


# ─── Strict-mode auth (service token) ────────────────────────────────


@pytest.fixture
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_on(isolated_keys_dir):
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def auth_client(strict_mode_on):
    """Client + a single MAT-A import row. Lighter than `seeded`."""
    cid = "by-codes-auth-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, %s, 'simple_mapping', 'auto')",
            (cid, "auth test"),
        )
        cur.execute(
            """insert into hub.bcct_rows
               (client_id, transaction_key, line_no, declaration_no,
                declaration_type, direction, registration_date,
                customs_code, goods_name, payload)
               values (%s, 'TX-1', '1', 'DECL01', 'E11', 'import',
                       '2026-01-10', 'MAT-A', 'desc', '{}'::jsonb)
            """,
            (cid,),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.service_accounts where name like 'sa_test_%'"
        )
        cur.execute(
            "delete from hub.revoked_service_tokens where revoked_by='sa_test_runner'"
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def test_service_token_with_hub_read_scope_returns_200(auth_client):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = _client().get(
        _url(auth_client) + "?codes=MAT-A",
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["customs_code"] == "MAT-A"


def test_service_token_without_hub_read_scope_rejected(auth_client):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["bom:propose"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["bom:propose"], client_ids=None,
    )
    r = _client().get(
        _url(auth_client) + "?codes=MAT-A",
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403
    assert "hub:read" in r.json()["detail"]


def test_service_token_client_whitelist_blocks_non_listed(auth_client):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=["a-different-client"],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"],
        client_ids=["a-different-client"],
    )
    r = _client().get(
        _url(auth_client) + "?codes=MAT-A",
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403


def test_no_bearer_in_strict_mode_returns_401(auth_client):
    r = _client().get(_url(auth_client) + "?codes=MAT-A")
    assert r.status_code == 401
