"""Per-company feature flag `features.bulk_delete_junk_rows` (default off).

Gates the "chọn NVL rác → xoá hàng loạt" action on both the per-sheet grid and the
aggregate "Tổng hợp NVL" sheet. CO-owned config section: must default off, backfill
on migrate, and survive both the file-mode store and the DH partition-merge save.
"""
from __future__ import annotations

import pytest

from app.data_hub_client import DataHubPortfolioService


class _FakeDataHub:
    """Flat `/client-config` payload DH returns (declaration types only)."""

    def get_client_config(self, _client_id: str) -> dict:
        return {
            "client_id": _client_id,
            "eligible_import_declaration_types": ["E11", "E15"],
            "relevant_export_declaration_types": ["E42"],
        }

    def source_summary(self, _client_id: str) -> dict:
        return {
            "client_config": self.get_client_config(_client_id),
            "material_catalog": {"published_row_count": 0, "latest_version": {}},
            "product_catalog": {"published_row_count": 0, "latest_version": {}},
            "bcct": {"published_row_count": 0, "latest_version": {}},
            "co_stock_row_count": 0,
        }


@pytest.fixture
def _cfg_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIENT_CONFIG_ROOT", str(tmp_path))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    return tmp_path


def test_default_config_flag_is_off():
    from app.client_config_store import default_config

    cfg = default_config({"id": "acme"})
    assert cfg["features"]["bulk_delete_junk_rows"] is False


def test_migrate_backfills_features_for_old_config():
    from app.client_config_store import migrate_config

    old = {
        "client_id": "acme",
        "co_stock": {"lot_policy": "line_level"},
        "allocation_code": {
            "strategy": "same_as_customs_code",
            "description_regex": "",
            "fallback": "same_as_customs_code",
        },
    }  # no `features` key at all
    merged = migrate_config(old, {"id": "acme"})
    assert merged["features"]["bulk_delete_junk_rows"] is False


def test_file_mode_toggle_round_trips(_cfg_root):
    from app.client_config_store import get_client_config, save_client_config

    client = {"id": "acme"}
    assert get_client_config(client)["features"]["bulk_delete_junk_rows"] is False

    cfg = get_client_config(client)
    cfg["features"]["bulk_delete_junk_rows"] = True
    save_client_config(client, cfg)

    assert get_client_config(client)["features"]["bulk_delete_junk_rows"] is True


def test_dh_mode_persists_incoming_features_toggle(_cfg_root):
    """DH-mode save builds `to_save` from local_base — the incoming toggle must be
    carried explicitly or it would be silently dropped in production (DH source-mode).
    """
    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_FakeDataHub())

    cfg = service.get_client_config(client)
    assert cfg["features"]["bulk_delete_junk_rows"] is False

    cfg["features"]["bulk_delete_junk_rows"] = True
    service.save_client_config(client, cfg)

    assert service.get_client_config(client)["features"]["bulk_delete_junk_rows"] is True
    # DH-owned bcct still overlaid alongside the CO-owned feature flag.
    assert service.get_client_config(client)["bcct"]["eligible_import_declaration_types"] == ["E11", "E15"]
