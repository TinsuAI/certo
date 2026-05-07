"""Phase 3c · adapter post_ingest_hooks contract.

Each registered BomAdapter exposes a `post_ingest_hooks` list of
string identifiers. The runner maps identifier → callable + invokes
the callable with (artifact_id, client_id) after a successful raw
artifact commit. Deep-tree adapters (sap_indented_walk,
multi_sheet_per_root) declare 'derive_btp_shallows'.

Wire-up into the upload flow is BACKLOG-tracked; this contract just
ensures the registry, identifiers, and runner work.
"""
from __future__ import annotations

import pytest

from app.parsers.bom_adapters import (
    HOOKS,
    adapter_names,
    resolve,
    run_post_ingest_hooks,
)


def test_every_adapter_declares_post_ingest_hooks():
    for name in adapter_names():
        adapter = resolve(name)
        assert hasattr(adapter, "post_ingest_hooks"), name
        assert isinstance(adapter.post_ingest_hooks, list), name


def test_deep_tree_adapters_declare_derive_btp_shallows():
    """SapIndentedWalk + MultiSheetPerRoot are the deep-tree shapes
    where intermediate parent_codes are real BTPs."""
    for name in ("sap_indented_walk", "multi_sheet_per_root"):
        adapter = resolve(name)
        assert "derive_btp_shallows" in adapter.post_ingest_hooks, name


def test_shallow_adapters_have_empty_hooks_by_default():
    """manual_flat / sheet_per_product / sap_exploded_levels don't
    need the BTP-shallow derivation since they emit one artifact per
    product already."""
    for name in ("manual_flat", "sheet_per_product"):
        adapter = resolve(name)
        assert adapter.post_ingest_hooks == [], name


def test_hook_registry_maps_identifier_to_callable():
    """HOOKS is the canonical identifier→callable map."""
    assert "derive_btp_shallows" in HOOKS
    assert callable(HOOKS["derive_btp_shallows"])


def test_run_post_ingest_hooks_no_op_for_unknown_adapter():
    """Unknown adapter name → no-op (defensive)."""
    out = run_post_ingest_hooks(
        adapter_name="not_a_real_adapter",
        artifact_id="ba_x", client_id="c_x",
    )
    assert out == []


def test_run_post_ingest_hooks_invokes_declared_hooks(monkeypatch):
    """For an adapter with hooks, the runner calls each. Verify by
    mocking the HOOKS map for this test."""
    calls: list[tuple[str, str]] = []

    def fake_hook(*, artifact_id: str, client_id: str, **kwargs):
        calls.append((artifact_id, client_id))
        return [{"hook": "fake"}]

    monkeypatch.setitem(HOOKS, "derive_btp_shallows", fake_hook)

    out = run_post_ingest_hooks(
        adapter_name="sap_indented_walk",
        artifact_id="ba_test", client_id="c_test",
    )
    assert calls == [("ba_test", "c_test")]
    assert out == [{"hook": "fake"}]
