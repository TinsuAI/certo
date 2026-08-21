# BCQT-System borrow survey

**Date:** 2026-05-02 | Sprint B0 (research only).

Reviewed BCQT-System (`~/workspace/client/BCQT-System`) for three patterns
to lift into Data Hub. Concise notes per pattern below; full citations to
the source files for the implementation step.

## 1. LLM optimizations

**Already in Data Hub:** structured output via `response_format=json_object`,
hallucination guard (drop unknown logical_fields/headers), per-(date,
client_id) budget enforcement (`hub.llm_usage`).

**Worth borrowing:**
- **Self-correction retry loop** with explicit error feedback to the LLM.
  Reference: `BCQT-System/app/pipeline/user_checks.py:200-250` "draft and
  validate" pattern. When schema validation fails, return the error text
  to the LLM and ask for a fixed mapping. Cap retries (BCQT uses `max_retries=2`).
- **Mtime-based KB cache** for system prompt + module field lists.
  Reference: `BCQT-System/app/agent/knowledge.py`. Same string instance
  per cache key keeps Anthropic's prompt cache warm across turns. (Less
  applicable to local vLLM but still cheap.)

**Skip:** Anthropic-specific `cache_control: ephemeral` (Data Hub uses
OpenAI-compat, local endpoints don't expose cache tokens). Multi-turn
agent loop — orthogonal to Data Hub's single-shot mapping proposal.

**Watch-out (BCQT learned):** `data=[(k,v),...]` form encoding with
TestClient produces wrong shape; switched to `data={k: [v1, v2]}` for
multi-value fields.

## 2. Notification system

**BCQT impl:** simple in-app feed.
- Schema: `migrations/app/011_notifications.sql` — single table
  `(id, user_id, kind, title, body, link_url, status, project_id,
  related_kind, related_id, created_at, read_at)` + index on
  `(user_id, status, created_at desc)`.
- Helper: `app/notifications.py` — `notify()`, `list_for_user()`,
  `unread_count()`, `mark_read()`, `mark_all_read()`, `get_for_user()`.
  Each opens its own connection so background tasks (no request scope)
  can call `notify()`.
- Routes: `app/routes/notifications.py` — bell fragment (HTMX-polled
  every 15s), list page, mark-read POST, mark-all-read POST. 404 silent
  (existence-leak hardening).
- UI: `templates/notifications/_bell.html` — `<details>`-based
  dropdown bell + badge.

**Adopt for Data Hub** with these adjustments:
- Postgres not SQLite (`bigserial` PK, `tz`-aware timestamps).
- Replace `project_id` → `client_id` (matches Data Hub's domain).
- Status state machine: just `unread` / `read` for MVP. Defer
  `archived` to phase 2 (BCQT did same).
- Drop email/SMS — defer to phase 2 (BCQT didn't ship either).
- Use Data Hub's existing translation pattern (`t('...')`) for labels.

**Watch-out (BCQT learned):** bell dropdown looked transparent in
production despite `var(--surface)`. Always provide a hardcoded
`background-color` fallback alongside the CSS custom property.

## 3. Chat-agent with strict ACL

**BCQT impl:** `app/agent/*` + `app/routes/agent.py`.
- 8 read-only tools (`try_sql`, `try_python`, `lookup_knowledge`,
  `lookup_glossary`, `export_excel`, etc.). Tools return
  `{"ok": bool, ...}`.
- Termination via explicit `submit_final_answer` tool — no
  inference-time flag.
- Per-project scoping: `_readonly_conn(project_id)` returns
  SQLite URI mode=ro. The `project_id` is threaded by route, never
  exposed to the LLM message — cross-customer hallucinations
  structurally impossible.
- Python sandbox: restricted `__builtins__` (no `__import__/exec/eval`).
  Documented as "adequate for trusted admin", not bulletproof.
- Threads scoped to (project, user). Cross-user access returns 404
  (existence-leak hardening, same pattern as notifications).
- Async: `BackgroundTasks` so long turns don't block UI.
- Per-project KB: `data/{project_id}/agent_kb/`. Prevents cross-project
  data leak in prompt.

**Adapt for Data Hub:**
- Replace `project_id` → `client_id`. Per-client read-only Postgres
  role (or row-level SELECT predicate). Use Data Hub's existing
  `auth.require_can_view_client(user, client_id)` to gate tool calls
  against the *user's* permissions, not just the client_id passed.
- Tool surface specific to Data Hub use cases:
  - `query_bcct(client_id, declaration_no=, date_range=)` → list rows
  - `query_catalog(client_id, code=, category=)` → list materials
  - `query_bom(client_id, product_code=)` → list versions
  - `query_provenance_alerts(client_id)` → unregistered codes
  - `lookup_glossary(term)` → customs terminology
  - `submit_final_answer(text)` — terminator
- System prompt enforces "verify before stating" (BCQT pattern).

**Critical: ACL on every tool call.** Even though the agent's thread
is scoped to (user, client_id), tools must re-verify the user's
permission to view that client. Otherwise a stale token / lateral
escalation could leak data. Pattern:
```python
def dispatch_tool(*, user, client_id, tool_name, args):
    auth.require_can_view_client(user, client_id)  # raises 403
    return TOOLS[tool_name](client_id=client_id, **args)
```

**Skip:** Anthropic-specific prompt caching. Hardcoded
`MAX_ROUNDS=10, MAX_TOOL_CALLS=50` — calibrate from production
metrics.

**Watch-out (BCQT learned):**
- Test stubs must mirror runtime contract fully. First test stub
  inserted only assistant message; real `run_agent_turn` inserts
  user message FIRST. Diverging stubs hid bugs.
- SDK response object attribute names are fragile across versions —
  pin attributes to the ones actually used; document the assumption.

## Order of build for Sprint B

1. **B1 — Notifications** (~2h). Smallest, isolated. Useful soon.
2. **B2 — Chat-agent** (~2-3h). Builds on RBAC + LLM infra. Higher-value.
3. **B3 — SSO** (~2h, design-heavy). M9 deliverable; foundational for
   BCQT/CO consumers but no consumers exist yet → light implementation
   bias toward design + JWKS endpoint stub.
