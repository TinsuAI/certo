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

