# 2026-05-13 — Phase 3 G refresh-preview + 3 small backlog items

## What Was Done

12 commits on `main`. Test count 953 → 978 (+25). No new migration.

### Bundle 1 — backlog reconciliation (commits `1876dea`, `2fe2945`)

Triggered when user asked "start phase 2 UoM conversion", but
verification showed Phase 2 already shipped 2026-05-12. Reading the
brief revealed Phase 3 follow-ups E and F had been folded in too —
backlog was stale.

- `1876dea`: extend `list_artifacts_for_product` SELECT in
  `app/stores/bom.py` to include `has_uom_drift` + `uom_drift_reasons`.
  Single-artifact reads already exposed them via `get_artifact_with_rows`;
  list endpoint `/v1/hub/products/{p}/bom/artifacts` did not. Sister
  apps consuming the list view now see drift. New test
  `test_api_list_artifacts_includes_uom_drift_fields` in
  `test_bom_staleness_api_ui.py`.
- `2fe2945`: BACKLOG entry "BOM UoM conversion engine" annotated
  SHIPPED. Phase 3 follow-ups E + F marked SHIPPED (folded into Phase 2
  brief items 2/3/6). G narrowed to the actual remaining gap:
  refresh-time conversion preview UI. Brief Done criteria ticked.

### Bundle 2 — Phase 3 G refresh-preview (commits `8119e69` → `3269d76`)

`/discover` produced a brief at
`.ai/features/2026-05-13-bom-refresh-preview/brief.md`. User
decided 3 open Qs:

1. Skip audit storage: **reuse `hub.bom_audit_events`** with
   `event_type='refresh.skipped'`. (Initial proposal was a new mig 059
   `hub.refresh_skip_audit`; user pushed back; codebase search found
   the existing table from mig 006 already had the exact shape.
   Memory `feedback_reuse_audit_events.md` captures the lesson.)
2. Concurrent factor edit: **last-write-wins**, no optimistic lock.
3. Same-hash refresh button label: **"Xác nhận đã xem"**.

`/tdd` then walked 7 implementation phases:

- `8119e69` — refactor `refresh_artifact()` body into a public
  `commit_refresh()` with `skip` + `edits` params; new pure
  `plan_refresh()` returning `RefreshPlan` (per-row plan +
  drift_summary + would_be_hash + has_blocking + skipped_reason).
  `refresh_artifact()` becomes a thin wrapper for back-compat.
  10 new tests in `test_bom_refresh_plan.py`.
- `b694e81` — GET `/clients/{cid}/bom/artifact/{aid}/refresh/preview`
  route + `bom_refresh_preview.html` template. Renders per-row plan
  with status badges (sẵn sàng / mặc định 1:1 / thiếu hệ số / thiếu
  catalog UoM). Same-hash detection swaps CTA to "Xác nhận đã xem".
  Tier A unconfirmed requires explicit ack checkbox before submit.
  4 new tests in `test_bom_refresh_preview_route.py`.
- `f7c82bd` — POST `/refresh` extended with `skip=1`,
  `inline_factor_<i>_<key>` form fields. Skip writes `bom_audit_events`
  row + returns without state change. Inline factor edits upsert
  `client_uom_overrides` before commit re-plans. Direct POST without
  these stays back-compat. 3 new tests in
  `test_bom_refresh_post_extensions.py`.
- `de1beea` — UI swap: stale + drift Refresh forms in
  `bom_artifact_detail.html` change from `method=post` to GET preview
  links. No test churn — existing assertions match the link text.
- `ea750b7` — lock the no-op refresh contract with 2 tests:
  preview shows "Xác nhận đã xem" + same-hash banner; POST confirm
  on same-hash clears flag without mint or tombstone.
- Full suite check: 971 / 971 pass (was 953 → +18).
- `3269d76` — close-out: BACKLOG Phase 3 G marked SHIPPED, brief
  Done criteria ticked, screenshot captured by
  `scripts/screenshot_refresh_preview.py` showing mixed Tier A
  (yellow) + Tier B (red) rows + ack checkbox + "+ hệ số" prefill
  link + "Bỏ qua" button.

### Bundle 3 — 3 small backlog items (commits `8cf355e` → `4060997`)

User requested three small independent items in sequence:

- `8cf355e` — **BOM upload auto-detect adapter**. Adds `auto` as the
  default option in the upload form. POST handler with `profile=auto`
  calls `bom_adapters.parse_with_fallback()` with filename stem as
  `root_code` hint; first adapter producing non-empty rows wins.
  Skips column-mapping page entirely (manual_flat path). 400 with
  friendly Vietnamese message when all 5 adapters fail. Manual
  override preserved. 2 new tests in `test_bom_flexible_flow.py`.
- `f113d17` — **Manual_flat 4-shape model**. `bom_shape()` returns
  `'manual_flat'` for `manual_flat_as_provided` strategy (was
  conflated with `'shallow'`). `BomShape` Literal extended to 4
  values. `shape_badge` macro renders `manual_flat` with its own
  tooltip emphasising "source vs derived". Memory
  `project_bom_3_shapes.md` updated 3-shape → 4-shape with worked
  example. 5 new tests in `test_bom_shape_function.py`.
- `4060997` — **UI rename "tombstone" → friendly Vietnamese**.
  UI/template/i18n only — code/DB/API stay `tombstone`. Mapping:
  catalog material → "đã loại"; BOM artifact lineage/replace → "đã
  thay thế"; preset retract → "thu hồi". 9 files edited including
  i18n.py VN values for `status.tombstoned` and
  `bom.stale.dim.btp_bom_tombstoned`. No test churn (UI text only).

### Bundle 4 — UI smoke evidence (commit `faadff0`)

User: "test bằng UI đi, đừng chỉ chém gió." Wrote
`scripts/smoke_three_small_items.py` Playwright harness. Drove all
3 items end-to-end against the live dev server. 5 visible checks
pass; one skipped (no `materials.status='tombstoned'` fixture in
DB). Screenshots committed at
`.ai/features/2026-05-13-three-small-items/screenshots/` along with
brief.md + the smoke script (OUT path points back at the feature
folder so future runs overwrite committed evidence).

## Decisions Made

1. **Reuse existing audit table over new mig.** When asked where to
   record the `refresh.skipped` event, initial answer was a new
   `hub.refresh_skip_audit` table with mig 059. User pushed back —
   "không lẽ cả bảng audit chỉ để track cái skip?". Codebase search
   found `hub.bom_audit_events` (mig 006) already had the exact
   schema (`client_id, product_code, artifact_id, event_type jsonb,
   actor, details jsonb, occurred_at`) and was already in use for
   `event_type='version.created'`. Reused it. Saved memory
   `feedback_reuse_audit_events.md` so future sessions check the
   table first.

2. **plan/commit split, not preview-only refactor.** `refresh_artifact()`
   already worked end-to-end. Splitting into `plan_refresh` (pure)
   + `commit_refresh` (mutates) makes the preview path possible
   without TOCTOU between render and commit (commit always re-plans
   at top). `refresh_artifact()` retains its old signature as a
   wrapper for the existing 10+ test callers.

3. **Skip = no state change + audit row only.** Rejected
   alternatives: tombstoning (would mint a useless dead artifact)
   and clearing the flag (would lose the warning). Skip captures
   intent without state change.

4. **Concurrent factor edit = LWW.** Rejected optimistic-lock token.
   Agency staff is small (3-5); cross-family same-material
   simultaneous edits are rare. Upgrade to optimistic lock if an
   incident occurs.

5. **Same-hash CTA = "Xác nhận đã xem".** Rejected "Clear flag
   only" (too technical) and "Đóng cảnh báo" (mơ hồ về artifact
   mint). "Xác nhận đã xem" matches staff workflow framing.

6. **4-shape model for BOM.** `manual_flat` is a SOURCE artifact
   (agency uploaded directly), distinct from `shallow` (DERIVED
   walker stopped at first leaf). The 3-shape model lumped them
   together; user feedback was that this was misleading. Memory
   `project_bom_3_shapes.md` updated.

7. **`auto` upload profile is the default, not an opt-in.** Per
   BACKLOG: "default = auto". Manual override stays available as
   the existing dropdown options. New users won't have to learn the
   5-adapter taxonomy upfront.

## What Didn't Work

1. **Initial `parse_with_fallback` path was already partially
   wired** for `technical_flatten` profile (line 279 of bom.py). I
   almost over-engineered by adding a separate registry walker; the
   right move was reusing the existing function with a new entry
   point at the top of the upload route handler.

2. **Playwright `button[type=submit]` selector** matched 11
   elements in the page (header notification button "Đánh dấu tất
   cả đã đọc" was the first hit). Fixed by scoping to the form:
   `form:has(input[name="password"]) button[type="submit"]`. Worth
   remembering for future smoke scripts.

3. **Catalog detail URL** — first guess was
   `/clients/{cid}/catalog/{material_code}` (returns 404). Actual
   route is `/clients/{cid}/catalog/{material_code}/detail`.
   Fixed and re-ran.

4. **Initial `commit_refresh` test factor assertion**
   `r["factor"] == "1"` failed — `Decimal('1')` survives convert as
   `float(1.0)` and `str(1.0) == "1.0"`, not `"1"`. Adjusted test
   assertion (the implementation contract is "factor is stringified
   for UI display"; precision is preserved by Decimal upstream).

## Open Items

- **Push 12 commits to `origin/main`** — deferred per user not
  asking.
- **Phase 2 step 9** (Johnson factor table populated for 220
  cross-family pairs) — agency-blocked on Q&A.
- **Sister apps adopting Phase 2 schema** — BCQT/CO consumer reads
  may diverge from Data Hub output until they update. Sister-app
  notes posted at
  `.ai/sister-app-notes/2026-05-12-uom-conversion-cutover.md`.
- **3b smoke skipped** — no `materials.status='tombstoned'` row in
  the live DB. The catalog template logic for tombstoned-material
  badge wasn't visually verified. Risk is low (same `status_labels`
  lookup used in 3c which did pass).
- **Demo server (tinsu) not updated** — Phase 3 G + 3 small items
  exist on `main` local only.
