# Feature: BCCT correctness overhaul + LLM-driven smart parser fallback

**Status:** discover + critic done 2026-05-04. Sequencing revised per critic.

Bundled work landing 4 changes in one sprint:

1. **Promote 12 CO-essential BCCT columns from jsonb to typed.**
2. **Drop `year` form field; derive per-row from `registration_date`.**
3. **Confirm-on-update gate** (Phase 1: hard-stop preview; Phase 2: per-row diff UI; Phase 3: audit log).
4. **LLM-driven smart parser fallback** with user-confirm + cached mapping (settings live in a new "Technical settings" admin page; pattern referenced from `~/workspace/client/BCQT-System/app/settings_store.py` + `app/pipeline/user_checks.py`).

## Scope

### In

**Promote columns** (added to `hub.bcct_rows`):
- `exporter_name`, `exporter_tax_code` ← Tên/Mã doanh nghiệp
- `consignee_name` ← Tên đối tác
- `incoterms` ← Điều kiện giá hóa đơn
- `weight`, `weight_unit` ← Trọng lượng + Mã ĐVT trọng lượng
- `package_count`, `package_unit` ← Số lượng kiện + Mã ĐVT kiện
- `invoice_date` ← Ngày hóa đơn
- `departure_date` ← Ngày khởi hành vận chuyển
- `destination_code`, `destination_name` ← Mã/Tên địa điểm đích
- `transport_mode` ← Mã hiệu PTVC
- `exchange_rate` ← Tỷ giá thanh toán

Parser populates from payload aliases; ON CONFLICT update list extended; read API surfaces them. `payload` jsonb stays (catch-all).

**Year derivation**: drop `year` Form field on POST `/clients/{id}/bcct/upload`. Parser already sets `registration_date` per row. Insert path uses `EXTRACT(YEAR FROM registration_date)`. Rows with NULL `registration_date` → reject row with surfaced error in the upload preview. View (`GET /clients/{id}/bcct`) keeps `year` as optional query filter (back-compatible).

**Confirm-on-update gate (Phase 1)**:
- Pre-flight: parse file, compute key per row `(client_id, year_from_date, transaction_key, line_no)`, look up existing rows in DB.
- Categorise: NEW / NOOP / DIFF / ORPHAN (orphans = rows in DB whose declaration_no appears in upload but with line_no missing from upload).
- If any DIFF or ORPHAN: stash parsed rows in a `hub.upload_pending` table (parsed jsonb + meta), redirect to preview page.
- Preview shows counts + diff table (existing vs new values for DIFF rows, list for ORPHAN). Confirm button submits with `pending_id`.
- On confirm: apply changes (UPDATE for confirmed DIFF, soft-delete for confirmed ORPHAN, INSERT for NEW), purge pending row.
- On cancel: purge pending row, no DB change.

**Phase 2 (per-row diff UI)**: add per-row checkbox so staff can opt out of specific changes. Default = all checked. Out-of-scope rows revert to prior values (NOOP).

**Phase 3 (audit log)**: `hub.bcct_row_history` table — old jsonb, new jsonb, action (insert/update/delete), upload_id, changed_by, changed_at. Trigger on AFTER UPDATE/DELETE. New tab `Lịch sử` per BCCT row drilling history.

**LLM-driven smart parser fallback**:
- New table `hub.app_settings(key, value, updated_at, updated_by)` — global key-value (single agency = single tenant for now).
- New module `app/llm.py` exposing `LLMConfig.load()` + `propose_header_mapping(headers, sample_rows, target_fields)` calling the OpenAI-compat client.
- Settings UI `/admin/settings/technical` — dev-only, edits LLM keys (`llm_base_url`, `llm_model`, `llm_temperature`, `llm_max_retries`, `llm_timeout_s`, `llm_api_key`). Mirror BCQT pattern.
- New table `hub.parser_mappings(client_id, module, file_signature, mapping jsonb, confirmed_by, confirmed_at)`. `file_signature = sha256(sorted normalized headers ; sheet names)`.
- Upload flow change: rigid parse first. If `*ParseError` → compute file_signature → look up mapping. If hit, parse with mapping. If miss, call LLM, propose mapping → preview UI → staff confirms → save mapping + parse.
- LLM cost guard: `llm_max_calls_per_day` setting; reject calls beyond budget with clear UX.
- Prompt-injection guard: only headers + 5 truncated sample rows sent (cell strings clipped to 100 chars, no raw user content); structured JSON tool-call output (Anthropic-shape via OpenAI tool_use), schema-validated.

### Out

- Multi-LLM provider switching at runtime (just OpenAI-compat for now; Anthropic users point at their own gateway via OpenAI-compat shim).
- Auto-generation of permanent Python parser code (Phase 4 / future).
- Streaming LLM responses (single-shot only).
- BCQT/CO consumer schema update notifications (cross-repo coordination separate session).
- Generic header-matcher upgrades beyond what's already in `_excel.py:index_headers` two-pass.

### In (added per critic)

- **Back-fill 12 promoted columns from existing `hub.bcct_rows.payload`.** One-shot `UPDATE ... FROM payload` in migration 010. Without it, historical rows return NULL on the new typed columns, degrading API for CO consumers later. Critic: "false economy."

## Decisions

1. **Year via Postgres `GENERATED ALWAYS AS (EXTRACT(YEAR FROM registration_date)::int) STORED`.** Critic-revised from "trigger or computed column" → STORED generated column. Reasons: atomic, no procedural code, no audit-log feedback loop, indexable. PG12+ supports `EXTRACT` as IMMUTABLE → can be in PK. Migration 011 must DROP the old PK + ALTER column to add GENERATED + recreate PK + recreate covering indexes. Hot-table ALTER cost flagged in Risks.

2. **Pending-upload state in DB, not session.** `hub.upload_pending(pending_id pk, client_id, module, content_sha256, parsed_rows jsonb, summary jsonb, file_upload_id fk, created_at, expires_at default now()+24h)`. Cron purge runs hourly; deletes the `file_uploads` blob too if no other reference (critic: "Cross-table TTL").

3. **Audit log via Postgres trigger + session GUC `app.user_id`.** Trigger reads `current_setting('app.user_id', true)` for `changed_by`. App contract: every connection used for writes calls `SET LOCAL app.user_id = '<user_id>'` at txn start; default empty string sentinel = `'system'`. Without GUC, audit log is useless (critic: "Specify the GUC contract now"). Plumb in `app.database.connect()` as a context-manager param.

4. **LLM via OpenAI-compat (not native Anthropic SDK).** Mirrors BCQT pattern. Anthropic API has OpenAI-compat shim. Lets the same settings drive Anthropic, OpenAI, vLLM, llama.cpp, Ollama, OpenRouter.

5. **Settings stored in `hub.app_settings`, not env vars.** Single-tenant trusted-admin model.

6. **LLM only on rigid-parse failure, not always.** Cheap, fast, deterministic for known shapes. Cache by `file_signature = sha256(client_id + module + sorted_normalized_headers + sheet_count)`. Critic: signature must be client-scoped (`client_id` in the hash AND in the `parser_mappings` PK) to prevent cross-client cache poisoning when two agencies happen to have similar headers.

7. **Confirm-gate is unbypassable from the route. Sanctioned escape hatch = `scripts/bcct_force_apply.py` CLI** (writes directly with `changed_by='ops:script'` via the GUC, leaves an audit trail). Critic: "don't add ?force=1; add CLI bypass". This protects ops/data-fix work without giving non-developers a footgun.

8. **LLM cost budget per-`(date, client_id)`** (not global). Critic: "one rogue agency exhausts budget for everyone".

9. **Confirm submit is idempotent via single-use `pending_id`** — DELETE pending row + apply changes in same txn (`DELETE ... RETURNING parsed_rows`). Double-click → second click sees no row → 404 / "already applied" message.

## Risks

1. **Migration cost on populated `bcct_rows`.** Column adds are O(1) (no defaults, PG11+). BUT (a) the year-PK reconstruction in migration 011 requires DROP CONSTRAINT + ALTER COLUMN + ADD CONSTRAINT — full rewrite of the PK btree on a 5K+ row table = seconds, on a 200K+ row table = minutes. (b) Index updates on the 12 new columns aren't O(1) — explicit `CREATE INDEX CONCURRENTLY` outside any txn. Run during low-traffic window; document procedure in migration header.

2. **LLM hallucination → wrong mapping → silent corruption.** Mitigated by:
   - Mandatory user confirm before mapping is saved
   - Preview shows 5 fully-parsed sample rows with the proposed mapping (visual sanity check)
   - LLM output schema-validated; if missing required fields the staff sees "LLM couldn't propose a complete mapping; please use manual mapping" not auto-application

3. **Prompt injection via uploaded Excel cells.** A malicious Excel could embed `Ignore previous instructions...` in a cell. Mitigation: only headers + truncated samples sent, cell strings escaped, response is tool-call JSON (not free-text), no system-prompt-bypass tokens.

4. **Pending-upload race**: two staff uploading the same file simultaneously could both create pending rows. Idempotency via `(client_id, module, content_sha256)` unique constraint; second upload returns "already pending — view here".

5. **Schema migration breaks BCQT/CO read API consumers.** They don't exist yet (BCQT/CO not migrated). Safe today, must coordinate when they migrate.

6. **Confirm-flow disrupts current "fire-and-forget" UX.** Staff used to single-click upload now hits preview. Fix: NEW-only uploads (no DIFF/ORPHAN) skip the preview entirely — direct apply with toast "X rows added".

7. **LLM unavailable at upload time.** Settings page shows LLM enabled but call fails (timeout, key revoked). Behavior: show error in preview, let staff bypass with a manual-mapping option (Phase 4 — for now, just error message and ask staff to add manual aliases via dev request).

## Open Questions

1. **For ORPHAN detection scope**: do orphans include all rows for declarations mentioned in upload, OR all rows for the date range covered by upload? Current proposal = same declaration_no. Risk: a partial re-upload (just one declaration to amend) shouldn't soft-delete the rest of the year. Spec firmly: orphans only within `(declaration_no)` keys present in the upload.

2. **Phase 3 audit log retention**: indefinite, or N years? TT 39/2018 says 5-10 years for compliance docs. Default = indefinite + manual purge tool. Confirm with user before merge.

3. **LLM mapping cache invalidation**: if agency changes their export template, file_signature changes → cache miss → LLM re-proposes. But what if agency *means* same fields with new headers? No automatic detection — staff must approve again. Acceptable.

4. **Settings page route placement**: under `/admin/settings/technical` (dev-only) vs nested under existing `/admin/users` page. Decision: separate page; users + LLM settings shouldn't share UI surface.

5. **CO consumer integration**: when CO migrates, does it want the 12 promoted columns surfaced in `/v1/hub/bcct/{transaction_key}` OR a new `/v1/hub/bcct/{transaction_key}/full` returning all + payload? Default = include in main response (12 columns is small, not bloating). Confirm post-build.

## Sequencing (revised post-critic)

**A+B → D → C1 → C2.** Critic recommendation: ship parsing wins first (real user value), defer the largest UX-heavy work until last.

- **A+B. Promote 12 columns + year-derive** (migrations 010 + 011 merged, parser populates new fields, route drops year form, view back-compat, BACK-FILL of historical rows from payload): ~1 day.
- **D. LLM smart parser** (migration 012 = `app_settings` + `parser_mappings`, `app/llm.py`, `app/settings_store.py`, `/admin/settings/technical` UI, parser-fallback flow with mapping cache, propose-and-confirm UI): ~1.5 days. Independent of C; unblocks parsing of files currently rejected.
- **C1. Confirm-gate Phase 1+2** (migration 013 = `upload_pending`, `bcct_row_history` + trigger + GUC plumb, preview UI, per-row diff): ~1.5 days.
- **C2. Audit log surface** (migration 014 if needed for indexes; `Lịch sử` tab per BCCT row; admin-CLI bypass script `scripts/bcct_force_apply.py`): ~0.5 day.

Total ~4-4.5 days. Each merges independently. Each ships behind a `/discover→/tdd→/rev` cycle.

## Files to touch (by phase)

**A+B (CO columns + year-derive):**
- `db/migrations/010_bcct_co_columns_and_year.sql` (new) — 12 columns + back-fill from payload + drop PK + alter year to GENERATED + add PK back + recreate covering indexes CONCURRENTLY
- `app/parsers/bcct.py` — alias map + populate 12 new fields from payload
- `app/routes/bcct.py` — drop year Form (year now derived in DB)
- `app/routes/api.py` — extend `/v1/hub/bcct/*` response with 12 new fields
- `tests/test_co_columns.py` (new) — TDD: column populated end-to-end + back-fill

**D (LLM smart parser):**
- `db/migrations/012_llm_and_mappings.sql` (new) — `hub.app_settings`, `hub.parser_mappings`, `hub.llm_usage` (per `(date, client_id)` budget tracking)
- `app/settings_store.py` (new) — read-through with constant fallback
- `app/llm.py` (new) — OpenAI-compat client + `propose_header_mapping(headers, sample_rows, target_fields)`
- `app/routes/admin.py` — add `/admin/settings/technical` (dev-only)
- `app/templates/admin/settings_technical.html` (new)
- `app/parsers/_excel.py` — `compute_file_signature(headers, sheet_count, client_id, module)`
- `app/routes/bcct.py` (and catalog/bom/bqd later) — rigid-parse-then-LLM-fallback, mapping cache lookup
- `app/templates/clients/parser_mapping_propose.html` (new) — propose UI with sample preview
- `tests/test_llm_mapping.py` (new) — TDD with mocked LLM responses

**C1 (confirm-gate Phase 1+2):**
- `db/migrations/013_confirm_gate.sql` (new) — `hub.upload_pending(... expires_at)`, `hub.bcct_row_history`, AFTER UPDATE/DELETE trigger reading `app.user_id` GUC, hourly cron-purge SQL function
- `app/database.py` — `connect(*, user_id=None)` sets `app.user_id` GUC at txn start
- `app/routes/bcct.py` — pre-flight diff, redirect to preview, confirm endpoint
- `app/templates/clients/bcct_upload_preview.html` (new) — diff table with checkboxes
- `tests/test_bcct_confirm_flow.py` (new) — TDD: NEW-only skips preview, DIFF triggers preview, ORPHAN detection, idempotent confirm

**C2 (audit surface + escape hatch):**
- `app/routes/bcct.py` — `Lịch sử` tab per row
- `app/templates/clients/bcct_history.html` (new)
- `scripts/bcct_force_apply.py` (new) — CLI bypass with synthetic audit
- `tests/test_bcct_history.py` (new)

**Cross-cutting:**
- `tests/fixtures/edge_cases/_generate.py` — add fixtures for staff-amended TKHQ + orphan scenario + LLM-fallback (Chinese / unknown headers)

## Suggested next step

`/tdd` for stage A+B first. Write tests → migration → parser → route. Verify via UI screenshot. `/rev` stage A+B before moving on. Then D, then C1, then C2.
