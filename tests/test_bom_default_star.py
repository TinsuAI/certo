"""Explicit favourite-★ for the per-client default BOM:
- POST /clients/{client}/bom-default sets/clears the default (reuses bom_default_store).
- co_case render context exposes `bom_defaults` so the picker can show ★/badge.
Additive to #14 (implicit write-through on pick stays); this just makes it
visible + explicitly controllable.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.main import app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    return TestClient(app)


def test_set_then_clear_bom_default(tmp_path, monkeypatch):
    http = _client(tmp_path, monkeypatch)
    from app import bom_default_store

    r = http.post("/clients/growatt/bom-default", json={"product_code": "PV00.0048500", "artifact_id": "art-7"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True and body["artifact_id"] == "art-7"
    assert bom_default_store.get_default("growatt", "PV00.0048500") == "art-7"

    r2 = http.post("/clients/growatt/bom-default", json={"product_code": "PV00.0048500", "artifact_id": ""})
    assert r2.status_code == 200
    assert r2.json()["is_default"] is False
    assert bom_default_store.get_default("growatt", "PV00.0048500") is None


def test_set_bom_default_requires_product_code(tmp_path, monkeypatch):
    http = _client(tmp_path, monkeypatch)
    r = http.post("/clients/growatt/bom-default", json={"artifact_id": "art-7"})
    assert r.status_code == 400


def test_context_exposes_bom_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    from app import bom_default_store
    from app.web.co_case_context import co_case_context
    from app.web.client_context import resolve_client

    bom_default_store.set_default("growatt", "PV00.0048500", "art-9")
    ctx = co_case_context("growatt", current_step="origin")
    assert ctx["bom_defaults"].get("PV00.0048500") == "art-9"
