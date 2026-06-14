"""Slice 1 — NXT + inventory-snapshot tier foundation.

Covers the canonical system_template round-trip (render → parse), adapter
detect/fallback, and store create→read with runtime-derived closing_implied /
variance. See .ai/features/2026-06-14-nxt-inventory-tier/brief.md.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session
from app.database import connect
from app.main import app
from app.parsers import inventory_adapters, nxt_adapters
from app.parsers.nxt_adapters.system_template import (
    SystemTemplateNxtAdapter, render_template_xlsx as render_nxt,
)
from app.parsers.inventory_adapters.system_template import (
    SystemTemplateInventoryAdapter, render_template_xlsx as render_inv,
)
from app.stores import inventory_snapshots as inv_store
from app.stores import nxt as nxt_store

CLIENT = "nxt_tier_test"


@pytest.fixture(autouse=True)
def _client():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "NXT tier test"),
        )
    yield


@pytest.fixture
def isolated_files_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield
    storage_mod._BACKEND = None


# ── NXT adapter round-trip ──────────────────────────────────────────────

def test_nxt_template_roundtrip():
    lines = SystemTemplateNxtAdapter().parse(render_nxt())
    assert len(lines) == 3  # one sample row per NVL/TP/BTP sheet
    by_role = {l["reported_role"]: l for l in lines}
    assert set(by_role) == {"nvl", "tp", "btp"}

    nvl = by_role["nvl"]
    assert nvl["internal_code"] == "NVL-001"
    assert nvl["customs_code"] == "A0123"
    assert nvl["uom"] == "KG"
    assert nvl["opening"] == 1000
    assert nvl["inbound_total"] == 5000
    assert nvl["out_xuat_sx"] == 4500
    assert nvl["closing_reported"] == 1500

    # BTP sample has an empty customs code → None, not "".
    assert by_role["btp"]["customs_code"] is None


def test_nxt_detect_and_fallback():
    blob = render_nxt()
    assert SystemTemplateNxtAdapter().detect(blob) == pytest.approx(0.95)
    result = nxt_adapters.parse_with_fallback(blob)
    assert result is not None
    lines, name = result
    assert name == "system_template"
    assert len(lines) == 3


def test_nxt_detect_abstains_on_foreign_workbook():
    # An inventory template has no NVL/TP/BTP sheets → NXT adapter abstains.
    assert SystemTemplateNxtAdapter().detect(render_inv()) is None


# ── NXT store round-trip + derived closing_implied ──────────────────────

def test_nxt_store_roundtrip_and_closing_implied():
    lines = SystemTemplateNxtAdapter().parse(render_nxt())
    aid = nxt_store.create_artifact(
        client_id=CLIENT, lines=lines,
        period_from=date(2025, 1, 1), period_to=date(2025, 12, 31),
        source_kind="system_template", adapter_name="system_template",
    )
    art = nxt_store.get_artifact(aid)
    assert art is not None
    assert art["client_id"] == CLIENT
    assert art["period_to"] == date(2025, 12, 31)
    assert len(art["lines"]) == 3

    nvl = next(l for l in art["lines"] if l["reported_role"] == "nvl")
    # closing_implied = opening + inbound - Σ out = 1000 + 5000 - 4500 = 1500
    assert nvl["closing_implied"] == pytest.approx(1500.0)
    assert nvl["closing_reported"] == pytest.approx(1500.0)

    listed = nxt_store.list_artifacts(CLIENT)
    assert any(a["id"] == aid and a["n_lines"] == 3 for a in listed)


# ── Inventory adapter + store round-trip + derived variance ─────────────

def test_inventory_template_roundtrip():
    lines = SystemTemplateInventoryAdapter().parse(render_inv())
    assert len(lines) == 2
    first = lines[0]
    assert first["code"] == "NVL-001"
    assert first["warehouse"] == "Kho NVL"
    assert first["qty_book"] == 1500
    assert first["qty_physical"] == 1495


def test_inventory_detect_and_fallback():
    blob = render_inv()
    assert SystemTemplateInventoryAdapter().detect(blob) == pytest.approx(0.9)
    result = inventory_adapters.parse_with_fallback(blob)
    assert result is not None
    lines, name = result
    assert name == "system_template"
    assert len(lines) == 2


def test_inventory_store_roundtrip_and_variance():
    lines = SystemTemplateInventoryAdapter().parse(render_inv())
    sid = inv_store.create_snapshot(
        client_id=CLIENT, lines=lines, snapshot_date=date(2025, 12, 31),
        source_kind="system_template", adapter_name="system_template",
    )
    snap = inv_store.get_snapshot(sid)
    assert snap is not None
    assert snap["snapshot_date"] == date(2025, 12, 31)
    assert len(snap["lines"]) == 2
    first = snap["lines"][0]
    # variance = physical - book = 1495 - 1500 = -5
    assert first["variance"] == pytest.approx(-5.0)

    listed = inv_store.list_snapshots(CLIENT)
    assert any(s["id"] == sid and s["n_lines"] == 2 for s in listed)


# ── Template download routes ────────────────────────────────────────────

def _dev_client() -> TestClient:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select user_id from hub.users where role='dev' "
                    "and status='active' limit 1")
        row = cur.fetchone()
    assert row, "no seeded dev user"
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(row[0]))
    return c


_XLSX_MAGIC = b"PK"


@pytest.mark.parametrize("path, expect_name", [
    ("/templates/nxt.xlsx", "mau-nxt.xlsx"),
    ("/templates/inventory-snapshot.xlsx", "mau-ton-kho-cuoi-ky.xlsx"),
])
def test_template_download(path, expect_name):
    c = _dev_client()
    r = c.get(path)
    assert r.status_code == 200
    assert r.content.startswith(_XLSX_MAGIC)
    assert expect_name in r.headers["content-disposition"]


def test_template_download_requires_auth():
    r = TestClient(app).get("/templates/nxt.xlsx", follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)


# ── Upload → preview → confirm flow ─────────────────────────────────────

def test_nxt_upload_preview_confirm_flow(isolated_files_dir):
    c = _dev_client()
    files = {"file": ("mau-nxt.xlsx", render_nxt(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = c.post(f"/clients/{CLIENT}/nxt/upload",
               files=files,
               data={"period_from": "2025-01-01", "period_to": "2025-12-31"},
               follow_redirects=False)
    assert r.status_code == 303
    preview_url = r.headers["location"]
    assert "/nxt/preview/" in preview_url

    pv = c.get(preview_url)
    assert pv.status_code == 200
    assert "Tồn cuối khớp" in pv.text  # sample rows balance

    upload_id = preview_url.rstrip("/").split("/")[-1]
    cf = c.post(f"/clients/{CLIENT}/nxt/preview/{upload_id}/confirm",
                follow_redirects=False)
    assert cf.status_code == 303

    arts = nxt_store.list_artifacts(CLIENT)
    assert arts and arts[0]["n_lines"] == 3
    art = nxt_store.get_artifact(arts[0]["id"])
    assert art["period_to"] == date(2025, 12, 31)
    assert art["adapter_name"] == "system_template"


def test_inventory_upload_preview_confirm_flow(isolated_files_dir):
    c = _dev_client()
    files = {"file": ("mau-ton.xlsx", render_inv(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = c.post(f"/clients/{CLIENT}/inventory-snapshots/upload",
               files=files, data={"snapshot_date": "2025-12-31"},
               follow_redirects=False)
    assert r.status_code == 303
    preview_url = r.headers["location"]
    assert "/inventory-snapshots/preview/" in preview_url

    pv = c.get(preview_url)
    assert pv.status_code == 200
    assert "lệch sổ-thực" in pv.text  # sample has a 5-unit discrepancy

    upload_id = preview_url.rstrip("/").split("/")[-1]
    cf = c.post(f"/clients/{CLIENT}/inventory-snapshots/preview/{upload_id}/confirm",
                follow_redirects=False)
    assert cf.status_code == 303

    snaps = inv_store.list_snapshots(CLIENT)
    assert snaps and snaps[0]["n_lines"] == 2
    snap = inv_store.get_snapshot(snaps[0]["id"])
    assert snap["snapshot_date"] == date(2025, 12, 31)


def test_nxt_nav_tab_present():
    c = _dev_client()
    r = c.get(f"/clients/{CLIENT}/nxt")
    assert r.status_code == 200
    assert "Nhập-Xuất-Tồn" in r.text
    assert "Quyết toán" in r.text  # settlement nav group
