"""Audit event helpers — turn raw jsonb payload into compact display."""
from __future__ import annotations

import json

# Fields that change on every UPDATE without semantic meaning. Skip in diff.
_NOISY_FIELDS = frozenset({
    "created_at", "updated_at", "indexed_at",
})

# Fields whose values are large/opaque embedding vectors. Never dump the raw
# value into the change-history feed — it overflows the layout and means
# nothing to a user. Collapse to a dimension count instead.
_VECTOR_FIELDS = frozenset({
    "description_embedding",
})

# Max characters before a scalar/JSON value is truncated in the diff feed.
_MAX_DISPLAY_LEN = 120


def summarize_value(field: str, value):
    """Display-safe rendering of an audit value.

    Embedding vectors collapse to `[vector N chiều]`; long strings and JSON
    blobs (provenance, arrays) truncate with an ellipsis. Keeps the change
    history readable instead of unrolling a 1536-float vector across the page.
    """
    if value is None:
        return None
    if field in _VECTOR_FIELDS:
        if isinstance(value, (list, tuple)):
            return f"[vector {len(value)} chiều]"
        if isinstance(value, str) and value.strip():
            n = value.count(",") + 1
            return f"[vector ~{n} chiều]"
        return "[vector]"
    # Heuristic: any long numeric sequence is a vector-like blob.
    if (isinstance(value, (list, tuple)) and len(value) > 16
            and all(isinstance(x, (int, float)) for x in value[:4])):
        return f"[vector {len(value)} chiều]"
    if isinstance(value, (list, tuple, dict)):
        s = json.dumps(value, ensure_ascii=False, default=str)
    else:
        s = str(value)
    if len(s) > _MAX_DISPLAY_LEN:
        return s[:_MAX_DISPLAY_LEN] + "…"
    return s


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
            out.append({"field": key,
                        "old": summarize_value(key, ov),
                        "new": summarize_value(key, nv)})
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
            out.append({"field": key, "old": summarize_value(key, ov)})
        return out
    return []
