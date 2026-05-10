# Feature: BOM refresh-time UoM conversion preview

Closes the last open Phase 3 follow-up (BACKLOG entry G). Ingest-time
preview shipped 2026-05-12 (commit `c57c627`); refresh-time still
auto-applies the 3-tier policy and redirects without showing the staff
the conversion plan.

## Scope

**In:**

1. **Plan/commit split in `bom_staleness`.** Factor `refresh_artifact()`
   into:
   - `plan_refresh(client_id, artifact_id) -> RefreshPlan` — pure, no
     writes. Re-walks SQL (or reconstructs manual_flat originals),
     calls `_convert_rows_to_catalog_uom`, returns per-row plan +
     drift summary + `would_be_hash` (for no-op detection) + flatten
     strategy + has_blocking flag.
   - `commit_refresh(client_id, artifact_id, *, plan=None, edits=None,
     skip=False, triggered_by_user_id=None) -> RefreshResult` —
     existing logic. Re-plans at the top to defeat TOCTOU between
     preview render and POST commit. Applies inline `edits` (factor
     rows in `client_uom_overrides`) before re-planning.
   - `refresh_artifact(...)` keeps its current signature as a thin
     wrapper around `commit_refresh()` for callers that don't care
     about the preview path (existing tests, programmatic refresh).
2. **GET preview route**:
   `/clients/{cid}/bom/artifact/{aid}/refresh/preview`. Renders a new
   template `bom_refresh_preview.html`. Reuses `_uom_drift_banner.html`
   for the drift summary. Adds a per-row plan table:
   `row_index | material_code | source_qty + uom | → | target_uom |
   factor | source | tier | status`. Status badges: `ready` (green),
   `unconfirmed_default` (yellow, Tier A), `blocked_no_factor` (red,
   Tier B). Inline "+ hệ số" link prefilled with material_code +
   from/to UoM (mirrors ingest banner).
3. **POST commit route** stays at
   `/clients/{cid}/bom/artifact/{aid}/refresh` (no URL break). New
   optional form fields:
   - `confirm=1` — explicit confirmation from preview screen (default
     when the button on preview is clicked).
   - `skip=1` — staff chose "không refresh bây giờ" — see decision 4.
   - `inline_factor[material_code]=…` — staff-edited factor entered on
     the preview page (one or more). Persists to `client_uom_overrides`
     before commit.
4. **UI swap on artifact detail.** The two existing Refresh forms
   (in stale block + drift block of `bom_artifact_detail.html`) change
   from `method="post"` to `method="get"` pointing at the new preview
   route. Direct-POST still works for tests and curl callers, but the
   default human path goes through preview.
5. **No-op detection.** When `plan.would_be_hash == artifact.normalized_hash`,
   preview shows "Refresh sẽ không thay đổi gì (same hash)" + a
   "Clear flag only" button that posts `confirm=1` (which already
   handles same-hash dedup → just clears flag).

**Out (defer):**

- BCCT artifact refresh preview — BCCT artifacts don't go through this
  refresh path. Out of scope.
- Bulk preview across many artifacts (e.g. "preview all stale for this
  product"). The stale list page already exists; bulk preview would
  duplicate it. Defer.
- Diff view between current rows and would-be rows (row-by-row "before
  vs after"). Nice-to-have but high complexity for limited gain.
- Routing skip-convert through a per-artifact "muted drift" flag.
  Decision 4 takes the simpler path.

## Decisions

1. **Plan is recomputed at commit time.** Preview is informational
   only. Catalog or factor state can change between preview render
   and POST; commit-time re-plan is the source of truth. Preview must
   warn "Hệ số có thể đã thay đổi — kế hoạch hiển thị cách đây N
   phút" if render age > 5 min (timestamp in form).
2. **Inline factor edits persist.** A factor edited on the preview
   page writes a `client_uom_overrides` row before commit, same as the
   ingest preview's "save factor to table" action. No "one-shot factor
   for this refresh only" mode — that semantic was rejected for
   ingest-time and we keep it consistent.
3. **Plan-only function lives in `bom_staleness.py`** next to
   `refresh_artifact`. Rejected putting it in `uom_drift.py` because
   it needs access to manual_flat reconstruction + raw walk SQL, both
   already in `bom_staleness`. Reuses `_convert_rows_to_catalog_uom`
   unchanged.
4. **Skip = no state change + audit row in existing table.** `skip=1`
   inserts a row into `hub.bom_audit_events` (mig 006, already in use
   for `event_type='version.created'`) with `event_type='refresh.skipped'`
   and `details={plan_summary, source_uoms, blocking_count}`. NO new
   migration needed — that was the original plan but `bom_audit_events`
   already has the exact shape (`client_id, product_code, artifact_id,
   event_type, actor, details jsonb, occurred_at`). Skip does NOT
   tombstone, NOT clear flag, NOT touch the artifact. Rationale:
   "skip" is "I saw this, I'll deal with it later" — clearing the
   flag would lose the warning; tombstoning would mint a useless
   dead artifact. Future review queries against `bom_audit_events`
   filtering on `event_type` are already possible.
5. **Concurrent factor edit = last-write-wins.** No optimistic lock
   token. Agency staff is small (3-5); cross-family same-material
   simultaneous edits are rare. If incident occurs ("staff A's
   factor silently overwritten"), upgrade to optimistic lock then.
6. **Same-hash button label: "Xác nhận đã xem"** — matches staff
   workflow framing ("I reviewed, nothing to do") rather than
   technical framing ("clear flag"). Action: clears `is_stale` /
   `has_uom_drift` on the artifact, no new artifact minted, redirect
   back to detail.
7. **Manual_flat + derived share the same preview UI.** Plan shape is
   uniform; rendering is row-table either way. The minor difference
   (manual_flat has no parent_artifact_id) is in metadata, not the
   plan.
8. **Existing direct-POST tests stay green.** `refresh_artifact()`
   keeps signature and behavior. The new path is additive.

## Risks

- **TOCTOU between preview and commit.** Mitigated by decision 1 —
  always re-plan at commit. Preview age stamp warns staff if drift.
- **Test churn from refactor.** Phase 2 has 10+ tests directly
  exercising `refresh_artifact()`. The factoring must keep that public
  API exactly. Verify by running the affected suites
  (`test_bom_staleness*.py`, `test_manual_flat_refresh.py`,
  `test_bom_artifact_rows_uom_audit.py`) before each commit.
- **`refresh_product()` calls `refresh_artifact()` in a loop.** No
  preview path for bulk; that's intentional (Out section). But the
  factored `commit_refresh` must be cheap enough that the existing
  bulk path doesn't regress. Re-planning twice (in `plan_refresh`
  then again in `commit_refresh`) is fine for the single-artifact
  preview case but doubles work in the bulk case → bulk should call
  `commit_refresh(plan=None)` which skips the preview-path overhead.
- **3-tier policy + Tier A unconfirmed_default.** Refresh today
  silently applies factor=1.0 for Tier A. Preview must EXPOSE this
  per-row with a yellow badge. Risk: staff confirms a screen full of
  yellow without reading. UI must require an explicit "Tôi đã xem"
  checkbox if any row is Tier A unconfirmed. Same pattern as ingest
  preview's `ack_uom_drift`.
- **Inline factor edit conflicts.** Two staff sessions could edit the
  same factor concurrently. `client_uom_overrides` has a unique key
  `(client_id, material_code, from_uom, to_uom)` — last write wins.
  Acceptable, matches ingest semantic. **Open Q2.**

## Open Questions

1. **Preview screenshot in feature folder** — required by repo
   convention. Defer to post-impl: capture once UI is wired.

(Q1-Q3 from initial scoping resolved 2026-05-13:
audit = reuse `hub.bom_audit_events` with `event_type='refresh.skipped'`
(no new mig); concurrent edit = LWW; same-hash label = "Xác nhận đã
xem". See Decisions 4-6.)

## Implementation phases (estimate: ~1-1.5d)

Each step its own commit pair (tests + impl):

1. **Refactor `refresh_artifact` → `plan_refresh` + `commit_refresh`**
   maintaining external API. **~3h.**
2. **GET `/refresh/preview` route + `bom_refresh_preview.html`
   template.** Reuse drift banner. **~3h.**
3. **POST extensions**: `confirm`, `skip`, `inline_factor[]`. Skip
   inserts `event_type='refresh.skipped'` into existing
   `hub.bom_audit_events`. No migration. **~1.5h.**
4. **UI swap on artifact detail** (POST → GET preview). **~30min.**
5. **No-op detection + same-hash messaging.** **~1h.**
6. **Tests** (per phase, alongside impl): preview renders plan,
   commit re-plans, inline factor edit persists, skip records audit
   without state change, same-hash → clear flag flow. **bundled in
   each step's commit pair.**
7. **Screenshot smoke** via `scripts/screenshot_*.py`-style harness.
   Capture preview screen with mixed Tier A/B rows. **~30min.**

## Manual test plan

1. Stale derived artifact with mixed Tier A + Tier B rows. Click
   Refresh → preview screen shows row table, yellow + red badges,
   ack checkbox visible because Tier A present. Confirm → mints new
   artifact, redirects to it.
2. Stale manual_flat artifact, factor missing for one row. Preview
   shows red blocked row + "+ hệ số" prefill link. Click prefill,
   add factor in admin UI, return to preview, refresh → row turns
   green. Confirm → mints new artifact.
3. Same-hash refresh (catalog hasn't changed semantically). Preview
   shows "Refresh sẽ không thay đổi gì". Click "Clear flag only" →
   flag cleared, no new artifact, redirect back to detail.
4. Skip from preview → no state change verified by reloading detail
   page (still stale, drift still present). Audit table has 1 row
   for the click.
5. Inline factor edit on preview → POST commits the edit + refresh
   in one round-trip. Verify `client_uom_overrides` row exists.
6. Direct POST `/refresh` (no preview, e.g. curl) still works for
   backwards compat. Existing tests pass unchanged.

## Done criteria

- [x] `plan_refresh()` + `commit_refresh()` exist; `refresh_artifact()`
      delegates; all existing refresh tests still pass (971 / 971).
- [x] GET preview route renders plan with severity badges + ack when
      Tier A present.
- [x] Inline factor edit on POST persists to `client_uom_overrides`
      before commit.
- [x] Skip = no state change + audit row in `hub.bom_audit_events`
      (`event_type='refresh.skipped'`).
- [x] Same-hash detection + "Xác nhận đã xem" UX.
- [x] Artifact detail Refresh button defaults to GET preview path.
- [x] Screenshot of preview screen committed
      (`screenshots/01_preview_mixed_tiers.png`).
- [x] BACKLOG Phase 3 G entry marked SHIPPED.

## Cross-links

- Phase 2 brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
- Phase 1 (staleness flag): `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`
- BACKLOG entry: "Phase 3 follow-ups → G. Refresh-time conversion preview"
- Memory: `project_uom_drift_gate.md`, `project_bom_immutable_principle.md`
- Code touchpoints (read-only references):
  - `app/stores/bom_staleness.py:418` `refresh_artifact`
  - `app/stores/bom_staleness.py:291` `_rederive_manual_flat`
  - `app/stores/bom_staleness.py:342` `_rederive_shape`
  - `app/stores/uom_drift.py:75` `compute_uom_drifts`
  - `app/templates/clients/_uom_drift_banner.html` reusable preview chunk
  - `app/templates/clients/bom_artifact_detail.html:24,82` Refresh forms
  - `app/routes/bom.py:598` POST refresh route
