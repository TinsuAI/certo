from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_data_hub_runtime_config(monkeypatch, tmp_path):
    from app import co_auth

    co_auth.clear_jwks_cache()
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    yield
    co_auth.clear_jwks_cache()
