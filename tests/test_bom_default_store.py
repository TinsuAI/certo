"""Tests for app.bom_default_store — per-client default BOM pick per product.

JSON-fallback tests run anywhere. The DB path mirrors cost_allocation_store
and is exercised by the migration applying cleanly in CI.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_config_root(monkeypatch, tmp_path):
    root = tmp_path / "bom-default"
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(root))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    yield root


def test_empty_client_returns_empty(isolated_config_root):
    from app.bom_default_store import get_defaults, get_default
    assert get_defaults("growatt") == {}
    assert get_default("growatt", "P1") is None


def test_set_and_get_default(isolated_config_root):
    from app.bom_default_store import set_default, get_default, get_defaults
    set_default("growatt", "PV00.1", "art-v3")
    assert get_default("growatt", "PV00.1") == "art-v3"
    assert get_defaults("growatt") == {"PV00.1": "art-v3"}


def test_set_default_overwrites_pin(isolated_config_root):
    from app.bom_default_store import set_default, get_default
    set_default("growatt", "PV00.1", "art-v3")
    set_default("growatt", "PV00.1", "art-v5")
    assert get_default("growatt", "PV00.1") == "art-v5"


def test_multiple_codes_isolated_per_client(isolated_config_root):
    from app.bom_default_store import set_default, get_defaults
    set_default("growatt", "P1", "a1")
    set_default("growatt", "P2", "a2")
    set_default("johnson", "P1", "b1")
    assert get_defaults("growatt") == {"P1": "a1", "P2": "a2"}
    assert get_defaults("johnson") == {"P1": "b1"}


def test_delete_default(isolated_config_root):
    from app.bom_default_store import set_default, delete_default, get_defaults
    set_default("growatt", "P1", "a1")
    set_default("growatt", "P2", "a2")
    delete_default("growatt", "P1")
    assert get_defaults("growatt") == {"P2": "a2"}


def test_set_default_ignores_blank(isolated_config_root):
    from app.bom_default_store import set_default, get_defaults
    set_default("growatt", "", "a1")
    set_default("growatt", "P1", "")
    assert get_defaults("growatt") == {}


def test_picks_from_payload_overrides_map():
    from app.bom_default_store import picks_from_payload
    payload = {"bom_product_artifact_overrides": {"P1": "a1", " ": "x", "P2": ""}}
    assert picks_from_payload(payload) == {"P1": "a1"}


def test_picks_from_payload_per_product_wins_over_map():
    from app.bom_default_store import picks_from_payload
    payload = {
        "bom_product_artifact_overrides": {"P1": "old"},
        "products": [
            {"code": "P1", "bom_product_artifact_id": "new"},
            {"code": "P2", "bom_product_version_id": "a2"},
            {"code": "", "bom_product_artifact_id": "x"},
        ],
    }
    assert picks_from_payload(payload) == {"P1": "new", "P2": "a2"}


def test_picks_from_payload_empty():
    from app.bom_default_store import picks_from_payload
    assert picks_from_payload({}) == {}
    assert picks_from_payload({"products": [{"code": "P1"}]}) == {}


def test_write_through_persists_new_picks(isolated_config_root):
    from app.routers.co_case import persist_bom_picks_as_defaults
    from app.bom_default_store import get_defaults
    payload = {
        "bom_product_artifact_overrides": {"P1": "art-1"},
        "products": [{"code": "P2", "bom_product_artifact_id": "art-2"}],
    }
    persist_bom_picks_as_defaults({"id": "growatt"}, payload, prior_overrides={})
    assert get_defaults("growatt") == {"P1": "art-1", "P2": "art-2"}


def test_write_through_skips_unchanged_pick(isolated_config_root):
    """Echoing a case's existing selection must NOT touch the client default."""
    from app.routers.co_case import persist_bom_picks_as_defaults
    from app.bom_default_store import set_default, get_defaults
    set_default("growatt", "P1", "newer-default")
    payload = {"products": [{"code": "P1", "bom_product_artifact_id": "stale-case-pick"}]}
    persist_bom_picks_as_defaults({"id": "growatt"}, payload, prior_overrides={"P1": "stale-case-pick"})
    assert get_defaults("growatt") == {"P1": "newer-default"}  # unchanged


def test_write_through_writes_changed_pick(isolated_config_root):
    from app.routers.co_case import persist_bom_picks_as_defaults
    from app.bom_default_store import get_default
    payload = {"products": [{"code": "P1", "bom_product_artifact_id": "v5"}]}
    persist_bom_picks_as_defaults({"id": "growatt"}, payload, prior_overrides={"P1": "v2"})
    assert get_default("growatt", "P1") == "v5"


def test_write_through_noop_without_client_id(isolated_config_root):
    from app.routers.co_case import persist_bom_picks_as_defaults
    from app.bom_default_store import get_defaults
    persist_bom_picks_as_defaults({}, {"bom_product_artifact_overrides": {"P1": "art-1"}}, prior_overrides={})
    assert get_defaults("growatt") == {}
