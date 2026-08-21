"""Per-client column-alias overrides (Phase 3 mapping overhaul).

Resolution: code-level ALIASES (parser modules) with the ENABLED client
rows layered on top. Empty config ⇒ code defaults unchanged. Used by the
rigid auto-match in the upload mapping flow so a client's local header
variants resolve without a code change.
"""
from __future__ import annotations

import copy

from hub.app.database import connect

_MODULES = ("bcct", "catalog", "bqd", "bom")


def _code_aliases(module: str) -> dict[str, list[str]]:
    """The code-level ALIASES dict for a module (the default layer)."""
    if module == "catalog":
        from hub.app.parsers.materials import ALIASES
        return ALIASES
    if module == "bqd":
        from hub.app.parsers.code_mappings import ALIASES
        return ALIASES
    if module == "bcct":
        from hub.app.parsers.bcct import ALIASES
        return ALIASES
    if module == "bom":
        try:
            from hub.app.parsers.bom_adapters.manual_flat import ALIASES  # type: ignore
            return ALIASES
        except Exception:  # noqa: BLE001
            return {}
    return {}


def resolved_aliases(client_id: str, module: str) -> dict[str, list[str]]:
    """Code ALIASES merged with this client's enabled overrides.

    Client aliases are appended to the matching field's alias list (deduped),
    so they ADD recognition without removing the built-in defaults.
    """
    merged = copy.deepcopy(_code_aliases(module))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select field, alias from hub.client_column_aliases "
            "where client_id = %s and module = %s and enabled",
            (client_id, module),
        )
        for field, alias in cur.fetchall():
            lst = merged.setdefault(field, [])
            if alias not in lst:
                lst.append(alias)
    return merged


def list_aliases(client_id: str, module: str) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, field, alias, enabled, created_at "
            "from hub.client_column_aliases "
            "where client_id = %s and module = %s "
            "order by field, alias",
            (client_id, module),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def add_alias(*, client_id: str, module: str, field: str, alias: str,
              created_by: str | None = None) -> None:
    """Upsert an alias; re-enables a previously disabled one."""
    alias = (alias or "").strip()
    field = (field or "").strip()
    if not alias or not field:
        raise ValueError("field and alias are required")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_column_aliases "
            "  (client_id, module, field, alias, enabled, created_by) "
            "values (%s, %s, %s, %s, true, %s) "
            "on conflict (client_id, module, field, alias) "
            "  do update set enabled = true",
            (client_id, module, field, alias, created_by),
        )


def set_alias_enabled(alias_id: int, enabled: bool, *, client_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.client_column_aliases set enabled = %s "
            "where id = %s and client_id = %s",
            (enabled, alias_id, client_id),
        )


def delete_alias(alias_id: int, *, client_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.client_column_aliases "
            "where id = %s and client_id = %s",
            (alias_id, client_id),
        )
