"""Provider tests for `GET /v1/hub/clients/{c}/declarations`.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`.

Surfaces declaration-level summary with `file_count` from
`hub.customs_declaration_files` so CO can answer "có tờ khai / thiếu
tờ khai" without scanning BCCT.

Two fixture flavors:
- `seeded` (auth-disabled): exercises filters + edge cases.
- `auth_client` (strict_mode_on) + service token: exercises scope +
  client-whitelist enforcement.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from hub.app import jwt_issuer, settings_store
from hub.app.database import connect
from hub.app.main import app
from hub.app.stores import service_accounts as sa_store


def _client() -> TestClient:
    return TestClient(app)


def _url(client_id: str) -> str:
    return f"/v1/hub/clients/{client_id}/declarations"


def _auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _seed_bcct(cur, *, client_id, decl_no, direction, line_no="1",
               registration_date="2026-04-21"):
    cur.execute(
        """insert into hub.bcct_rows
           (client_id, transaction_key, line_no, declaration_no,
            declaration_type, direction, registration_date,
            customs_code, goods_name, payload)
           values (%s, %s, %s, %s,
                   %s, %s, %s,
                   'MAT-X', 'desc', '{}'::jsonb)""",
        (client_id, f"TX-{decl_no}-{direction}-{line_no}", line_no,
         decl_no,
         "E11" if direction == "import" else "E42", direction,
         registration_date),
    )


def _seed_file(cur, *, client_id, decl_no, direction,
               file_kind="pdf", original_filename="tk.pdf",
               sha256=None, backend_key=None):
    sha = sha256 or secrets.token_hex(32)
    bk = backend_key or f"customs_declarations/{client_id}/{secrets.token_hex(4)}_{original_filename}"
    cur.execute(
        """insert into hub.customs_declaration_files
           (client_id, declaration_no, direction, file_kind,
            backend_key, original_filename, sha256, size_bytes)
           values (%s, %s, %s, %s, %s, %s, %s, 0)""",
        (client_id, decl_no, direction, file_kind, bk,
         original_filename, sha),
    )


# ─── Auth-disabled fixture ───────────────────────────────────────────


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(auth_disabled):
    """Throwaway client. Layout:
      Imports:
        - DEC001 (1 BCCT line, 1 file)
        - DEC002 (2 BCCT lines, 0 files — BCCT-only, no upload)
        - DEC003 (1 BCCT line, 2 files — multi-file case)
      Exports:
        - DEC003 (1 BCCT line, 1 file — same decl_no as import DEC003,
                  separate identity per (client, no, direction))
        - DEC100 (1 BCCT line, 0 files)
    """
    cid = "decl-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "Decl API test"),
        )
        # BCCT — import
        _seed_bcct(cur, client_id=cid, decl_no="DEC001",
                   direction="import", line_no="1",
                   registration_date="2026-04-19")
        _seed_bcct(cur, client_id=cid, decl_no="DEC002",
                   direction="import", line_no="1",
                   registration_date="2026-04-20")
        _seed_bcct(cur, client_id=cid, decl_no="DEC002",
                   direction="import", line_no="2",
                   registration_date="2026-04-20")
        _seed_bcct(cur, client_id=cid, decl_no="DEC003",
                   direction="import", line_no="1",
                   registration_date="2026-04-21")
        # BCCT — export
        _seed_bcct(cur, client_id=cid, decl_no="DEC003",
                   direction="export", line_no="1",
                   registration_date="2026-04-22")
        _seed_bcct(cur, client_id=cid, decl_no="DEC100",
                   direction="export", line_no="1",
                   registration_date="2026-04-23")
        # Files — DEC001 import: 1 file
        _seed_file(cur, client_id=cid, decl_no="DEC001",
                   direction="import", original_filename="dec001.pdf")
        # DEC003 import: 2 files (multi-file case)
        _seed_file(cur, client_id=cid, decl_no="DEC003",
                   direction="import", file_kind="pdf",
                   original_filename="dec003_pdf.pdf")
        _seed_file(cur, client_id=cid, decl_no="DEC003",
                   direction="import", file_kind="xls",
                   original_filename="dec003_xls.xls")
        # DEC003 export: 1 file (same decl_no as import; different identity)
        _seed_file(cur, client_id=cid, decl_no="DEC003",
                   direction="export", original_filename="dec003_export.pdf")

    yield {"client_id": cid}

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute(
            "delete from hub.bcct_rows where client_id=%s", (cid,),
        )
        cur.execute(
            "delete from hub.bcct_row_history where client_id=%s", (cid,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ─── Strict-mode + service-token fixture ──────────────────────────────


@pytest.fixture
def strict_mode_on(monkeypatch):
    monkeypatch.delenv("DATA_HUB_API_AUTH_DISABLED", raising=False)
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def auth_client(strict_mode_on):
    """Lighter client used for auth tests."""
    cid = "decl-auth-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "decl auth test"),
        )
        _seed_bcct(cur, client_id=cid, decl_no="DEC001",
                   direction="import")
        _seed_file(cur, client_id=cid, decl_no="DEC001",
                   direction="import", original_filename="x.pdf")
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.service_accounts where name like 'sa_test_%'",
        )
        cur.execute(
            "delete from hub.revoked_service_tokens "
            "where revoked_by='sa_test_runner'",
        )
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute(
            "delete from hub.bcct_rows where client_id=%s", (cid,),
        )
        cur.execute(
            "delete from hub.bcct_row_history where client_id=%s", (cid,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ─── Functional tests ────────────────────────────────────────────────


def test_default_returns_all_declarations(seeded):
    r = _client().get(_url(seeded["client_id"]))
    assert r.status_code == 200
    body = r.json()
    # 4 import declarations + 2 export = wait, import has 3 distinct:
    # DEC001, DEC002, DEC003. Export has DEC003 + DEC100. Total 5 rows.
    assert len(body["items"]) == 5
    by_key = {(i["declaration_no"], i["direction"]): i for i in body["items"]}
    assert by_key[("DEC001", "import")]["file_count"] == 1
    assert by_key[("DEC001", "import")]["bcct_line_count"] == 1
    assert by_key[("DEC002", "import")]["file_count"] == 0
    assert by_key[("DEC002", "import")]["bcct_line_count"] == 2
    assert by_key[("DEC003", "import")]["file_count"] == 2
    assert by_key[("DEC003", "export")]["file_count"] == 1
    assert by_key[("DEC100", "export")]["file_count"] == 0


def test_direction_filter(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"direction": "export"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["declaration_no"] for i in items} == {"DEC003", "DEC100"}
    assert all(i["direction"] == "export" for i in items)


def test_invalid_direction_returns_400(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"direction": "sideways"})
    assert r.status_code == 400
    assert "invalid_direction" in r.json()["detail"]


def test_has_files_yes(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"has_files": "yes"})
    assert r.status_code == 200
    items = r.json()["items"]
    # DEC001 import + DEC003 import + DEC003 export
    assert len(items) == 3
    assert all(i["file_count"] > 0 for i in items)


def test_has_files_no(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"has_files": "no"})
    assert r.status_code == 200
    items = r.json()["items"]
    # DEC002 import + DEC100 export
    assert len(items) == 2
    assert all(i["file_count"] == 0 for i in items)


def test_invalid_has_files_returns_400(seeded):
    r = _client().get(_url(seeded["client_id"]), params={"has_files": "maybe"})
    assert r.status_code == 400
    assert "invalid_has_files" in r.json()["detail"]


def test_declaration_nos_filter_exact(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"declaration_nos": "DEC001,DEC003"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    # DEC001 import + DEC003 import + DEC003 export = 3 rows
    assert len(items) == 3
    assert {(i["declaration_no"], i["direction"]) for i in items} == {
        ("DEC001", "import"),
        ("DEC003", "import"),
        ("DEC003", "export"),
    }
    # When declaration_nos passed, no cursor pagination.
    assert r.json()["next_cursor"] is None


def test_declaration_nos_with_direction(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"declaration_nos": "DEC003", "direction": "export"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["direction"] == "export"
    assert items[0]["file_count"] == 1


def test_declaration_nos_unknown_returns_empty(seeded):
    r = _client().get(
        _url(seeded["client_id"]),
        params={"declaration_nos": "NOPE-1,NOPE-2"},
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_same_declaration_no_in_both_directions(seeded):
    """DEC003 exists in both import + export with different file_count.
    Identity is (client, no, direction) — must return both rows."""
    r = _client().get(
        _url(seeded["client_id"]),
        params={"declaration_nos": "DEC003"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    by_dir = {i["direction"]: i for i in items}
    assert by_dir["import"]["file_count"] == 2
    assert by_dir["export"]["file_count"] == 1


def test_pagination_cursor(seeded):
    """Limit=2 should produce a cursor; following it returns rest."""
    r1 = _client().get(_url(seeded["client_id"]), params={"limit": 2})
    assert r1.status_code == 200
    body1 = r1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"] is not None
    r2 = _client().get(
        _url(seeded["client_id"]),
        params={"limit": 2, "cursor": body1["next_cursor"]},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    # Walk through all 5 rows in 3 pages of 2, 2, 1.
    seen = {(i["declaration_no"], i["direction"]) for i in body1["items"]}
    seen.update((i["declaration_no"], i["direction"]) for i in body2["items"])
    # Page 3 needed.
    r3 = _client().get(
        _url(seeded["client_id"]),
        params={"limit": 2, "cursor": body2["next_cursor"]},
    )
    body3 = r3.json()
    seen.update((i["declaration_no"], i["direction"]) for i in body3["items"])
    assert body3["next_cursor"] is None
    assert len(seen) == 5


# ─── Auth tests ───────────────────────────────────────────────────────


def test_no_bearer_in_strict_mode_returns_401(auth_client):
    r = _client().get(_url(auth_client))
    assert r.status_code == 401


def test_garbage_bearer_in_strict_mode_returns_401(auth_client):
    r = _client().get(
        _url(auth_client),
        headers={"authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


def test_service_token_hub_read_returns_200(auth_client):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = _client().get(_url(auth_client), headers=_auth_header(out["access_token"]))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["file_count"] == 1


def test_service_token_without_hub_read_rejected(auth_client):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["bom:propose"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["bom:propose"], client_ids=None,
    )
    r = _client().get(_url(auth_client), headers=_auth_header(out["access_token"]))
    assert r.status_code == 403
    assert "hub:read" in r.json()["detail"]


def test_service_token_client_whitelist_blocks(auth_client):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=["other-client"],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=["other-client"],
    )
    r = _client().get(_url(auth_client), headers=_auth_header(out["access_token"]))
    assert r.status_code == 403


def test_client_not_found_returns_404(auth_disabled):
    r = _client().get(_url("does-not-exist-" + secrets.token_hex(4)))
    assert r.status_code == 404
