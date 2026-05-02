from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_data_hub_runtime_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
