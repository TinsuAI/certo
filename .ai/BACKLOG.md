# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

---

## UI BOM upload — wire up v3 concepts

**Captured 2026-05-05** after session shipped v3 schema (raw_graph /
shallow / full_flat shapes), supplier-batch ingest scripts, BTP
roster, and provenance UI on BOM list/detail pages. The upload route
itself (`app/routes/bom.py`) was not updated; it still uses the
unified-mapping-flow from commit `b278ff5` and treats every upload
as `bom_variant_id='default'` with no post-upload hooks.

**Gaps to close:**

1. **`bom_variant_id` field in upload form** — staff should pick a
   batch label (e.g. `agency_2026-05-05` or freetext) when uploading
   multiple supplier batches per product. Auto-derive default from
   filename or upload date if blank. Without this, multi-batch
   uploads via UI collide on `(product_code, default)` and trigger
   version-bump idempotency dedup.
2. **Auto-materialize post-upload** — when `technical_raw` confirms,
   trigger `materialize_shallow_and_full_flat` for the new
   `bom_versions` row inline (or async). Without this, shallow +
   full_flat versions only exist after a manual script run, which
   leaves the freshly-uploaded raw_graph orphan from BCQT/CO consumer
   queries.
3. **Auto-bootstrap BTP roster** — same trigger should re-run BTP
   detection (rule: parent_code in bom_edges + not a tp_root).
   Catalog `btp_sx` entries for newly-introduced intermediate codes
   land without a separate command.
4. **Shape badge in preview** — preview page currently shows flat
   rows. Add a header banner showing "This upload will create a
   `raw_graph` BOM" / "`shallow`" / "`full_flat`" so staff confirm
   with intent. Use the `bom_shape()` helper.
5. **Multi-role warning** — if any code in the upload also appears
   in `bcct_rows.direction='export'` for this client AND the upload
   would categorize the code as `btp_sx`, surface a warning: "Code
   PV01.0104300 has been exported in BCCT — adding it as BTP here
   creates a multi-role situation. Confirm intent." Reference
   `project_bom_code_multirole.md` memory for context.
6. **Per-client policy gate** — `clients.auto_derive_shallow_from_raw`
   (`disabled` / `draft_only` / `publish`) should gate auto-materialize
   step. UI upload should respect the value: in `draft_only`, derived
   shallow/full_flat insert as `status='draft'` not `published`.
7. **Tests + docs** — Playwright E2E that drives upload → mapping →
   parse → preview → confirm and asserts shape + materialize side
   effects. Unit tests for the new auto-trigger functions.

**Why deferred to Phase 3 / a dedicated session:**

The UI integration naturally couples with Phase 3 resolver +
profiles work — both need shape-aware UX, and shipping them
together avoids two rounds of UI churn. Pre-MVP scope is covered by
direct-ingest scripts (`scripts/ingest_technical_raw_batch.py`,
`scripts/ingest_curated_xlsx_direct.py`) + manual UI for ad-hoc
single uploads, which is acceptable until first real customer.

Estimated effort: 4-6h for items 1-5, +2-3h for tests + docs (item 7).

---

## Aggregate-data git-history

**Captured 2026-05-05** as a hard product principle from user.

**Principle (already enforced for BOMs, generalize to other aggregates):**

- Never physically `DELETE` rows from any aggregate-data table (BOMs,
  materials, code_mappings, client_config, parser_mappings, etc.).
- Edits = INSERT a new version with lineage back to the previous one.
- "Removal" is via tombstone / deactivation flag on the row, not row
  deletion.
- All aggregate data must support **git-like history**: who added what,
  who removed what, when, with revert / undo capability.

**Current state (HEAD as of 2026-05-05):**

| Table | History tracking | Gap |
|---|---|---|
| `bom_versions` + children | ✅ tombstone + parent_version_id lineage (mig 006/029) | Uses migration 027 cleanup pattern. Already conformant. |
| `bcct_rows` | ✅ `bcct_row_history` audit table + AFTER UPDATE/DELETE trigger (mig 013) | OK, but no UI for revert. |
| `materials` | ⚠️ `provenance` jsonb merge-on-conflict only | No history table. UPDATE overwrites name/category/unit/etc. |
| `code_mappings` | ❌ Plain table, UPDATE in place. | No history. |
| `client_config`, `parser_mappings`, `bom_flatten_decisions`, `client_uom_overrides`, `client_type_presets` | ❌ Plain tables. | No history. |
| `clients`, `users` | ❌ Plain tables. | No history (probably OK for users, debatable for clients). |

**Work units (each its own PR):**

1. **`materials_history` audit table + trigger** mirroring the
   `bcct_row_history` pattern. Capture full row before any UPDATE
   or DELETE, with `changed_at`, `changed_by` (read from
   `app.user_id` GUC), `change_kind ∈ {insert, update, delete}`.
2. **`code_mappings_history`** same pattern.
3. **`client_config_history`** + **`parser_mappings_history`** same.
4. **`/v1/hub/{table}/{key}/history` endpoints** — paginated audit
   timeline per entity.
5. **`/v1/hub/{table}/{key}/revert?to=<changed_at>`** — revert one
   row to a prior state. Implemented as INSERT-from-history (still
   append-only); audit captures it as a new change with
   `change_kind='revert'`.
6. **UI: history page per entity.** Reuse `bcct_row_history` page
   pattern. Diff view showing what changed.
7. **Document the "no DELETE" rule in `AGENTS.md` + standards repo.**
   Add a CI lint that scans for `DELETE FROM hub.<aggregate-table>`
   and fails on match unless explicitly tagged
   `-- ALLOW-DELETE: <reason>`.

**Why this matters:**

- Customs audit (TT 39/2018) requires 5-10 year retention of source
  data underlying settlement / origin certificates.
- Disputes between agency and customs auditor often hinge on "which
  version of the catalog/BOM/mapping was active when this transaction
  was filed?" — without history, the answer is "current state"
  which may not be the truth-of-record.
- Staff confidence: undo / revert lowers the cost of accidental
  destructive edits, which lowers the activation energy for staff
  to actually fix bad data.

**Out of scope for this backlog item:**

- BOM versioning is already done — don't redo it. The new history
  tables are for non-BOM aggregates.
- Operational tables (sessions, llm_usage, notifications,
  upload_pending) don't need this — they're transient.

---

## Sprint D — parser/data architectural follow-ups (post-Sprints A/B/C)

**Captured 2026-05-03 PM** after Sprints A/B/C closed the immediate
correctness gaps. Each item below is its own PR (per plan-review
critic: "uncoupled changes — don't bundle"). No fixed order; ship in
parallel as bandwidth allows.

- **D1: `hub.declaration_types` lookup table.** Replace the hardcoded
  `IMPORT_TYPES` / `EXPORT_TYPES` Python sets in `app/parsers/bcct.py`
  with a DB-seeded table sourced from Decision 1357/QĐ-TCHQ. Direction
  becomes a SQL JOIN; future schedule revisions are a seed-INSERT
  migration not a code release.

- **D2: `transaction_key` GENERATED ALWAYS AS column.** Make
  `transaction_key = '{declaration_no}-{line_no}'` a stored generated
  column on `hub.bcct_rows` so the invariant cannot drift. Migration
  touches every BCCT insert path; ship as its own PR.

- **D3: `normalized_hash` Decimal end-to-end + dual-version migration.**
  `app/stores/bom.py:normalized_hash` currently does
  `round(float(...), 9)` — float arithmetic drift undermines
  idempotency. Switching to Decimal changes every existing version's
  hash. Need a phase-in plan: compute v2 hash on writes, store both
  v1 + v2 during transition, dual-check on insert until backfill.

- **D4: Idempotency canonical-projection re-design.** Critic flagged
  that re-uploading the same Excel after fixing an unrelated catalog
  row currently silently dedup's because `normalized_hash` doesn't
  cover the upload-context dimension. Discovery doc first, then
  decide: log audit event on dedup-hit, OR widen the canonical
  projection, OR both.

- **D5: SAP indented-walk level-skip handling.** Reject (or pad with
  sentinel parents) BOM workbooks where indent levels skip
  non-contiguously (e.g. L2 → L4 missing L3). Need a real Johnson SAP
  sample exhibiting the case to reproduce — fixture
  `johnson_sap_english_headers.xlsx` may already cover it; verify
  before writing speculative code.

- **D6: BOM idempotency unique index audit.** Same
  uq_bom_idempotent_v2 design — verify the (`actor`, `intent`)
  column tuple is the right granularity vs upload identity.

- **D7: Fixture-pinned regression test for BOM-vs-CO compare.**
  Replace the gitignored `data/screenshots/_compare_report.md` with
  `tests/regression/test_real_bom_compare.py` env-gated, pinning
  per-file leaf-set match thresholds against checked-in fixture
  corpus.

- **D8: Cross-table `hub.integrity_findings` materialized view.**
  Surface every catalog-vs-BOM-vs-BCCT inconsistency in one place
  (orphan BTP_SX, UOM mismatches, ghost codes, etc.). Defer until 3+
  consumers want the same data — currently the per-page badges from
  Sprint B cover MVP need.

- **D9: `bcct_rows.bom_version_id` point-of-use binding.** Already
  designed in `.ai/features/2026-04-30-data-hub-mvp.md` (BCQT-side).
  Implement when BCQT migration sprint lands.

---

## CO + BCQT — adopt service-account JWTs

**Captured 2026-05-02 PM.** Ship-blocking dependency for "API auth strict
promotion" below. No hard deadline — coexistence works fine.

Service-account JWTs are live in Data Hub (migration 020 + CLI). Sister
apps still call with permissive bearer / user JWT. To adopt:

1. **Mint tokens** (Data Hub admin):
   ```bash
   uv run python scripts/mint_service_token.py create \
     --name co --scopes hub:read,bom:propose \
     --client-ids growatt-vn,dke-vietnam-d0e3,johnson-vn,do-thanh-vietnam-2614 \
     --created-by <admin-email>

   uv run python scripts/mint_service_token.py create \
     --name bcqt --scopes hub:read \
     --created-by <admin-email>
   ```
2. **CO repo** (`barry-CO-main`): inject `DATA_HUB_SERVICE_TOKEN` env
   into `app/data_hub_client.py` Bearer header on every call. If CO
   verifies tokens locally, branch on `claims["typ"] == "service"` —
   service tokens have no email/role/name; `sub` is `svc:co`.
3. **BCQT repo**: same pattern, `hub:read` scope only.

Full instructions: `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`.
Design rationale: `.ai/features/2026-05-02-service-account-jwts.md`.

**Pull this out of backlog when:** ready to coordinate the sister-repo
PRs, or when about to flip `api_auth_strict=true` (then it becomes
ship-blocking).

---

## API auth — flip dev-permissive reads to strict by default

**Captured 2026-05-02.** **Unblocked 2026-05-02 PM** — service-account
JWTs shipped (migration 020). Now waiting on sister-app cutover (item
above).

Today the read API on `/v1/hub/*` accepts non-empty legacy bearer strings
when `api_auth_strict=false` (default). Writes (BOM proposal POST) always
require a valid Data Hub JWT regardless of the flag. The trade-off was
chosen deliberately: prioritize dev/integration ergonomics today,
prioritize corruption prevention on writes.

**Promote when:**
- CO and BCQT have switched to service-account JWTs (per
  `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`).
- We have a staging environment where strict mode can be soak-tested
  before flipping prod.

**Steps when promoting:**
1. Default `api_auth_strict=true` in fresh installs; add a one-time
   migration to flip existing installs after CO/BCQT confirm readiness.
2. Remove the legacy bearer fallback path in `_require_token`; keep only
   the JWT validation branch.
3. Update `docs/API_CONTRACT.md` to drop the dev-permissive mode section.
4. Update CO/BCQT consumer code to send real JWT on every read call.

---

## Manual mapping UI when LLM disabled

When LLM is unavailable AND a file fails rigid parse, the upload errors
with no recovery besides edit-in-DB. Add a "Manual mapping" link on the
parser-mapping preview when LLM is unavailable, surfacing the same
header→logical-field grid the LLM-confirmed flow uses. Reuses
`parser_mappings` cache once confirmed.

---

## BOM/BQD/Catalog parse-error UX

**Partial.** Phase 2 universal preview-confirm pattern surfaces parsed
rows nicely when parsing succeeds. But when the parser rejects the file
outright (no LLM available, or LLM also fails), `app/routes/bom.py:145`
still raises `HTTPException(400, ...)` which the browser renders as raw
FastAPI JSON `{"detail": "..."}`.

Compare BCCT's `parse-mapping` error path which renders a proper
template with recovery options.

**Fix:** catch the final parse-error path and render an error template
or redirect with a `?error=...` toast (matching the post-upload toast
pattern from `c77da85`).

---

## /rev cross-cuts (still open)

- **CSRF protection** on POST endpoints (pre-existing project gap).
- **`set_config('app.user_id', ..., false)`** — switch to `true`
  (LOCAL) if connection pooling lands. Today every `connect(user_id=...)`
  call gets a fresh connection, so SESSION-scoped GUC is fine.
- **Migration numbering gap** (010 → 012, no 011) — cosmetic; renaming
  applied migrations would diverge `schema_migrations` rows across
  environments.

---

## Notes

The previously-tracked items below have all shipped (verified in HEAD as
of 2026-05-02 PM):

- Pre-commit upload preview at all stages → `359ebec` Phase 2.
- Catalog multi-source provenance + auto-derive from BCCT → `6141d1e` A4.
- BCCT (and all 4 tab) staleness metadata → `53da49b` A3.
- Parser bugs A/B/C/D from 2026-05-02 real-data smoke → `338be91` Phase 1.
- BCCT confirm-on-update gate + history page → `b3a59d6` + `91d2ca7`.
- LLM smart parser → `175d1f8` (BCCT) + `5d44b60` (BOM/BQD).
- /rev cache `use_count` overcount + `Path(stored_path).read_bytes()`
  FileNotFoundError → `2e8cd05`.
- Apply confirm-gate pattern to catalog/bqd/bom (was a cross-cut from
  prior /rev) → `359ebec` Phase 2.
- Service-account JWTs → migration 020, `app/jwt_issuer.py:make_service_token`,
  `scripts/mint_service_token.py`, `tests/test_service_account_jwts.py`
  (13 new tests, 232 total).

These were removed from this file on 2026-05-02 PM. See git history of
`.ai/BACKLOG.md` for the original entries.
