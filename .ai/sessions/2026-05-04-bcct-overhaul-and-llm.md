# Session: 2026-05-04 — BCCT overhaul + LLM smart parser

User asked to drive 4 features in one bundle through the full
discover → critic → synthesize → plan → TDD → UI test → /rev → manual
test cycle. Five commits, ~3000 LoC, 40 → 106 tests.

## Stages

### A+B: 12 CO columns + year derived (commit `365bfed`)
- Migration 010: 12 typed columns added; back-fill from existing payload
  jsonb (5119 historical rows touched, 100% coverage where source had the
  field). Year column dropped + re-added as `GENERATED ALWAYS AS
  (EXTRACT(YEAR FROM registration_date))::int STORED`. PK rebuilt; 5
  covering indexes recreated.
- Parser extended with 14 new logical fields (12 CO + invoice_date +
  departure_date) + Vietnamese aliases. Reordered some existing aliases
  (đơn vị tính > đvt; tổng số lượng 2 > số lượng 2; mã hs > hs; stt
  hàng > stt) — was matching wrong column on real Vietnamese files.
- Route drops `year` Form param; pre-filters rows missing
  registration_date (would violate generated NOT NULL).
- Read API surfaces all 14 fields. Verified: real DKE row → exporter_name,
  consignee_name, incoterms='CIP', weight=158.2, exchange_rate=26089.

### D: LLM-driven smart parser (commit `175d1f8`)
- Migration 012: `hub.app_settings`, `hub.parser_mappings` (keyed by
  client_id+module+file_signature with `confirmed_by/confirmed_at`),
  `hub.llm_usage` (per-(date,client_id) budget).
- `app/settings_store.py`: mirrors BCQT-System pattern. get/set/get_int/
  get_float with constant fallback.
- `app/llm.py`: OpenAI-compat client. `LLMConfig.load()` →
  `propose_header_mapping(client_id, module, headers, sample_rows)`. Cell
  strings truncated to 100 chars; structured JSON output validated against
  the module's known logical fields; unknown fields/headers dropped
  (defends against hallucination).
- `compute_file_signature(client_id, module, headers_per_sheet)` — sha256
  over normalized+sorted headers per sheet, with client_id and module in
  the hash so cross-client cache poisoning is impossible.
- `parse_bcct_workbook(blob, mapping_override=...)` accepts an explicit
  header→logical_field mapping, bypassing alias matching.
- BCCT upload flow: cache lookup → rigid parse → LLM propose → stash in
  `file_uploads.result` with parse_status='proposed_mapping' → preview UI
  → staff confirm → save to parser_mappings.
- `/admin/settings/technical` (dev-only) UI for LLM keys.

### C1: Confirm-on-update gate (commit `b3a59d6`)
- Migration 013: `hub.upload_pending` (parsed_rows + diff_summary jsonb,
  24h TTL), `hub.bcct_row_history` (append-only audit), AFTER UPDATE/DELETE
  trigger reading `current_setting('app.user_id', true)` for changed_by
  (sentinel 'system' when unset; filters out no-change updates so
  ON CONFLICT DO UPDATE noops don't pollute history).
- `app/database.py:connect(user_id=...)` sets the GUC via `set_config()`
  for audit attribution. Plumbed through every write path.
- `_classify_rows`: NEW / NOOP / DIFF / ORPHAN. Orphans scoped to
  declarations in upload (per critic — partial re-upload of one
  declaration shouldn't soft-delete others).
- Preview UI: counts + diff table (old vs new per changed field) + per-
  category confirm checkbox.
- Single-use pending_id: DELETE...RETURNING in same tx as load.

### C2: History page + ops escape hatch (commit `91d2ca7`)
- `GET /clients/{id}/bcct/history/{txn_key}/{line_no}`: chronological
  audit-log view with old vs new per changed field, actor, upload_id.
- `scripts/bcct_force_apply.py`: dev CLI that bypasses the route confirm
  gate. Sets `app.user_id='ops:script'` GUC so the audit trigger captures
  the bypass actor (rather than 'system').

### Post-/rev fixes (commit `1d79247`)
Three critical findings from the /rev pass:

1. **Data-loss bug** — confirm path was re-classifying rows after
   filtering out unconfirmed DIFFs. The dropped DIFF rows became new
   ORPHANs in the re-classification, and `confirm_orphans=True` would
   DELETE them. **Fix:** apply the stashed `diff_summary` directly,
   without re-classification. New regression test
   `test_confirm_orphans_only_does_not_delete_unconfirmed_diff_rows`.

2. **Two separate transactions** in `_apply_bcct_rows` — insert and
   orphan-delete each opened their own connection. Docstring said "all in
   one txn" but wasn't. **Fix:** refactored `_insert_bcct` →
   `_insert_bcct_with_cursor` (cursor-accepting); `_apply_bcct_rows`
   opens one connection, runs both on the same cursor.

3. **API-key leak risk** — `HTTPException(400, f"...: {e}")` echoed raw
   OpenAI SDK exception to the browser; some transport errors include
   the request URL with the Authorization header. **Fix:** log full
   exception server-side, surface only exception class name + generic
   message to user.

## What didn't work / Surprises

- **`SET app.user_id = $1` fails** — psycopg can't parameterize SET. Used
  `SELECT set_config('app.user_id', %s, false)` instead.
- **Preview UI 500'd on first attempt** — included
  `clients/_client_nav.html` instead of `_client_nav.html`. Fixed.
- **Unique-violation in seed-row helper** for the regression test — my
  helper made `transaction_key` from `declaration_no` only, so 4 calls
  with same decl_no but different line_no all collided. Fix: use
  distinct decl_nos.
- **PK rebuild mid-migration** — Postgres requires DROP CONSTRAINT before
  DROP COLUMN year (since year is in PK). Then ADD COLUMN year
  GENERATED. Then ADD PRIMARY KEY back. Then recreate the 5 covering
  indexes that were auto-dropped with the column.
- **Generated column NOT NULL** — Postgres rejects `registration_date IS
  NULL` rows; pre-flight DO block in migration verifies 0 such rows
  exist before proceeding.

## How to resume

```bash
cd ~/workspace/client/data-hub
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload
# Login: admin@data-hub.local / admin123 (role=dev)

# Tests
uv run pytest -q                  # 99 passed locally (+ real-data env-gated)
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q   # 106 passed

# LLM smoke test (when API key configured):
# 1. /admin/settings/technical → set base_url, model, api_key
# 2. Upload a BCCT file with weird/Chinese headers
# 3. Should redirect to /clients/{id}/bcct/parse-mapping/{upload_id}

# Confirm-gate smoke test:
# 1. Upload a BCCT file
# 2. Re-upload the same file with one row's quantity changed
# 3. Should redirect to /clients/{id}/bcct/upload/preview/{pending_id}
# 4. Tick "confirm overwrite" → row updated; audit log captures change

# History view: /clients/{id}/bcct/history/{transaction_key}/{line_no}

# Ops bypass:
uv run python scripts/bcct_force_apply.py --client growatt-vn \
  --file /path/to/file.xls --dry-run
uv run python scripts/bcct_force_apply.py --client growatt-vn \
  --file /path/to/file.xls --confirm-orphans
```

## Open follow-ups (rolled forward)

- **/rev "Important" findings #4-7** — minor: cache use_count overcounts
  on rigid-fallback; FileNotFoundError in stored_path read; bcct_history
  link not surfaced from BCCT row table; migration 011 numbering gap.
- **Manual mapping UI** — when LLM is disabled, user can't manually map
  unknown headers; today the upload just errors. Add a "Manual mapping"
  link on the parser-mapping preview when LLM is unavailable.
- **Apply confirm-gate pattern to catalog/bqd/bom uploads** — currently
  only BCCT has the pre-flight diff. Other modules go through the old
  flow (catalog status normalization etc.).
- **CSRF protection** — pre-existing project gap, not blocking.
- **Connection pooling** — when introduced, switch
  `set_config('app.user_id', ..., false)` → `true` (LOCAL) or wrap in
  explicit BEGIN.
