"""Errors are surfaced elegantly: a browser navigation gets a styled HTML page,
an AJAX/fetch call keeps getting JSON {"detail": …} so in-page toasts still work.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def err_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def test_unknown_path_browser_gets_html_not_raw_json(err_client):
    resp = err_client.get("/no-such-path", headers={"accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]
    assert "Không tìm thấy trang" in resp.text
    assert not resp.text.lstrip().startswith("{")  # never a raw JSON blob


def test_unknown_path_fetch_gets_json(err_client):
    resp = err_client.get("/no-such-path", headers={"x-requested-with": "fetch", "accept": "text/html"})
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"]


def test_sec_fetch_dest_document_gets_html(err_client):
    resp = err_client.get("/no-such-path", headers={"sec-fetch-dest": "document", "accept": "*/*"})
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]


def test_sec_fetch_dest_empty_gets_json(err_client):
    # fetch() sets sec-fetch-dest: empty even without X-Requested-With.
    resp = err_client.get("/no-such-path", headers={"sec-fetch-dest": "empty", "accept": "*/*"})
    assert resp.headers["content-type"].startswith("application/json")


def test_default_client_gets_json(err_client):
    # TestClient default (accept */*, no html signal) → JSON, so API clients/tests keep JSON.
    resp = err_client.get("/no-such-path")
    assert resp.headers["content-type"].startswith("application/json")


def _seed_blocked(client_id="growatt", case_id="err-export-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "ERR-EXPORT", "title": "blocked export", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["SP1"],
        "products": [{"code": "SP1", "name": "SP1", "materials": [{"material_code": "M1"}]}],
        "origin_sheet_states": {"SP1": {"status": "stale"}},  # not-ready → export blocker
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def test_export_blocker_browser_renders_html_with_detail(err_client):
    case_id = _seed_blocked()
    resp = err_client.post(
        f"/clients/growatt/co-case/{case_id}/export-bang-ke",
        headers={"accept": "text/html"},
    )
    assert resp.status_code == 409
    assert "text/html" in resp.headers["content-type"]
    assert "Chưa thể xuất bảng kê" in resp.text
    assert "SP1" in resp.text


def test_export_blocker_fetch_gets_json_detail(err_client):
    case_id = _seed_blocked()
    resp = err_client.post(
        f"/clients/growatt/co-case/{case_id}/export-bang-ke",
        headers={"x-requested-with": "fetch"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("Chưa thể xuất bảng kê")


# A bad typed query param triggers RequestValidationError (422) before the route body.
_BAD_PARAM_URL = "/clients/growatt/co-case/x/origin/sheet/sp/substitute-candidates?material_code=m&limit=notanint"


def test_validation_error_browser_gets_html(err_client):
    resp = err_client.get(_BAD_PARAM_URL, headers={"accept": "text/html"})
    assert resp.status_code == 422
    assert "text/html" in resp.headers["content-type"]
    assert "không hợp lệ" in resp.text
    assert not resp.text.lstrip().startswith("{")


def test_validation_error_fetch_keeps_standard_json(err_client):
    resp = err_client.get(_BAD_PARAM_URL, headers={"x-requested-with": "fetch"})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/json")
    # FastAPI's standard 422 shape (error list) is preserved for API clients.
    assert isinstance(resp.json()["detail"], list)
