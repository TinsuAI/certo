# Session 2026-05-11 — A.7 BOM description + Bearer substitute mirror + F.1 cleanup

## What Was Done

Backlog-driven session. Original sequence picked from `/loop` planning:
`A.7 → A.6 → A.5 → A.1`. Actual flow:

### F.1 cleanup (preamble, before A-series work)
- BACKLOG F.1 "Johnson programmatic bulk re-ingest plan" moved to
  Shipped — that work landed already in commits `11ea9bd` + `dcc6216`
  + `cac2bcb` + `e7578bf` via 4 chained scripts (no single
  `bulk_reingest_johnson.py` tool). F.1 now tracks Growatt-only
  re-ingest plan, ~0.5-1d effort by mirroring Johnson's chain.
- Memory `project_reingest_pending.md` reframed: Johnson SHIPPED
  2026-05-11; Growatt PENDING. MEMORY.md index hook updated.
- Carry-over uncommitted from prior session: STATUS.md + the
  2026-05-11 Johnson session log. Committed together as
  `0989237 docs(handoff): Johnson onboarding ship + F.1 backlog cleanup`.

### A.7 — BOM parser extract Object description column (shipped)
- `_DESCRIPTION_ALIASES` added in `sap_indented_walk.py` covering
  EN ("Object description", "Description", "Material description"),
  VI ("tên hàng", "mô tả"), ZH ("物料描述", "物料名称").
- `SapIndentedWalkAdapter.parse` propagates description into leaf
  rows. `parse_sap_indented_raw_edges` (raw-edge path Johnson
  actually uses) stores description into `bom_edges.payload->>'description'`.
  jsonb-only — no schema migration.
- `catalog_candidates._backfill_sample_from_bom` added as a fallback
  after BCCT backfill; picks most-recent alive artifact's description
  for BOM-only candidates via UNION of `child_code` + `parent_code`
  lookups.
- 5 tests added: 3 parser tests (`test_bom_raw_edges`) + 2 candidate
  refresh tests (`test_catalog_candidates_refresh`).
- Commit `9c687da`.

### A.5 — v_material_roles paren-aware (deferred)
- Started, then halted: original BACKLOG recommendation (option B:
  reintroduce `bcct_rows.internal_code` column) directly conflicts
  with `feedback_no_derived_in_source` memory. Mig 038 dropped
  `material_identity` precisely to enforce that principle. Adding
  another cached column would re-violate it.
- Three options surveyed and written into BACKLOG A.5 body:
  - B (stored column + trigger) — original plan; needs plpython3u OR
    external Python re-derive job. Conflicts with principle.
  - C (separate derived table `bcct_internal_codes`) — aligns
    principle. ~1-1.5d.
  - D (batch Python supplement on list page) — solves 1 of 3 removal
    triggers. ~2-4h.
- User: "thôi defer đi, cái này tao vẫn chưa rõ lắm." Deferred. A.6
  also stays deferred (its 3-script Python rewrite would be obsoleted
  by A.5 option B or C).

### CO blocker — Bearer-aware substitute API (unplanned, shipped)
- CO reported 401 on `GET /api/v1/clients/{c}/materials/{m}/substitutes`
  for any Bearer token. Root cause: route uses `auth.require_user`
  which only checks `data_hub_session` cookie. Cross-origin
  server-to-server can't carry the cookie.
- Approach picked: option B (mirror under `/v1/hub/*`, Bearer-aware,
  cookie route preserved for UI). Aligns with sister-app convention.
- New `GET /v1/hub/clients/{c}/materials/{m}/substitutes` in
  `app/routes/api.py`; reuses `_require_token` + `_require_can_view_client`.
  Same response shape as cookie route.
- 7 tests in `tests/test_substitute_api_v1.py` (no-auth, service
  token happy path, scope rejection, whitelist allow/block,
  min_score filter).
- `docs/API_CONTRACT.md` Substitutes section added.
- Sister-app note posted at
  `.ai/sister-app-notes/2026-05-13-substitute-api-bearer-available.md`.
- Live-verified end-to-end with a minted service token against
  Johnson `MFW0502-39` → 200, 15 substitutes (embedding + trigram +
  manual sources).
- Commit `ae3373b`.

### Push + handoff
- 8 commits pushed to `origin/main` (covers this session + leftover
  from Johnson onboarding session).
- CO posted back-note
  `.ai/sister-app-notes/2026-05-13-co-substitutes-bearer-consumer-shipped.md`
  confirming their adapter migrated and CO tests pass.

## Decisions Made

1. **F.1 split into Johnson SHIPPED + Growatt PENDING** rather than
   archiving F.1 wholesale. Growatt still needs the same wipe +
   re-ingest, so the queue entry is still useful.

2. **A.7 stores description in `bom_edges.payload->>'description'`
   (jsonb)** rather than adding a `description text` column via mig.
   Sparse data, no aggregation needs, no migration cost; matches
   existing payload convention. Removable if a typed column is ever
   needed.

3. **A.7 backfill is BOM-only fallback, not a replacement.**
   `_backfill_sample_from_bcct` runs first; BCCT goods_name wins
   when present. Test
   `test_refresh_bcct_sample_takes_precedence_over_bom_description`
   locks the order in.

4. **A.5 deferred rather than picked.** User explicitly said unclear;
   the design options have asymmetric cost / principle alignment.
   No partial work shipped — design notes captured in BACKLOG for
   when bandwidth + clarity converge.

5. **CO blocker fix via mirror, not in-place dual-mode.** Cleaner
   architecture: cookie surface stays for UI, Bearer surface lives
   under canonical sister-app prefix `/v1/hub/*`. Cost ~1h vs ~30min
   for dual-mode in-place; the longer-term clarity is worth it. Same
   pattern likely applies to other cookie-only routes CO may need.

6. **Commit hygiene: 2 commits per logical change.** F.1 docs +
   Johnson handoff carry-over got their own commit (`0989237`) so the
   A.7 commit (`9c687da`) stayed scope-clean. Avoided BACKLOG.md
   cross-commit pollution by reverting + re-applying patches via
   `/tmp/backlog_with_both.md`.

## What Didn't Work

1. **Initial A.5 dive aborted.** Started reading
   `material_observations.py`, `client_parser_rules.py`,
   `v_material_roles.sql` to design option B. Realized halfway
   that adding `bcct_rows.internal_code` re-violates the principle
   that drove mig 038. Stopped, surveyed alternatives, presented
   to user. User deferred. ~30min spent but produced the BACKLOG
   design memo, so not wasted.

2. **Test `test_technical_raw_upload_confirm_materializes_edges`
   failing on main** (pre-existing). Verified via `git stash` →
   still fails. Not from any of this session's changes. Leaving as-is
   per "don't fix what wasn't broken by your changes." Worth a
   follow-up but not blocking.

3. **Browser end-to-end test for A.7 not driven by AI.** User said
   "tôi chỉ prep, ông tự click." Johnson XLSX copied to Windows
   Downloads; steps documented. Browser-side verification still
   pending.

## Open Items

- **A.5 design choice** — defer in place; re-engage when user has
  clarity on the principle vs SQL-side query convenience trade-off.
- **A.6 Python rewrite** — sequence-coupled with A.5. Stays deferred.
- **Johnson BOM full re-ingest for A.7 backfill** — needs CLI run
  (`scripts/ingest_technical_raw_batch.py` over the 106 XLSX). After
  that, `refresh_candidates` will populate `sample_text` for 3711+
  BOM-only candidates. Pre-requisite: pg_dump backup before wipe.
- **CO Bearer audit** — substitutes migrated. Confirm if CO calls
  any other `/api/v1/...` routes that would 401 on Bearer; if so,
  mirror them under `/v1/hub/*` on demand.
- **`test_technical_raw_upload_confirm_materializes_edges`
  pre-existing fail** — unrelated to this session's work; assertion
  expects `('technical_raw', 2, 0)`, gets `('technical_flattened', 0, 1)`.
  Smells like a side-effect of the BTP dedup fix / hook resolution
  fix from earlier 2026-05-11 work. Worth a focused fix session.
- **A.1 (roles[]) still pending** — biggest remaining open item from
  the original sequence. 2-3d cross-cut refactor; ready to start when
  user picks it up.
