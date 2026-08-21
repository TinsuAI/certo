# 2026-05-28 PM — CO API trio + quality cleanup

Closed 3 CO API requests (all dated 2026-05-28) plus a sequence of
quality fixes (password docs, conftest robustness, CI badge, a
backlog item). 8 commits, 22 files, +2,198 / -114 lines. Suite went
from 1,175 (stale baseline) → 1,263 passing.

Branch ended at `316ec57`, demo + dev in sync.

## What Was Done

### Quality fixes (early session)

1. **Admin password docs drift fix** (`e7192ed`). User couldn't log
   in with `admin123` per `CLAUDE.md` / `README.md` — real seed in
   `.env` is `local_test_password`. Updated both docs (CLAUDE.md is
   a symlink to AGENTS.md). 3 references corrected.

2. **Conftest force-reset** (`a16202b`). 5 "pre-existing failures"
   flagged in STATUS.md were the visible tip of a wider iceberg.
   `tests/conftest.py:30` called `auth.seed_admin_if_empty(...)`
   which no-ops when users exist. On a dev DB seeded by env
   `DATA_HUB_SEED_PASSWORD=local_test_password`, the test-expected
   `admin123` was never applied → all hardcoded-`admin123` tests
   401'd. Force-reset password + role in conftest's session
   bootstrap regardless of existing seed. Baseline 1,175 → 1,224.

3. **CI LLM smoke soft-fail** (`8072749`). `.github/workflows/ci-cd.yml`
   step `Smoke LLM /models (best effort)` used `bash -e` which
   propagated curl exit 22 (upstream `codex-lb-demo.sgnai.dev`
   returning 401). CI badge red on every push even when deploy +
   tests + API smoke all passed. Added `continue-on-error: true` +
   inline if-branch around curl.

### A.4.3 — goods_name bucketing

4. **Catalog drift bucketing** (`d595bbe`). Backlog item A.4.3.
   `app/stores/catalog_bcct_analysis.py` grouped goods_name drift by
   exact-equal value. Real Johnson data had many materials with 3-5
   "distinct" names differing only in whitespace runs, double comma,
   code prefix `<code>#&`, or casing — staff saw noise and stopped
   trusting the panel.

   Solution: `_normalize_goods_name()` (lowercase + strip Johnson
   `<code>#&` prefix + collapse punctuation runs) + `_bucket_by_normalized()`
   regroup `(value, count)` pairs by normalized key. Representative
   per bucket = most-frequent original. Wired into goods_name field
   only (other fields stay strict).

   Real-data smoke on top-10 Johnson per-product codes: 21% noise
   reduction, zero false collapses. +4 tests.

5. **A.4.3 feature folder + screenshots** (`2f3362e`). Captured
   before/after screenshots on Johnson `005485-E` (4 raw → 2 buckets)
   per `feedback_feature_folder_with_screenshots.md` convention.
   Screenshot capture pattern needed git revision swap (server
   running new code from prior commit; reverted file temporarily,
   restarted, captured "before", restored, restarted, captured
   "after"). Selector `table:has(.drift-row)` — `.dh-table` alone
   matched the wrong table at top of page.

### Three CO API requests

6. **BCCT incremental `since` + tombstones** (`ebedf86`). Request:
   `barry-CO-main/.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`.
   CO migrating `refresh_co_stock_for_client()` from DELETE+INSERT to
   diff-based; full-corpus pull (~65k Johnson rows, 8-10s) was the
   dominant cost. Speed win: a no-op refresh becomes sub-100ms.

   Added `since` (ISO-8601 UTC) + `include_tombstones` query params
   to `GET /v1/hub/bcct`. `WHERE indexed_at > since` filter
   (column already existed). Tombstones sourced from
   `hub.bcct_row_history` `action='delete'` (mig 013) — no new
   table, per [[feedback_reuse_audit_events]]. `server_time` always
   in response so callers use it as next call's `since` (gap-safe
   across multi-row clock ticks).

   Confirmed `transaction_key` stability for CO's diff design (was
   asked in the request): built as `f"{decl_no}-{line_no}"` when
   declaration_no is present (the normal case). Fallback only on
   empty decl_no. Documented in sister-app note. +9 tests.

7. **Declarations ZIP Bearer mirror** (`28ea610`). Request:
   `barry-CO-main/.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`.
   CO building consolidated dossier ZIP needs server-to-server
   access to declaration file bytes. Existing cookie route 303s
   Bearer callers.

   Mirror, not dual-auth on cookie route (per
   [[project_api_routing_convention]] — substitute API precedent
   2026-05-13). New `/v1/hub/clients/{cid}/declarations/download.zip`
   reuses helpers `_build_declarations_zip` / `_parse_zip_declaration_nos`
   / `_safe_archive_filename` from `app.routes.declarations`. 500-decl
   cap server-side on the mirror only; cookie route unchanged.
   +13 tests including service-token scope + whitelist.

   **End-to-end verified locally:** CO's `DataHubClient.download_declarations_zip()`
   → local Data Hub → 3 real Growatt XLS + manifest, 87 KB. Contract
   match 100%.

8. **BOM picker filter** (`316ec57`). Request:
   `barry-CO-main/.ai/api-requests/2026-05-28-bom-artifacts-active-flat-filter.md`.
   Biggest of the 3. CO picker leaks tombstoned/draft/foreign-case
   `modified_for_case`/non_flattened — operator could silently pick
   a stale or wrong-case BOM driving origin calculations.

   Added 5 new query params on `/v1/hub/products/{p}/bom/artifacts`:
   `intents`, `lifecycle`, `shape`, `latest_per_variant`, `case_id`.
   Defaults preserve raw-history back-compat (request's "Recommended"
   path — CO opts in to filter, admin/debug callers see no change).
   Response always carries `filter_applied` echo block so consumers
   detect server-side support.

   Filter logic Python-side over `list_artifacts_for_product()`
   output — typical product has <50 artifacts; SQL surgery not
   needed. Real-data smoke on Growatt `PV00.0047600`: 6 raw → 4
   selectable winners (2 variants × 2 strategies, dual-source case
   that `/bom/latest` 409s on). +13 tests.

## Decisions Made

1. **Mirror routes, not dual-auth retrofit** on cookie routes. Per
   memory [[project_api_routing_convention]] this was already the
   convention; today's declarations ZIP is another data point. The
   pattern: shared helpers in the module, separate route handler
   that picks its own auth.

2. **BOM picker defaults preserve back-compat** (`lifecycle=all,
   shape=any, latest_per_variant=false`). Request had a contradiction
   between the params table (defaults to picker behavior) and the
   "Versioning" section (recommended back-compat path). CO's
   pre-staged adapter passes filters explicitly, so back-compat
   defaults cost nothing and are safer.

3. **Tombstones from `bcct_row_history`, not new table.** Per memory
   [[feedback_reuse_audit_events]]. Audit table existed since mig 013,
   already captures delete events with `old_row` jsonb.

4. **Conftest now mutates dev DB state.** Force-reset of admin
   password every session is a behavior change — running tests on
   dev DB flips the password. Acceptable for test isolation; logged
   in STATUS.md "Notes for Next AI Session" so future sessions
   aren't confused.

5. **Filter logic Python-side, not SQL.** For BOM picker partition
   logic. Products have <50 artifacts in practice. SQL push-down
   reserved for "if a hot product ever has thousands of artifacts".

## What Didn't Work

- **First screenshot capture attempt** rendered full_page at
  66326×5952 pixels (8.5 MB PNG) because a long inline table forced
  the page width. Fix: capture by element selector (`table:has(.drift-row)`)
  instead of full_page. Also: `table.dh-table` alone matched the
  wrong table (material attributes at top of page, not the drift
  panel). Use a unique inner-class selector.

- **Test fixture used invalid `flatten_strategy` values**
  (`technical_raw_pending`, `modified_for_case_A/B/none`). `chk_flatten_strategy`
  CHECK constraint rejects anything outside the 6 allowed values.
  Fixed by using `no_strategy` for non_flattened rows and
  `manual_flat_as_provided` for the modified_for_case rows (intent
  filter doesn't care about strategy in that test).

- **Initial recommendation of F.1 Growatt BOM re-ingest** as next
  work. User pushed back: "tại sao cần re-ingest BOM?" Closer look:
  Growatt uses `growatt_factory_technical` adapter which doesn't hit
  the SAP qty bug or subtree dedup bug that drove Johnson's wipe.
  Re-ingest would be hygiene, not a fix. Downgraded recommendation.
  Lesson: don't recommend wipe-and-replay just because memory says
  "pending" — check whether the reasons that drove the pending state
  still apply.

- **Initial recommendation of A.4.2 substitute bulk upload.** User
  asked "Growatt/Johnson có cần bulk không?" Query showed 0
  `client_confirmed` rows on either client across 2.5 weeks since
  P1 UI shipped. YAGNI — dropped.

- **Initial recommendation of ALARM external alert.** User passed
  ("thôi bỏ qua đi"). Don't push back; move on.

## Open Items

- F.1 Growatt BOM wipe still queued in `project_reingest_pending.md`.
  Lower priority than implied by the memory; consider revising the
  memory description.
- CO's BOM picker consumer (`bom_service.product_version_options_by_code`)
  not yet inspected — request specified pre-stage pattern but I
  didn't find the commit. Worth a check next session.
- `nginx_access.log` on demo can confirm whether `/bom/version/...`
  alias has zero hits (C.3 trigger). 30-min cleanup task.
- `BACKLOG.md` audit note dates from 2026-05-13; many items shipped
  since. Worth a refresh pass when next picking work from it.

## Reusable patterns observed

- **Before/after screenshot via git revision swap**: when capturing
  UI evidence for a code change after the fact, the running server
  is on new code. Pattern: `git show HEAD~1:path > /tmp/old.py` →
  swap → restart → capture before → restore → restart → capture
  after. Worked cleanly for catalog drift panel.

- **Pre-staged consumers + probe field**: CO's `filter_applied` /
  `server_time` / `hasattr(adapter, 'method')` checks let Data Hub
  ship without coordinated deploy. Three requests today, three
  pre-staged consumers, three auto-upgrades on next CO restart. This
  is becoming the standard CO↔DH workflow and should probably be
  formalized.
