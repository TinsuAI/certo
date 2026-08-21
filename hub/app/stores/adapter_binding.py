"""Per-client default BOM adapter binding (mig 081).

`hub.clients.default_bom_adapter` pins one registered adapter as the upload-form
default. Null (or an adapter that's since been removed) reads back as 'auto' —
the detect-ranked `parse_with_fallback` default — so a binding never breaks the
upload form.
"""
from __future__ import annotations

from app.database import connect
from app.parsers import bom_adapters

AUTO = "auto"


def _valid_names() -> set[str]:
    return set(bom_adapters.adapter_names()) | {AUTO}


def _resolve_stored(raw: str | None) -> str:
    """Stored value → effective adapter. Unset or unregistered → AUTO."""
    if not raw or raw == AUTO:
        return AUTO
    return raw if bom_adapters.resolve(raw) is not None else AUTO


def get_default_adapter(client_id: str) -> str:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select default_bom_adapter from hub.clients where client_id=%s",
            (client_id,),
        )
        row = cur.fetchone()
    return _resolve_stored(row[0] if row else None)


def set_default_adapter(client_id: str, name: str) -> None:
    name = (name or AUTO).strip()
    if name not in _valid_names():
        raise ValueError(f"unknown adapter: {name!r}")
    stored = None if name == AUTO else name
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.clients set default_bom_adapter=%s where client_id=%s",
            (stored, client_id),
        )


def list_bindings() -> list[dict]:
    """Every client + its effective default adapter (for the registry matrix).
    `degraded` flags a stored adapter that no longer resolves."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select client_id, name, default_bom_adapter from hub.clients "
            "order by client_id"
        )
        rows = cur.fetchall()
    out = []
    for cid, cname, raw in rows:
        resolved = _resolve_stored(raw)
        out.append({
            "client_id": cid, "name": cname,
            "default_bom_adapter": resolved,
            "degraded": bool(raw) and raw != AUTO and resolved == AUTO,
        })
    return out
