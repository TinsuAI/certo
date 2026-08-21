"""bom_shape() helper — 4-shape model.

manual_flat_as_provided is now its own shape (was conflated with shallow).
Rationale: manual_flat is a SOURCE artifact (agency uploaded flat BOM
directly, no walker involved), whereas shallow is a DERIVED artifact
(walker stopped at first leaf — BTP or NVL). Lumping them together
under 'shallow' was misleading.

Spec: backlog "Re-evaluate shallow shape for manual_flat artifacts".
"""
from hub.app.stores.bom import bom_shape


def test_raw_graph_unchanged():
    assert bom_shape("non_flattened", "no_strategy") == "raw_graph"
    assert bom_shape("non_flattened", "any_strategy") == "raw_graph"


def test_manual_flat_is_its_own_shape():
    """manual_flat_as_provided → 'manual_flat' (not 'shallow')."""
    assert bom_shape("not_applicable", "manual_flat_as_provided") == "manual_flat"
    # Even when status is 'flattened' (legacy mislabel), strategy wins.
    assert bom_shape("flattened", "manual_flat_as_provided") == "manual_flat"


def test_shallow_only_for_purchased_btp_as_leaf_and_mixed():
    """shallow now means 'derived walker stopped at first leaf' —
    purchased_btp_as_leaf or mixed_confirmed."""
    assert bom_shape("flattened", "purchased_btp_as_leaf") == "shallow"
    assert bom_shape("flattened", "mixed_confirmed") == "shallow"


def test_full_flat_unchanged():
    assert bom_shape("flattened", "technical_exploded") == "full_flat"
    assert bom_shape("flattened", "self_produced_btp_exploded") == "full_flat"


def test_unknown_falls_back_to_shallow():
    """Conservative default for unrecognised flattened strategies."""
    assert bom_shape("flattened", "no_strategy") == "shallow"
