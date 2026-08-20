"""#14 S2 — the config-save route in DH source-mode.

CO-owned config fields (allocation_code + co_stock lot_policy) must save in DH
source-mode without tripping the read-only source-write gate; only a
declaration-type (bcct) field trips it (409).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.routers import pages


class _FakeReq:
    def __init__(self, form):
        self._form = form

    async def form(self):
        return self._form


class _RecordingStore:
    def __init__(self):
        self.upserts = []

    def upsert_client(self, client):
        self.upserts.append(client)


def _patch_service(monkeypatch, saved, store=None):
    monkeypatch.setattr(pages, "resolve_client", lambda cid: {"id": cid})
    monkeypatch.setattr(pages, "get_app_state_store", lambda: store)
    monkeypatch.setattr(
        pages.portfolio_service, "get_client_config",
        lambda c: {"co_stock": {"lot_policy": "line_level"},
                   "allocation_code": {"strategy": "same_as_customs_code",
                                       "description_regex": "", "fallback": "same_as_customs_code"},
                   "bcct": {}},
    )

    def _save(c, cfg):
        saved["config"] = cfg
        return cfg

    monkeypatch.setattr(pages.portfolio_service, "save_client_config", _save)
    monkeypatch.setattr(pages.portfolio_service, "refresh_client_indexes", lambda c: None)
    monkeypatch.setattr(pages, "config_context", lambda cid, **kw: {})
    monkeypatch.setattr(pages, "declaration_type_exclusion_warning", lambda client, config: "")
    monkeypatch.setattr(pages.templates, "TemplateResponse", lambda **kw: kw)


def test_allocation_only_save_not_blocked_in_dh_mode(monkeypatch):
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    saved: dict = {}
    _patch_service(monkeypatch, saved)

    req = _FakeReq({
        "co_stock_lot_policy": "line_level",
        "allocation_code_strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "allocation_code_fallback": "same_as_customs_code",
    })
    # Must NOT raise the 409 source-write gate.
    asyncio.run(pages.save_client_config_route(req, "growatt-vn"))
    assert saved["config"]["allocation_code"]["strategy"] == "description_regex"


def test_declaration_type_change_trips_gate_in_dh_mode(monkeypatch):
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    saved: dict = {}
    _patch_service(monkeypatch, saved)

    req = _FakeReq({
        "allocation_code_strategy": "description_regex",
        "eligible_import_declaration_types": "E11,E13",
    })
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pages.save_client_config_route(req, "growatt-vn"))
    assert exc.value.status_code == 409
    assert "config" not in saved  # nothing persisted


def test_declaration_type_with_overlay_persists_nothing_in_dh_mode(monkeypatch):
    """The gate fires UP FRONT: a POST mixing a declaration-type field with an
    overlay field must 409 with neither the overlay nor the config written."""
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    saved: dict = {}
    store = _RecordingStore()
    _patch_service(monkeypatch, saved, store=store)

    req = _FakeReq({
        "tkn_pdf_max_part_mb": "5",                 # CO-side overlay
        "eligible_import_declaration_types": "E11",  # DH-owned bcct change
    })
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pages.save_client_config_route(req, "growatt-vn"))
    assert exc.value.status_code == 409
    assert store.upserts == []   # overlay NOT partial-saved
    assert "config" not in saved


def test_allocation_save_allowed_when_dh_mode_off(monkeypatch):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    saved: dict = {}
    _patch_service(monkeypatch, saved)

    req = _FakeReq({
        "co_stock_lot_policy": "manual_review",
        "allocation_code_strategy": "same_as_customs_code",
    })
    asyncio.run(pages.save_client_config_route(req, "growatt-vn"))
    assert saved["config"]["co_stock"]["lot_policy"] == "manual_review"


def test_features_bulk_delete_checkbox_saved_on(monkeypatch):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    saved: dict = {}
    _patch_service(monkeypatch, saved)   # mocked config has no `features` key → setdefault path

    req = _FakeReq({
        "co_stock_lot_policy": "line_level",
        "allocation_code_strategy": "same_as_customs_code",
        "features_bulk_delete_junk_rows": "1",
    })
    asyncio.run(pages.save_client_config_route(req, "growatt-vn"))
    assert saved["config"]["features"]["bulk_delete_junk_rows"] is True


def test_features_bulk_delete_checkbox_absent_is_off(monkeypatch):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    saved: dict = {}
    _patch_service(monkeypatch, saved)

    req = _FakeReq({
        "co_stock_lot_policy": "line_level",
        "allocation_code_strategy": "same_as_customs_code",
        # Unchecked → the checkbox field is absent, but the form still stamps
        # `features_section`, which is what makes absence readable as "off".
        "features_section": "1",
    })
    asyncio.run(pages.save_client_config_route(req, "growatt-vn"))
    assert saved["config"]["features"]["bulk_delete_junk_rows"] is False
