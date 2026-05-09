"""Audit event helpers — turn raw jsonb payload into compact display."""
from __future__ import annotations


# Fields that change on every UPDATE without semantic meaning. Skip in diff.
_NOISY_FIELDS = frozenset({
    "created_at", "updated_at", "indexed_at",
})


def audit_diff(event_type: str, payload: dict | None) -> list[dict]:
    """Return a compact field-level diff for display.

    For 'update' events: list of {"field", "old", "new"} for changed fields only.
    For 'delete' events: list of {"field", "old"} for non-null old values.

    Skips noisy internal fields (created_at/updated_at/indexed_at).
    """
    if not payload:
        return []
    if event_type == "update":
        old = payload.get("old") or {}
        new = payload.get("new") or {}
        out = []
        for key in sorted(set(old) | set(new)):
            if key in _NOISY_FIELDS:
                continue
            ov = old.get(key)
            nv = new.get(key)
            if ov == nv:
                continue
            out.append({"field": key, "old": ov, "new": nv})
        return out
    if event_type == "delete":
        old = payload.get("old") or {}
        out = []
        for key in sorted(old):
            if key in _NOISY_FIELDS:
                continue
            ov = old.get(key)
            if ov is None or ov == "" or ov == {} or ov == []:
                continue
            out.append({"field": key, "old": ov})
        return out
    return []
