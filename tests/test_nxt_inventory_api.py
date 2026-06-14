"""Provider tests for the paged/filtered NXT + inventory read API.

Covers the additive `…/nxt/{aid}/lines` and
`…/inventory-snapshots/{sid}/lines` sub-resources (pagination, code/role/
warehouse filters, exact `total`, `next_cursor`, error + cross-client paths)
plus the `period_year` / `year` list filters. See
`.ai/features/2026-06-14-nxt-inventory-tier/brief.md`.
"""
from __future__ import annotations

import secrets
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from app.stores import inventory_snapshots as inv_store
from app.stores import nxt as nxt_store


def _c() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(auth_disabled):
    """Throwaway client with two NXT artifacts (2025 with 5 lines, 2024 empty)
    and two inventory snapshots (2025-12-31 with 5 lines, 2024-12-31 empty)."""
    cid = "nxt-api-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "NXT API test"),
        )
    nxt_lines = [
        {"internal_code": "A001", "customs_code": "CC001", "name": "n1",
         "uom": "PCS", "reported_role": "nvl", "opening": 10,
         "inbound_total": 5, "outbound_total": 3, "closing_reported": 12},
        {"internal_code": "A002", "customs_code": "CC002", "name": "n2",
         "uom": "PCS", "reported_role": "tp", "opening": 0,
         "inbound_total": 7, "outbound_total": 2, "closing_reported": 5},
        {"internal_code": "A003", "customs_code": "CC003", "name": "n3",
         "uom": "KG", "reported_role": "btp", "opening": 1,
         "inbound_total": 0, "outbound_total": 0, "closing_reported": 1},
        {"internal_code": "A004", "customs_code": "CC004", "name": "n4",
         "uom": "PCS", "reported_role": "nvl", "opening": 2,
         "inbound_total": 2, "outbound_total": 1, "closing_reported": 3},
        {"internal_code": "A005", "customs_code": "CC005", "name": "n5",
         "uom": "PCS", "reported_role": "nvl", "opening": 0,
         "inbound_total": 9, "outbound_total": 9, "closing_reported": 0},
    ]
    aid = nxt_store.create_artifact(client_id=cid, lines=nxt_lines,
                                    period_year=2025)
    nxt_store.create_artifact(client_id=cid, lines=[], period_year=2024)

    inv_lines = [
        {"code": "M001", "name": "m1", "uom": "PCS", "warehouse": "KHO-A",
         "qty_book": 100, "qty_physical": 98},
        {"code": "M002", "name": "m2", "uom": "PCS", "warehouse": "KHO-A",
         "qty_book": 50, "qty_physical": 50},
        {"code": "M003", "name": "m3", "uom": "KG", "warehouse": "KHO-B",
         "qty_book": 10, "qty_physical": 12},
        {"code": "M004", "name": "m4", "uom": "PCS", "warehouse": "KHO-B",
         "qty_book": 5, "qty_physical": 5},
        {"code": "M005", "name": "m5", "uom": "PCS", "warehouse": "KHO-B",
         "qty_book": 1, "qty_physical": 0},
    ]
    sid = inv_store.create_snapshot(client_id=cid, lines=inv_lines,
                                    snapshot_date=date(2025, 12, 31))
    inv_store.create_snapshot(client_id=cid, lines=[],
                              snapshot_date=date(2024, 12, 31))
    return {"cid": cid, "aid": aid, "sid": sid}


# ── list filters ─────────────────────────────────────────────────────────

def test_list_nxt_period_year_filter(seeded):
    cid = seeded["cid"]
    r = _c().get(f"/v1/hub/dncxs/{cid}/nxt")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2
    r = _c().get(f"/v1/hub/dncxs/{cid}/nxt", params={"period_year": 2025})
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["period_year"] == 2025


def test_list_inventory_year_filter(seeded):
    cid = seeded["cid"]
    r = _c().get(f"/v1/hub/dncxs/{cid}/inventory-snapshots")
    assert len(r.json()["items"]) == 2
    r = _c().get(f"/v1/hub/dncxs/{cid}/inventory-snapshots",
                 params={"year": 2024})
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["snapshot_date"] == "2024-12-31"


# ── NXT lines: pagination + filters ──────────────────────────────────────

def test_nxt_lines_pagination_round_trip(seeded):
    cid, aid = seeded["cid"], seeded["aid"]
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = _c().get(f"/v1/hub/dncxs/{cid}/nxt/{aid}/lines",
                        params=params).json()
        assert body["total"] == 5
        assert body["artifact_id"] == aid
        assert body["server_time"]
        assert len(body["items"]) <= 2
        seen.extend(line["line_no"] for line in body["items"])
        cursor, pages = body["next_cursor"], pages + 1
        if not cursor:
            break
        assert pages < 10  # guard against a non-terminating cursor
    assert seen == [1, 2, 3, 4, 5]          # complete, ordered, no dups
    assert pages == 3                        # 2 + 2 + 1


def test_nxt_lines_closing_implied_present(seeded):
    cid, aid = seeded["cid"], seeded["aid"]
    body = _c().get(f"/v1/hub/dncxs/{cid}/nxt/{aid}/lines").json()
    first = body["items"][0]
    assert first["closing_implied"] == 12.0   # 10 + 5 − 3


def test_nxt_lines_code_filter_matches_either_code(seeded):
    cid, aid = seeded["cid"], seeded["aid"]
    # internal_code, case-insensitive
    body = _c().get(f"/v1/hub/dncxs/{cid}/nxt/{aid}/lines",
                    params={"code": "a001"}).json()
    assert body["total"] == 1 and body["items"][0]["internal_code"] == "A001"
    # customs_code
    body = _c().get(f"/v1/hub/dncxs/{cid}/nxt/{aid}/lines",
                    params={"code": "CC003"}).json()
    assert body["total"] == 1 and body["items"][0]["customs_code"] == "CC003"


def test_nxt_lines_role_filter(seeded):
    cid, aid = seeded["cid"], seeded["aid"]
    body = _c().get(f"/v1/hub/dncxs/{cid}/nxt/{aid}/lines",
                    params={"role": "nvl"}).json()
    assert body["total"] == 3
    assert all(line["reported_role"] == "nvl" for line in body["items"])


def test_nxt_lines_bad_cursor_400(seeded):
    cid, aid = seeded["cid"], seeded["aid"]
    r = _c().get(f"/v1/hub/dncxs/{cid}/nxt/{aid}/lines",
                 params={"cursor": "abc"})
    assert r.status_code == 400


def test_nxt_lines_unknown_artifact_404(seeded):
    cid = seeded["cid"]
    r = _c().get(f"/v1/hub/dncxs/{cid}/nxt/nxt_bogus/lines")
    assert r.status_code == 404


def test_nxt_lines_cross_client_404(seeded):
    aid = seeded["aid"]
    r = _c().get(f"/v1/hub/dncxs/other-client/nxt/{aid}/lines")
    assert r.status_code == 404


# ── inventory lines: pagination + filters ────────────────────────────────

def test_inventory_lines_pagination_and_variance(seeded):
    cid, sid = seeded["cid"], seeded["sid"]
    body = _c().get(f"/v1/hub/dncxs/{cid}/inventory-snapshots/{sid}/lines",
                    params={"limit": 3}).json()
    assert body["total"] == 5 and body["snapshot_id"] == sid
    assert len(body["items"]) == 3 and body["next_cursor"] == "3"
    assert body["items"][0]["variance"] == -2.0   # 98 − 100


def test_inventory_lines_code_filter(seeded):
    cid, sid = seeded["cid"], seeded["sid"]
    body = _c().get(f"/v1/hub/dncxs/{cid}/inventory-snapshots/{sid}/lines",
                    params={"code": "m003"}).json()
    assert body["total"] == 1 and body["items"][0]["code"] == "M003"


def test_inventory_lines_warehouse_filter(seeded):
    cid, sid = seeded["cid"], seeded["sid"]
    body = _c().get(f"/v1/hub/dncxs/{cid}/inventory-snapshots/{sid}/lines",
                    params={"warehouse": "KHO-B"}).json()
    assert body["total"] == 3
    assert all(line["warehouse"] == "KHO-B" for line in body["items"])


def test_inventory_lines_cross_client_404(seeded):
    sid = seeded["sid"]
    r = _c().get(f"/v1/hub/dncxs/other-client/inventory-snapshots/{sid}/lines")
    assert r.status_code == 404
