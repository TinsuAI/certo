"""Per-client default adapter binding for the NXT + inventory tiers (mig 085).

Mirrors app/stores/adapter_binding.py (BOM) but generalized over the two
settlement modules. `auto` (or an adapter since removed) reads back as the
detect-ranked fallback, so a binding never breaks the upload form.
"""
from __future__ import annotations

from app.database import connect
from app.parsers import inventory_adapters, nxt_adapters

AUTO = "auto"

_COLUMN = {
    "nxt": "default_nxt_adapter",
    "inventory": "default_inventory_adapter",
}
_REGISTRY = {
    "nxt": nxt_adapters,
    "inventory": inventory_adapters,
}


def _check_module(module: str) -> None:
    if module not in _COLUMN:
        raise ValueError(f"unknown module: {module!r}")


def _valid_names(module: str) -> set[str]:
    return set(_REGISTRY[module].adapter_names()) | {AUTO}


def _resolve_stored(module: str, raw: str | None) -> str:
    if not raw or raw == AUTO:
        return AUTO
    return raw if _REGISTRY[module].resolve(raw) is not None else AUTO


def get_default_adapter(client_id: str, module: str) -> str:
    _check_module(module)
    col = _COLUMN[module]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {col} from hub.clients where client_id=%s", (client_id,))
        row = cur.fetchone()
    return _resolve_stored(module, row[0] if row else None)


def set_default_adapter(client_id: str, module: str, name: str) -> None:
    _check_module(module)
    name = (name or AUTO).strip()
    if name not in _valid_names(module):
        raise ValueError(f"unknown adapter: {name!r}")
    stored = None if name == AUTO else name
    col = _COLUMN[module]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update hub.clients set {col}=%s where client_id=%s",
            (stored, client_id))


def list_bindings() -> list[dict]:
    """Every client + its effective default adapter per module (registry matrix)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select client_id, name, default_nxt_adapter, default_inventory_adapter "
            "from hub.clients order by client_id")
        rows = cur.fetchall()
    out = []
    for cid, cname, raw_nxt, raw_inv in rows:
        out.append({
            "client_id": cid, "name": cname,
            "nxt": _resolve_stored("nxt", raw_nxt),
            "nxt_degraded": bool(raw_nxt) and raw_nxt != AUTO
                            and _resolve_stored("nxt", raw_nxt) == AUTO,
            "inventory": _resolve_stored("inventory", raw_inv),
            "inventory_degraded": bool(raw_inv) and raw_inv != AUTO
                                  and _resolve_stored("inventory", raw_inv) == AUTO,
        })
    return out
