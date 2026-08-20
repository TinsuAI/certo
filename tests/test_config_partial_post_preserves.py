"""A partial POST to the client-config route must not reset CO-owned config.

The route used to read every CO-owned field with `form.get(name, default)`, so
any POST that did not carry a field silently overwrote it with the default.
The measured damage: a POST carrying only `legal_name` reset
`allocation_code.strategy` to `same_as_customs_code`, which on growatt-vn takes
BOM matching from 2,145/2,236 rows to 101/2,236, and then
`refresh_client_indexes` rebuilt the indexes from the wrecked config.

The full config form posts every field, so a normal save is unaffected; these
tests pin the partial-POST behaviour that the form does not exercise.
"""
from __future__ import annotations

import asyncio

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


CONFIGURED = {
    "co_stock": {"lot_policy": "aggregate_by_declaration_and_allocation_code"},
    "allocation_code": {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "customs_code",
    },
    "features": {"bulk_delete_junk_rows": True},
    "bcct": {},
}


def _patch_service(monkeypatch, saved, refreshed, store=None):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    monkeypatch.setattr(pages, "resolve_client", lambda cid: {"id": cid})
    monkeypatch.setattr(pages, "get_app_state_store", lambda: store)
    monkeypatch.setattr(
        pages.portfolio_service,
        "get_client_config",
        lambda c: {k: dict(v) for k, v in CONFIGURED.items()},
    )

    def _save(c, cfg):
        saved["config"] = cfg
        return cfg

    monkeypatch.setattr(pages.portfolio_service, "save_client_config", _save)
    monkeypatch.setattr(
        pages.portfolio_service, "refresh_client_indexes",
        lambda c: refreshed.append(c),
    )
    monkeypatch.setattr(pages, "config_context", lambda cid, **kw: {})
    monkeypatch.setattr(pages, "declaration_type_exclusion_warning", lambda client, config: "")
    monkeypatch.setattr(pages.templates, "TemplateResponse", lambda **kw: kw)


def test_identity_only_post_does_not_touch_co_owned_config(monkeypatch):
    saved: dict = {}
    refreshed: list = []
    store = _RecordingStore()
    _patch_service(monkeypatch, saved, refreshed, store)

    asyncio.run(pages.save_client_config_route(
        _FakeReq({"legal_name": "CÔNG TY TNHH GROWATT VIỆT NAM"}), "growatt-vn"))

    # The identity field still persists to the client overlay …
    assert store.upserts and store.upserts[0]["legal_name"] == "CÔNG TY TNHH GROWATT VIỆT NAM"
    # … and the config sections the form never carried are left alone.
    assert "config" not in saved
    assert refreshed == []


def test_partial_config_post_keeps_the_fields_it_does_not_carry(monkeypatch):
    saved: dict = {}
    refreshed: list = []
    _patch_service(monkeypatch, saved, refreshed)

    asyncio.run(pages.save_client_config_route(
        _FakeReq({"co_stock_lot_policy": "manual_review"}), "growatt-vn"))

    cfg = saved["config"]
    assert cfg["co_stock"]["lot_policy"] == "manual_review"
    assert cfg["allocation_code"]["strategy"] == "description_regex"
    assert cfg["allocation_code"]["description_regex"] == r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)"
    assert cfg["allocation_code"]["fallback"] == "customs_code"
    # The feature flag is a checkbox, so absence is ambiguous on its own. This
    # POST carries no `features_section` marker, so it did not carry the
    # features card either — the stored flag must survive.
    assert cfg["features"]["bulk_delete_junk_rows"] is True
    assert refreshed, "a config change must still rebuild the indexes"


def test_checkbox_only_clears_when_its_section_was_submitted(monkeypatch):
    saved: dict = {}
    refreshed: list = []
    _patch_service(monkeypatch, saved, refreshed)

    # The real form always stamps `features_section`; an unchecked box then
    # legitimately means off.
    asyncio.run(pages.save_client_config_route(
        _FakeReq({"co_stock_lot_policy": "line_level", "features_section": "1"}), "growatt-vn"))
    assert saved["config"]["features"]["bulk_delete_junk_rows"] is False


def test_empty_description_regex_still_clears_it(monkeypatch):
    # Presence, not truthiness: an empty box the operator cleared on purpose
    # must still be written through.
    saved: dict = {}
    refreshed: list = []
    _patch_service(monkeypatch, saved, refreshed)

    asyncio.run(pages.save_client_config_route(
        _FakeReq({"allocation_code_strategy": "same_as_customs_code",
                  "description_regex": ""}), "growatt-vn"))

    cfg = saved["config"]
    assert cfg["allocation_code"]["strategy"] == "same_as_customs_code"
    assert cfg["allocation_code"]["description_regex"] == ""
    # Not carried by this POST → untouched.
    assert cfg["allocation_code"]["fallback"] == "customs_code"
