"""Broad guard: EVERY /v1/hub/* route must enforce auth.

The 2026-06-06 leak was an assembly/deploy gap, not a single bad handler
— so this tests the whole class, against the REAL ASGI app object
(`app.main.app`), two ways:

1. Behavioral (strict mode = prod config): an anonymous request to every
   /v1/hub route must NEVER return 2xx. A new route that forgets auth
   shows up here as a 200.
2. Structural: every /v1/hub handler must take an `authorization` Header
   param AND call an auth helper (`_require_token` / `_require_jwt_claims`).
   Catches a route that declares the param but forgets to check it, and a
   route added without either.

Intentionally-public /v1/hub paths must be added to PUBLIC_ALLOWLIST
(reviewed) — that's the one place a reviewer signs off on a public hub
route, so the test fails loudly if someone skips that review.
"""
from __future__ import annotations

import inspect
import re
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import settings_store
from app.main import app

HUB_PREFIX = "/v1/hub"

# Reviewed, intentionally-unauthenticated /v1/hub paths. Add here ONLY
# with a security review — every entry is a public hub surface.
PUBLIC_ALLOWLIST = {
    "/v1/hub/healthz",  # liveness probe; returns {"status":"ok"}, no data
}


def _hub_routes():
    seen = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith(HUB_PREFIX) and getattr(r, "endpoint", None):
            seen.append(r)
    assert seen, "no /v1/hub routes found — wrong app object?"
    return seen


def _fill(path: str) -> str:
    # Replace {param} and {param:path} with a dummy segment.
    return re.sub(r"\{[^}]+\}", "x", path)


# ─── 1. Behavioral: anonymous must never get 2xx (real ASGI app) ─────


@pytest.fixture
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_on(isolated_keys_dir, monkeypatch):
    # Mirror prod: strict on, dev kill-switch off — so the check can't be
    # silently disabled by an env var leaking into the test environment.
    monkeypatch.delenv("DATA_HUB_API_AUTH_DISABLED", raising=False)
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


def test_no_v1_hub_route_serves_2xx_anonymously(strict_mode_on):
    client = TestClient(app)
    leaks = []
    for r in _hub_routes():
        if r.path in PUBLIC_ALLOWLIST:
            continue
        for method in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
            resp = client.request(method, _fill(r.path))  # no auth header
            if 200 <= resp.status_code < 300:
                leaks.append(f"{method} {r.path} -> {resp.status_code}")
    assert not leaks, (
        "anonymous request returned 2xx on auth-required /v1/hub routes:\n"
        + "\n".join(leaks)
    )


# ─── 2. Structural: every handler wires auth ─────────────────────────


def test_every_v1_hub_handler_enforces_auth():
    missing = []
    for r in _hub_routes():
        if r.path in PUBLIC_ALLOWLIST:
            continue
        ep = r.endpoint
        params = inspect.signature(ep).parameters
        try:
            src = inspect.getsource(ep)
        except (OSError, TypeError):
            src = ""
        has_param = "authorization" in params
        calls_auth = ("_require_token" in src) or ("_require_jwt_claims" in src)
        if not (has_param and calls_auth):
            missing.append(
                f"{r.path} (authorization param={has_param}, "
                f"auth-helper call={calls_auth})"
            )
    assert not missing, (
        "/v1/hub routes missing the auth dependency "
        "(add to PUBLIC_ALLOWLIST only after security review):\n"
        + "\n".join(missing)
    )


def test_allowlist_entries_are_real_hub_routes():
    # Keep the allowlist honest: every entry must be a live /v1/hub route,
    # so stale entries can't quietly widen the public surface.
    live = {r.path for r in _hub_routes()}
    stale = PUBLIC_ALLOWLIST - live
    assert not stale, f"PUBLIC_ALLOWLIST has paths that no longer exist: {stale}"


def test_declaration_download_routes_are_guarded():
    # Explicit anchor for the incident: the two leaked routes + metadata
    # must be present and NOT in the public allowlist.
    live = {r.path for r in _hub_routes()}
    for p in (
        "/v1/hub/clients/{client_id}/declarations/download.pdf",
        "/v1/hub/clients/{client_id}/declarations/download.zip",
        "/v1/hub/clients/{client_id}/declarations",
    ):
        assert p in live, f"expected route missing: {p}"
        assert p not in PUBLIC_ALLOWLIST, f"{p} must never be public"
