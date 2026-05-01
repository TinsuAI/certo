"""Curated read-only tools for the chat agent.

Each tool definition follows the OpenAI function-calling shape so the
runtime can pass them directly into `client.chat.completions.create(
tools=...)`. Every tool returns a dict serializable as JSON.

ACL contract: `dispatch_tool` re-verifies the caller's `auth.require_can_view_client`
on every call. The LLM cannot see or set `client_id`; it's threaded
from the runtime context. Cross-client queries are structurally
impossible — even a prompt-injected "use client_id=growatt-vn" arg
gets filtered out (we drop any client_id from args before dispatch).
"""
from __future__ import annotations

from typing import Any

from app import auth
from app.database import connect


# ── Tool definitions (OpenAI function-calling shape) ────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_bcct",
            "description": (
                "Query customs declarations (BCCT) for the current client. "
                "Use to look up specific declarations by number, "
                "find recent imports/exports, or count rows by year. "
                "Returns up to 20 rows by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer",
                             "description": "Filter by registration year (e.g. 2025)"},
                    "declaration_no": {"type": "string",
                                       "description": "Exact declaration number"},
                    "customs_code": {"type": "string",
                                     "description": "HS / customs code"},
                    "direction": {"type": "string", "enum": ["import", "export"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                              "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_catalog",
            "description": (
                "Query the material registry (Danh Mục) for the current client. "
                "Use to look up codes by customs/internal code, name keyword, "
                "category, or provenance source (registered / unregistered / "
                "user_added)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customs_code": {"type": "string"},
                    "name_query": {"type": "string",
                                   "description": "Substring match on name"},
                    "category": {"type": "string",
                                 "enum": ["nvl", "btp_sx", "btp_nm", "tp", "ccdc"]},
                    "provenance": {"type": "string",
                                   "enum": ["registered", "unregistered",
                                            "user_added"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                              "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_bom",
            "description": (
                "Query bill-of-materials (BOM) for the current client. "
                "Returns active versions (most recent first) for one product "
                "code, or list of products with BOMs if no code given."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": {"type": "string",
                                     "description": "Specific product code"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                              "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_provenance_alarms",
            "description": (
                "Return the list of customs codes that appear on BCCT "
                "declarations for the current client but are NOT yet "
                "registered with HQ. Used to surface 'pending registration' "
                "audit items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                              "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_final_answer",
            "description": (
                "Call when you have the final answer for the user. The text "
                "you pass becomes the assistant's user-facing reply. "
                "Always cite the tool result you used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string",
                               "description": "The complete user-facing answer "
                                              "(Vietnamese unless user wrote English)."},
                },
                "required": ["answer"],
            },
        },
    },
]


# ── Dispatcher with ACL ─────────────────────────────────────────────────

class ToolACLError(PermissionError):
    """Raised when the caller's permissions don't cover the tool's scope.
    Becomes a tool-result string so the LLM can adapt; never a 500."""


def dispatch_tool(*, user, client_id: str, name: str, args: dict) -> dict:
    """Dispatch a single tool call. Re-verifies user's permission on the
    client_id every call (defense in depth). Returns a JSON-serializable
    dict; never raises (caller renders errors as tool result content)."""
    try:
        auth.require_can_view_client(user, client_id)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"permission denied: {e}"}

    # Strip any client_id the LLM tried to put in args. Always use the
    # runtime-bound one. Same for user_id.
    args = {k: v for k, v in (args or {}).items()
            if k not in {"client_id", "user_id"}}

    impl = _IMPLS.get(name)
    if impl is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        return impl(client_id=client_id, **args)
    except TypeError as e:
        return {"ok": False, "error": f"bad args: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── Tool implementations ────────────────────────────────────────────────

def _query_bcct(*, client_id: str, year: int | None = None,
                declaration_no: str | None = None,
                customs_code: str | None = None,
                direction: str | None = None,
                limit: int = 20) -> dict:
    sql = (
        "select declaration_no, line_no, declaration_type, direction, "
        "       registration_date, customs_code, internal_code, "
        "       goods_name, quantity, unit, total_value, currency "
        "from hub.bcct_rows where client_id = %s"
    )
    params: list = [client_id]
    if year:
        sql += " and year = %s"
        params.append(year)
    if declaration_no:
        sql += " and declaration_no = %s"
        params.append(declaration_no)
    if customs_code:
        sql += " and customs_code = %s"
        params.append(customs_code)
    if direction:
        sql += " and direction = %s"
        params.append(direction)
    sql += " order by registration_date desc, line_no asc limit %s"
    params.append(min(max(int(limit or 20), 1), 50))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
    return {
        "ok": True,
        "row_count": len(rows),
        "rows": [
            {c: (v.isoformat() if hasattr(v, "isoformat") else
                 float(v) if hasattr(v, "as_tuple") else v)
             for c, v in zip(cols, r)}
            for r in rows
        ],
    }


def _query_catalog(*, client_id: str, customs_code: str | None = None,
                   name_query: str | None = None,
                   category: str | None = None,
                   provenance: str | None = None,
                   limit: int = 20) -> dict:
    sql = (
        "select customs_code, product_code, name, category, status, unit, "
        "       hs_code, provenance "
        "from hub.materials where client_id = %s"
    )
    params: list = [client_id]
    if customs_code:
        sql += " and customs_code = %s"
        params.append(customs_code)
    if name_query:
        sql += " and name ilike %s"
        params.append(f"%{name_query}%")
    if category:
        sql += " and category = %s"
        params.append(category)
    if provenance == "registered":
        sql += " and provenance ? 'registered_with_hq'"
    elif provenance == "unregistered":
        sql += (" and provenance ? 'seen_in_bcct' "
                "and not provenance ? 'registered_with_hq'")
    elif provenance == "user_added":
        sql += " and provenance ? 'user_added'"
    sql += " order by customs_code limit %s"
    params.append(min(max(int(limit or 20), 1), 50))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
    return {
        "ok": True,
        "row_count": len(rows),
        "rows": [dict(zip(cols, r)) for r in rows],
    }


def _query_bom(*, client_id: str, product_code: str | None = None,
               limit: int = 20) -> dict:
    if product_code:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select version_id, product_code, source, status,
                           created_at, row_count
                    from hub.bom_versions
                    where client_id = %s and product_code = %s
                      and tombstoned_at is null
                    order by created_at desc
                    limit %s
                    """,
                    (client_id, product_code, min(max(int(limit or 20), 1), 50)),
                )
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
        return {
            "ok": True, "row_count": len(rows),
            "rows": [
                {c: (v.isoformat() if hasattr(v, "isoformat") else v)
                 for c, v in zip(cols, r)}
                for r in rows
            ],
        }
    # No code → list distinct products
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select product_code, count(*) as version_count,
                       max(created_at) as latest_at
                from hub.bom_versions
                where client_id = %s and tombstoned_at is null
                group by product_code order by latest_at desc nulls last
                limit %s
                """,
                (client_id, min(max(int(limit or 20), 1), 50)),
            )
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
    return {
        "ok": True, "row_count": len(rows),
        "rows": [
            {c: (v.isoformat() if hasattr(v, "isoformat") else v)
             for c, v in zip(cols, r)}
            for r in rows
        ],
    }


def _query_provenance_alarms(*, client_id: str, limit: int = 50) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select customs_code, name, category, provenance->'seen_in_bcct'
                from hub.materials
                where client_id = %s
                  and provenance ? 'seen_in_bcct'
                  and not provenance ? 'registered_with_hq'
                order by customs_code
                limit %s
                """,
                (client_id, min(max(int(limit or 50), 1), 100)),
            )
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
    return {
        "ok": True, "row_count": len(rows),
        "rows": [dict(zip(cols, r)) for r in rows],
    }


def _submit_final_answer(*, client_id: str, answer: str) -> dict:
    """Marker tool — runtime detects this name and terminates the loop.
    The implementation just echoes the answer so it's recorded as tool
    result; the runtime grabs the answer from the call args directly."""
    return {"ok": True, "final": True, "answer": answer}


_IMPLS: dict[str, Any] = {
    "query_bcct": _query_bcct,
    "query_catalog": _query_catalog,
    "query_bom": _query_bom,
    "query_provenance_alarms": _query_provenance_alarms,
    "submit_final_answer": _submit_final_answer,
}
