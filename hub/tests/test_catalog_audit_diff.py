"""Audit diff helper — turn raw jsonb payload into a compact field-level diff.

For 'update' events: compare old vs new, return only changed fields.
For 'delete' events: return all fields with their old values.
"""
from __future__ import annotations

from hub.app.stores.catalog_audit import audit_diff


def test_update_diff_only_changed_fields():
    payload = {
        "old": {"name": "Old", "category": "nvl", "uom": None, "client_id": "x"},
        "new": {"name": "New", "category": "nvl", "uom": "PIECES", "client_id": "x"},
    }
    diff = audit_diff("update", payload)
    fields = {d["field"]: d for d in diff}
    assert "name" in fields
    assert "uom" in fields
    assert "category" not in fields  # unchanged
    assert "client_id" not in fields  # unchanged
    assert fields["name"]["old"] == "Old"
    assert fields["name"]["new"] == "New"


def test_update_skips_noisy_internal_fields():
    """Skip created_at, updated_at, indexed_at which always change."""
    payload = {
        "old": {"name": "X", "created_at": "2026-04-01", "updated_at": "2026-04-01"},
        "new": {"name": "X", "created_at": "2026-04-01", "updated_at": "2026-05-01"},
    }
    diff = audit_diff("update", payload)
    assert all(d["field"] != "updated_at" for d in diff)


def test_delete_lists_all_fields():
    payload = {"old": {"name": "X", "category": "nvl", "uom": "PIECES"}}
    diff = audit_diff("delete", payload)
    assert len(diff) == 3
    fields = {d["field"] for d in diff}
    assert fields == {"name", "category", "uom"}


def test_delete_skips_null_fields():
    """No point listing fields that were already null."""
    payload = {"old": {"name": "X", "uom": None, "supplier_hint": None}}
    diff = audit_diff("delete", payload)
    fields = {d["field"] for d in diff}
    assert "name" in fields
    assert "uom" not in fields
    assert "supplier_hint" not in fields


def test_handles_empty_payload():
    assert audit_diff("update", {}) == []
    assert audit_diff("update", None) == []
