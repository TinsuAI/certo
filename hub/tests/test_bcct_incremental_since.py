"""Provider tests for `since` + `include_tombstones` on GET /v1/hub/bcct.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`.

Covers:
- happy path: omitted, past, future timestamps
- tombstone semantics (first-page only, requires since)
- pagination with since
- error cases (invalid since, naive timezone, garbage boolean,
  tombstones without since)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


URL = "/v1/hub/bcct"


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(auth_disabled):
    """Throwaway client with 4 rows at distinct `indexed_at` values + 1
    tombstone entry in bcct_row_history."""
    cid = "bcct-since-" + secrets.token_hex(4)
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        # (transaction_key, indexed_at)
        ("DECL01-1", base + timedelta(hours=0)),
        ("DECL02-1", base + timedelta(hours=1)),
        ("DECL03-1", base + timedelta(hours=2)),
        ("DECL04-1", base + timedelta(hours=3)),
    ]
    tombstone_at = base + timedelta(hours=2, minutes=30)
    tombstoned_tx = "DECL_DELETED-1"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, %s, 'simple_mapping', 'auto')",
            (cid, "since-test"),
        )
        for tx, indexed_at in rows:
            decl, line = tx.split("-", 1)
            cur.execute(
                """insert into hub.bcct_rows
                   (client_id, transaction_key, line_no, declaration_no,
                    declaration_type, direction, registration_date,
                    customs_code, goods_name, payload, indexed_at)
                   values (%s, %s, %s, %s, 'E11', 'import', '2026-01-01',
                           'MAT', 'MAT#&desc', '{}'::jsonb, %s)
                """,
                (cid, tx, line, decl, indexed_at),
            )
        # Synthesize one delete event in the audit table. The bcct_rows
        # AFTER UPDATE/DELETE trigger (mig 013) would populate this on a
        # real delete; for a deterministic test we insert directly with
        # changed_by='operator_delete' so the response's `reason` field is
        # populated and stable.
        cur.execute(
            """insert into hub.bcct_row_history
               (client_id, year, transaction_key, line_no, action,
                old_row, changed_by, changed_at)
               values (%s, 2026, %s, '1', 'delete',
                       '{"transaction_key":"DECL_DELETED-1"}'::jsonb,
                       'operator_delete', %s)
            """,
            (cid, tombstoned_tx, tombstone_at),
        )
    yield {"client_id": cid, "base": base, "tombstone_at": tombstone_at,
           "tombstoned_tx": tombstoned_tx}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_row_history where client_id=%s", (cid,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _client() -> TestClient:
    return TestClient(app)


# ─── Happy paths ─────────────────────────────────────────────────────


def test_since_omitted_keeps_existing_shape_plus_server_time(seeded):
    """Spec back-compat: omitting `since` returns all rows; `tombstones`
    must be absent (not present-empty); `server_time` is always set."""
    r = _client().get(URL, params={"client_id": seeded["client_id"]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 4
    assert "tombstones" not in body
    assert body["server_time"]  # ISO string from JSONResponse encoder


def test_since_past_filters_to_newer_rows(seeded):
    cutoff = (seeded["base"] + timedelta(hours=1, minutes=30)).isoformat()
    r = _client().get(URL, params={
        "client_id": seeded["client_id"], "since": cutoff,
    })
    assert r.status_code == 200
    body = r.json()
    txs = {it["transaction_key"] for it in body["items"]}
    # Cutoff at +1h30 → keep DECL03 (+2h) and DECL04 (+3h).
    assert txs == {"DECL03-1", "DECL04-1"}


def test_since_future_returns_empty_with_server_time(seeded):
    far_future = (seeded["base"] + timedelta(days=365)).isoformat()
    r = _client().get(URL, params={
        "client_id": seeded["client_id"],
        "since": far_future,
        "include_tombstones": "true",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["tombstones"] == []
    assert body["server_time"]


def test_tombstones_returned_when_requested(seeded):
    cutoff = seeded["base"].isoformat()
    r = _client().get(URL, params={
        "client_id": seeded["client_id"], "since": cutoff,
        "include_tombstones": "true",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["tombstones"]) == 1
    tomb = body["tombstones"][0]
    assert tomb["transaction_key"] == seeded["tombstoned_tx"]
    assert tomb["reason"] == "operator_delete"
    assert tomb["removed_at"]  # ISO timestamp


def test_tombstones_first_page_only(seeded):
    """Per spec: tombstones is returned in full on the first page;
    subsequent pages have tombstones=[] (still present as empty array
    when include_tombstones=true was requested)."""
    cutoff = seeded["base"].isoformat()
    r = _client().get(URL, params={
        "client_id": seeded["client_id"], "since": cutoff,
        "include_tombstones": "true",
        "limit": 2, "cursor": "2",  # second page
    })
    assert r.status_code == 200
    body = r.json()
    assert body["tombstones"] == []


# ─── Error cases ─────────────────────────────────────────────────────


def test_since_invalid_string_returns_400(seeded):
    r = _client().get(URL, params={
        "client_id": seeded["client_id"], "since": "not-a-timestamp",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_since"


def test_since_timezone_naive_returns_400(seeded):
    # Strip the timezone — should be rejected per spec ("require explicit UTC").
    naive = "2026-01-01T12:00:00"
    r = _client().get(URL, params={
        "client_id": seeded["client_id"], "since": naive,
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_since"


def test_include_tombstones_without_since_returns_400(seeded):
    r = _client().get(URL, params={
        "client_id": seeded["client_id"], "include_tombstones": "true",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "include_tombstones_requires_since"


def test_include_tombstones_garbage_returns_400(seeded):
    r = _client().get(URL, params={
        "client_id": seeded["client_id"],
        "since": seeded["base"].isoformat(),
        "include_tombstones": "maybe",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_include_tombstones"
