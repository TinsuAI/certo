"""Mine locally-recorded NVL substitution history from a client's CO cases.

A substitution only counts when it lives on a **locked** origin sheet — i.e. it
was committed into a real C/O dossier. Draft overrides (stale/calculated sheets)
are ignored so the recommendation list does not learn from throwaway edits.

History is keyed by the *base* BOM material code that was replaced, which is the
same `material_code` the substitute-candidates route receives when the modal
opens on a row. That lets the route pin previously-used substitutes to the top
of the recommendation list and inject ones Data Hub never proposed.

This is a CO-owned signal: it reads only this client's own case records, so it
needs no Data Hub endpoint.
"""
from __future__ import annotations

import time

_CACHE: dict[str, tuple[float, dict[str, list[dict]]]] = {}
_TTL_SECONDS = 60.0


def build_substitution_history(cases: list[dict]) -> dict[str, list[dict]]:
    """Return {base_material_code: [substitute_entry, ...]} from locked sheets.

    Each substitute_entry: {substitute_code, name, count, last_used, case_codes},
    sorted by count desc then last_used desc (most-used / most-recent first).
    """
    buckets: dict[str, dict[str, dict]] = {}
    for case in cases or []:
        states = case.get("origin_sheet_states") or {}
        if not isinstance(states, dict):
            continue
        case_code = str(case.get("case_code") or case.get("case_id") or "").strip()
        updated_at = str(case.get("updated_at") or "")
        products = {
            str(p.get("code") or "").strip(): p
            for p in (case.get("products") or [])
            if isinstance(p, dict)
        }
        for product_code, state in states.items():
            if not isinstance(state, dict) or state.get("status") != "locked":
                continue
            overrides = state.get("material_overrides") or {}
            if not isinstance(overrides, dict):
                continue
            materials = (products.get(str(product_code).strip()) or {}).get("materials") or []
            for key, override in overrides.items():
                if not isinstance(override, dict):
                    continue
                # Skip deletes and hand-added rows — only genuine swaps of an
                # existing BOM row count as "thay thế".
                if override.get("deleted") or override.get("added") or str(key).startswith("added_"):
                    continue
                to_code = str(override.get("material_code") or "").strip()
                if not to_code:
                    continue
                try:
                    idx = int(str(key))
                except (TypeError, ValueError):
                    continue
                if idx < 0 or idx >= len(materials):
                    continue
                base = materials[idx] if isinstance(materials[idx], dict) else {}
                from_code = str(base.get("material_code") or "").strip()
                if not from_code or from_code == to_code:
                    continue
                bucket = buckets.setdefault(from_code, {})
                entry = bucket.setdefault(to_code, {
                    "substitute_code": to_code,
                    "name": "",
                    "count": 0,
                    "last_used": "",
                    "case_codes": [],
                })
                entry["count"] += 1
                name = str(override.get("name") or "").strip()
                if name and not entry["name"]:
                    entry["name"] = name
                if updated_at > entry["last_used"]:
                    entry["last_used"] = updated_at
                if case_code and case_code not in entry["case_codes"]:
                    entry["case_codes"].append(case_code)

    return {
        from_code: sorted(
            bucket.values(),
            key=lambda e: (e["count"], e["last_used"]),
            reverse=True,
        )
        for from_code, bucket in buckets.items()
    }


def get_substitution_history(client: dict, *, ttl: float = _TTL_SECONDS) -> dict[str, list[dict]]:
    """TTL-cached history for a client. Scans all of the client's case records
    via the case workspace; cached briefly so reopening the modal does not
    re-load the full case state every time.
    """
    from app.co_case_store import get_case_workspace

    client_id = str(client.get("id") or "")
    now = time.monotonic()
    cached = _CACHE.get(client_id)
    if cached is not None and (now - cached[0]) < ttl:
        return cached[1]
    cases = get_case_workspace(client).get("cases") or []
    history = build_substitution_history(cases)
    _CACHE[client_id] = (now, history)
    return history


def invalidate(client_id: str = "") -> None:
    """Drop cached history (all clients, or one) — call after a lock changes."""
    if client_id:
        _CACHE.pop(client_id, None)
    else:
        _CACHE.clear()
