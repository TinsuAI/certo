"""#14 S1 — CO-owned client config editable in DH source-mode.

In DH source-mode `client_config` is partitioned: Data Hub owns the `bcct`
declaration-type preset; CO owns `allocation_code` + `co_stock`, persisted in the
local config store. `get_client_config` = local base + DH `bcct` overlay;
`save_client_config` writes the CO-owned sections locally and rejects a `bcct` edit.

File-mode (no BARRY_DATABASE_URL) exercises the local file `client_config_store`,
isolated to a tmp CLIENT_CONFIG_ROOT.
"""
from __future__ import annotations

import pytest

from app.data_hub_client import DataHubPortfolioService


class _FakeDataHub:
    """Mirrors the flat `/client-config` payload Data Hub returns (declaration
    types only)."""

    def __init__(self, eligible=("E11", "E13", "E15"), relevant=("E42",)):
        self.eligible = list(eligible)
        self.relevant = list(relevant)

    def get_client_config(self, _client_id: str) -> dict:
        return {
            "client_id": _client_id,
            "eligible_import_declaration_types": self.eligible,
            "relevant_export_declaration_types": self.relevant,
        }


class _NestedDataHub:
    """A DH deployment that returns a nested config carrying a co_stock field CO
    still falls back to (min_days_before_export)."""

    def __init__(self, min_days=5):
        self.min_days = min_days

    def get_client_config(self, _client_id: str) -> dict:
        return {
            "client_id": _client_id,
            "bcct": {
                "declaration_type_preset": "dncx",
                "eligible_import_declaration_types": ["E11", "E13", "E15"],
                "relevant_export_declaration_types": ["E42"],
            },
            "co_stock": {"lot_policy": "line_level", "min_days_before_export": self.min_days},
        }


@pytest.fixture
def _isolated_config_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIENT_CONFIG_ROOT", str(tmp_path))
    # No BARRY_DATABASE_URL in the file-mode test suite → the local store is the
    # file store under CLIENT_CONFIG_ROOT.
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    return tmp_path


def test_dh_mode_saves_co_owned_allocation_strategy(_isolated_config_root):
    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_FakeDataHub())

    base = service.get_client_config(client)
    # growatt-vn (not the legacy "growatt") defaults to same_as_customs_code.
    assert base["allocation_code"]["strategy"] == "same_as_customs_code"

    base["allocation_code"]["strategy"] = "description_regex"
    service.save_client_config(client, base)

    reread = service.get_client_config(client)
    assert reread["allocation_code"]["strategy"] == "description_regex"


def test_dh_bcct_overlays_local_base(_isolated_config_root):
    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_FakeDataHub(eligible=("E11", "E13", "E15")))

    config = service.get_client_config(client)
    # DH's declaration types win over the local default, even after a CO save.
    config["allocation_code"]["strategy"] = "description_regex"
    service.save_client_config(client, config)

    reread = service.get_client_config(client)
    assert reread["bcct"]["eligible_import_declaration_types"] == ["E11", "E13", "E15"]
    assert reread["bcct"]["relevant_export_declaration_types"] == ["E42"]


def test_dh_bcct_change_after_save_still_wins(_isolated_config_root):
    """A later DH declaration-type change is reflected on the next read — CO's
    saved allocation strategy persists, DH's bcct is re-overlaid live."""
    client = {"id": "growatt-vn"}
    hub = _FakeDataHub(eligible=("E11",))
    service = DataHubPortfolioService(hub)

    config = service.get_client_config(client)
    config["allocation_code"]["strategy"] = "description_regex"
    service.save_client_config(client, config)

    hub.eligible = ["E11", "E13", "E15"]  # DH changes the preset later
    reread = service.get_client_config(client)
    assert reread["bcct"]["eligible_import_declaration_types"] == ["E11", "E13", "E15"]
    assert reread["allocation_code"]["strategy"] == "description_regex"


def test_dh_mode_rejects_bcct_edit(_isolated_config_root):
    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_FakeDataHub(eligible=("E11", "E13", "E15")))

    config = service.get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = ["E99"]
    with pytest.raises(ValueError):
        service.save_client_config(client, config)


def test_co_stock_lot_policy_is_co_owned_and_persists(_isolated_config_root):
    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_FakeDataHub())

    config = service.get_client_config(client)
    config["co_stock"]["lot_policy"] = "manual_review"
    service.save_client_config(client, config)

    assert service.get_client_config(client)["co_stock"]["lot_policy"] == "manual_review"


def test_dh_co_stock_min_days_preserved_while_lot_policy_is_local(_isolated_config_root):
    """DH-supplied co_stock fields (min_days_before_export) survive; local owns
    lot_policy. Guards against a silent eligibility regression."""
    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_NestedDataHub(min_days=5))

    config = service.get_client_config(client)
    assert config["co_stock"]["min_days_before_export"] == 5

    config["co_stock"]["lot_policy"] = "manual_review"
    service.save_client_config(client, config)

    reread = service.get_client_config(client)
    assert reread["co_stock"]["lot_policy"] == "manual_review"  # local wins
    assert reread["co_stock"]["min_days_before_export"] == 5    # DH value preserved


def test_dh_min_days_change_reflected_after_local_save(_isolated_config_root):
    """A save must not pin DH's min_days into local: a later DH change wins."""
    client = {"id": "growatt-vn"}
    hub = _NestedDataHub(min_days=5)
    service = DataHubPortfolioService(hub)

    config = service.get_client_config(client)
    config["co_stock"]["lot_policy"] = "manual_review"
    service.save_client_config(client, config)

    hub.min_days = 9  # DH changes the fallback later
    assert service.get_client_config(client)["co_stock"]["min_days_before_export"] == 9


# --------------------------------------------------------------------------- #
# S4 — growatt-vn onboarding: effective strategy + lot resolution               #
# --------------------------------------------------------------------------- #
def test_growatt_vn_onboarding_resolves_embedded_codes(_isolated_config_root):
    """After seeding description_regex through the new save path, growatt-vn's
    effective strategy is description_regex and a lot whose goods_name embeds the
    internal code `... (920.0042600)` resolves allocation_code=920.0042600."""
    from app.client_config_store import DEFAULT_DESCRIPTION_REGEX, resolve_allocation_code

    client = {"id": "growatt-vn"}
    service = DataHubPortfolioService(_FakeDataHub())

    config = service.get_client_config(client)
    config["allocation_code"]["strategy"] = "description_regex"
    config["allocation_code"]["description_regex"] = DEFAULT_DESCRIPTION_REGEX
    service.save_client_config(client, config)

    effective = service.get_client_config(client)
    assert effective["allocation_code"]["strategy"] == "description_regex"

    # A real growatt-vn lot: short customs code + embedded internal code.
    lot = {
        "item_code": "LKN-DO",
        "description": "Đi ốt chỉnh lưu (920.0042600)",
        "material_identity": {"internal_code": None},
    }
    resolved = resolve_allocation_code(lot, effective)
    assert resolved["allocation_code"] == "920.0042600"
    assert resolved["source"] == "description_regex"

    # Contrast: the pre-onboarding default keys on the short customs code (4.5%).
    default_resolved = resolve_allocation_code(
        lot, {"allocation_code": {"strategy": "same_as_customs_code",
                                  "fallback": "same_as_customs_code"}},
    )
    assert default_resolved["allocation_code"] == "LKN-DO"
