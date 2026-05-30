from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_data_hub_runtime_config(monkeypatch, tmp_path):
    from app import co_auth

    co_auth.clear_jwks_cache()
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    # Tests exercise the local file-store backend (DATA_HUB_ENABLED off). In a
    # real deployment that now raises SourceBackendUnavailable; opt into the
    # local fallback for the suite. DH-mode tests set DATA_HUB_ENABLED=1 anyway.
    monkeypatch.setenv("CO_ALLOW_LOCAL_SOURCE", "1")
    yield
    co_auth.clear_jwks_cache()
