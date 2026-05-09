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
                    "customs_code": {"type": "string",
                                     "description": "HQ-assigned code (Mã HQ)"},
                    "internal_code": {"type": "string",
                                      "description": "Agency's internal code (Mã NB)"},
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
            "name": "query_uploads",
            "description": (
                "List recent file_uploads for the current client. Useful for "
                "questions like 'when was the last BCCT uploaded?' or 'why "
                "did this upload fail?'. Returns up to 20 by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {"type": "string",
                               "enum": ["bcct", "catalog", "bqd", "bom"]},
                    "parse_status": {"type": "string",
                                     "enum": ["pending", "done", "error",
                                              "proposed_mapping", "rejected"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                              "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_bcct_history",
            "description": (
                "Audit-log lookup for a specific BCCT row's change history. "
                "Use when user asks 'who changed this row?' or 'when was it "
                "last updated?'. Requires either declaration_no OR transaction_key."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "declaration_no": {"type": "string"},
                    "transaction_key": {"type": "string"},
                    "line_no": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                              "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_glossary",
            "description": (
                "Look up customs / domain terminology. Returns the definition "
                "from Data Hub's glossary if the term is found. Use for "
                "user questions like 'what is BCCT?' or 'what does NVL mean?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string",
                             "description": "Term to look up (case-insensitive, "
                                            "matches by substring)."},
                },
                "required": ["term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search Data Hub's curated project knowledge: glossary, "
                "architecture decisions, SSO/API notes, and feature briefs. "
                "Use before answering business-rule, architecture, workflow, "
                "or domain-context questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Search phrase or question"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8,
                              "default": 5},
                },
                "required": ["query"],
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


def tool_definitions_for_user(user) -> list[dict]:
    return TOOL_DEFINITIONS


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
    # mig 038: material_identity column dropped; agent surfaces
    # customs_code only here. Caller wanting parser-derived internal
    # code reads goods_name (raw text, agent can interpret).
    sql = (
        "select declaration_no, line_no, declaration_type, direction, "
        "       registration_date, customs_code, "
        "       goods_name, quantity, unit, "
        "       total_value, total_value_nt, currency_nt "
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


def _query_catalog(*, client_id: str, material_code: str | None = None,
                   name_query: str | None = None,
                   category: str | None = None,
                   provenance: str | None = None,
                   limit: int = 20,
                   # Legacy param accepted for backward compat in tool args
                   customs_code: str | None = None,
                   internal_code: str | None = None) -> dict:
    # Mig 042: customs_code (legacy) + internal_code (dropped column) → material_code.
    # Accept legacy args from agent tool calls for grace period; map to material_code.
    if material_code is None and customs_code is not None:
        material_code = customs_code
    if material_code is None and internal_code is not None:
        material_code = internal_code
    sql = (
        "select material_code, name, category, status, unit, "
        "       hs_code, source, hq_registered, provenance "
        "from hub.materials where client_id = %s"
    )
    params: list = [client_id]
    if material_code:
        sql += " and material_code = %s"
        params.append(material_code)
    if name_query:
        sql += " and name ilike %s"
        params.append(f"%{name_query}%")
    if category:
        sql += " and category = %s"
        params.append(category)
    # Provenance filter mapped to source/hq_registered post-mig-042
    if provenance == "registered":
        sql += " and hq_registered = true"
    elif provenance == "unregistered":
        sql += " and source = 'bcct_observed' and (hq_registered is null or hq_registered = false)"
    elif provenance == "user_added":
        sql += " and source = 'client_declared'"
    sql += " order by material_code limit %s"
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
                    select artifact_id, product_code, source, status,
                           created_at, row_count
                    from hub.bom_artifacts
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
                from hub.bom_artifacts
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
    # Post-mig-042: source/hq_registered columns replaced provenance jsonb keys
    # for query filtering. Observation stats now derive from v_material_roles view.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select m.material_code, m.name, m.category,
                       jsonb_build_object(
                         'observed_count', vmr.observed_count,
                         'observed_first_at', vmr.observed_first_at,
                         'observed_last_at', vmr.observed_last_at,
                         'observed_directions', vmr.observed_directions
                       ) as observation
                from hub.materials m
                left join hub.v_material_roles vmr
                       on vmr.client_id = m.client_id and vmr.material_code = m.material_code
                where m.client_id = %s
                  and m.source = 'bcct_observed'
                  and (m.hq_registered is null or m.hq_registered = false)
                order by m.material_code
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


def _query_uploads(*, client_id: str, module: str | None = None,
                   parse_status: str | None = None,
                   limit: int = 20) -> dict:
    sql = (
        "select upload_id, module, original_filename, parse_status, "
        "       parsed_at, uploader_user_id, parse_error, row_count, size_bytes "
        "from hub.file_uploads where client_id = %s"
    )
    params: list = [client_id]
    if module:
        sql += " and module = %s"
        params.append(module)
    if parse_status:
        sql += " and parse_status = %s"
        params.append(parse_status)
    sql += " order by parsed_at desc nulls last, upload_id desc limit %s"
    params.append(min(max(int(limit or 20), 1), 50))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
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


def _query_bcct_history(*, client_id: str,
                        declaration_no: str | None = None,
                        transaction_key: str | None = None,
                        line_no: str | None = None,
                        limit: int = 50) -> dict:
    if not (declaration_no or transaction_key):
        return {"ok": False,
                "error": "either declaration_no or transaction_key is required"}
    sql = (
        "select h.transaction_key, h.line_no, h.action, h.changed_by, "
        "       h.changed_at, "
        "       u.email as actor_email, "
        "       (h.old_row->>'quantity') as old_quantity, "
        "       (h.new_row->>'quantity') as new_quantity "
        "from hub.bcct_row_history h "
        "left join hub.users u on u.user_id = h.changed_by "
        "where h.client_id = %s"
    )
    params: list = [client_id]
    if transaction_key:
        sql += " and h.transaction_key = %s"
        params.append(transaction_key)
    elif declaration_no:
        # transaction_key isn't always == declaration_no; use the index on
        # bcct_rows to map. Easier: query history rows whose transaction_key
        # appears in bcct_rows for this declaration.
        sql += (" and h.transaction_key in ("
                "select distinct transaction_key from hub.bcct_rows "
                "where client_id = %s and declaration_no = %s)")
        params.extend([client_id, declaration_no])
    if line_no:
        sql += " and h.line_no = %s"
        params.append(line_no)
    sql += " order by h.changed_at desc limit %s"
    params.append(min(max(int(limit or 50), 1), 100))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
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


def _lookup_glossary(*, client_id: str, term: str) -> dict:
    """Substring search on .ai/GLOSSARY.md. Returns the matching bullet
    + 1-2 lines of context. Don't expose the full file (it's project
    metadata, not user content), just matched entries."""
    from pathlib import Path

    term_lower = (term or "").strip().lower()
    if not term_lower:
        return {"ok": False, "error": "term is required"}
    path = (Path(__file__).resolve().parent.parent.parent
            / ".ai" / "GLOSSARY.md")
    if not path.exists():
        return {"ok": False, "error": "glossary not available"}
    content = path.read_text(encoding="utf-8")
    matches: list[str] = []
    for line in content.splitlines():
        ls = line.strip()
        if not ls.startswith("- **"):
            continue
        if term_lower in ls.lower():
            matches.append(ls)
            if len(matches) >= 5:
                break
    return {"ok": True, "match_count": len(matches), "matches": matches}


def _search_knowledge_base(*, client_id: str, query: str, limit: int = 5) -> dict:
    """Small deterministic doc search over curated agent knowledge.

    This is not vector RAG. It is a constrained keyword search that gives
    the agent grounded snippets without exposing internal `.ai/*` context.
    """
    from pathlib import Path
    import re

    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query is required"}
    terms = [t for t in re.findall(r"[\wÀ-ỹ]+", q.lower()) if len(t) >= 2]
    if not terms:
        return {"ok": False, "error": "query has no searchable terms"}

    root = Path(__file__).resolve().parent.parent.parent
    knowledge_root = root / "docs" / "agent_knowledge"
    if not knowledge_root.exists():
        return {"ok": False, "error": "knowledge base not available"}
    sources = sorted(knowledge_root.rglob("*.md"))
    matches: list[tuple[int, str, str]] = []
    for path in sources:
        try:
            path.relative_to(knowledge_root)
        except ValueError:
            continue
        content = path.read_text(encoding="utf-8")
        blocks = re.split(r"\n(?=#{1,3} |\s*[-*] \*\*|\s*\d+\. )", content)
        for block in blocks:
            text = " ".join(line.strip() for line in block.splitlines()).strip()
            if not text:
                continue
            lower = text.lower()
            score = sum(lower.count(term) for term in terms)
            if score <= 0:
                continue
            snippet = text[:900] + ("..." if len(text) > 900 else "")
            matches.append((score, str(path.relative_to(knowledge_root)), snippet))
    matches.sort(key=lambda item: (-item[0], item[1], item[2]))
    cap = min(max(int(limit or 5), 1), 8)
    return {
        "ok": True,
        "match_count": len(matches[:cap]),
        "matches": [
            {"source": source, "snippet": snippet}
            for _score, source, snippet in matches[:cap]
        ],
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
    "query_uploads": _query_uploads,
    "query_bcct_history": _query_bcct_history,
    "lookup_glossary": _lookup_glossary,
    "search_knowledge_base": _search_knowledge_base,
    "submit_final_answer": _submit_final_answer,
}
