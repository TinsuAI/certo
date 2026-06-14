# Session — NXT year-keyed period + browsable detail views + Catalog cross-link

**Date:** 2026-06-14 (later PM, same day as v0.16.0 ship)
**Outcome:** Two follow-up requirements on the just-shipped NXT + year-end
inventory tier — built, reviewed, **merged (PR #9, `8921ebe`), released
`v0.17.0`, deployed to prod** (`/version`=0.17.0, `/healthz` 200, mig 087 at
boot; prod now on docs commit `ccfc482`). Dev DB test/demo clutter cleaned up.
**Feature folder:** `.ai/features/2026-06-14-nxt-inventory-tier/` (brief gained a
"Follow-up slice" section; screenshots 09–10 added; `ui_smoke.py` updated).

## What the user asked
1. **NXT phải có kỳ theo năm. Chốt tồn kho cũng phải có thời điểm.**
2. **Show bảng data đã ingest giống các bảng dữ liệu khác.** View link sang view
   khác — vd mã NVL ở bảng NXT link sang view của mã đó ở Catalog.
3. Then: demo on a company, clean up test clients, `/rev`, commit, push + PR.

## Decisions (user-confirmed via AskUserQuestion)
- **NXT "kỳ theo năm" → dedicated `period_year` (smallint), required**; supersede
  key moves `(client, period_to)` → `(client, period_year)`. Keep `period_from/to`
  optional for exact range. (Chosen over "keep date-range, just required".)
- **Inventory "thời điểm" → `snapshot_date` required**, date granularity (no time).
  (Chosen over date+time — no migration.)

## What was built (commit 6385ec2, 28 files)
- **mig 087** — `nxt_artifacts.period_year smallint` (nullable at DB for
  deploy-safety on legacy no-period rows), backfilled `extract(year from
  period_to)`, partial index `(client_id, period_year) where superseded_by is null`.
- **`app/stores/nxt.py`** — `create_artifact` takes `period_year`, derives it from
  `period_to.year` when omitted, **supersedes by year**, and **defaults
  `period_from/to` to Jan-1/Dec-31 of the year** when not given (rev fix #1, see
  below). `get_artifact`/`list_artifacts` select `period_year`. New
  `get_artifact_meta` (header-only) + `list_lines(limit, offset)` for paged detail.
- **`app/stores/inventory_snapshots.py`** — new `get_snapshot_meta` + `list_lines`.
- **`app/stores/materials.py`** (new) — `known_material_codes(client_id) -> set`
  for cross-link resolution.
- **Routes** — NXT/inventory upload now reject missing year/date (redirect
  `?error=`); meta carries `period_year` through upload→mapping→confirm; new
  `GET /clients/{id}/nxt/{artifact_id}` and
  `GET /clients/{id}/inventory-snapshots/{snapshot_id}` detail views (paginated,
  cross-client 404 guard, registered LAST so literal routes win).
- **Templates** — `nxt_detail.html` + `inventory_snapshot_detail.html` (new):
  header card + paged lines, derived closing_implied/variance with mismatch
  highlight, mã → `/catalog/{code}/detail` when in `known_codes` (`.xlink`
  primary-color affordance). List rows clickable (`data-row-href`); NXT list +
  `Năm` column; upload forms get required field + error toast; preview shows year.
- **CSS** — `a.xlink` (catalog links inherit text color by design; `.xlink` gives
  resolvable codes a clickable affordance).
- **API** — `/v1/hub` nxt list/get gain `period_year` (additive, auto via
  `list_artifacts`); `API_CHANGELOG` + `API_CONTRACT` updated. `data_promotion`
  needs no change — it introspects columns via `information_schema`.

## Review (`/rev`) — 1 Important + 1 Minor, both applied
- **Important #1 — `period_end_link` (BCQT consumer) decoupled from the required
  year.** It joins on `a.period_to = %s` / `a.period_from = %s`, never
  `period_year`. With year required but dates optional, a year-only upload
  (`period_to = NULL`) was **silently invisible** to BCQT's date-keyed
  reconciliation. **Fix:** `create_artifact` defaults `period_from/to` to the
  calendar year (settlement period = 01/01–31/12, overridable). Regression test
  `test_nxt_year_only_upload_stays_visible_to_period_end_link` locks it.
- **Minor #2 — `customs_code` cross-link could mislink** to a coincidentally-equal
  `material_code` (different namespaces). **Fix:** link `internal_code` only;
  `customs_code` renders plain mono.
- Verified blind claim: `data_promotion` introspects columns → `period_year`
  travels automatically (no finding). Route-shadowing checked (tests confirm).

## Demo + cleanup
- Seeded `demo-nxt-co` (36 real Growatt catalog codes copied so cross-links
  resolve) with NXT 2024+2025 + stocktake 2025-12-31; showed the user live.
- **Cleaned dev DB:** dropped **37** test/demo clients (`demo-nxt-co`,
  `nxt_tier_test`, `nxt-yr/det/sup/x/api-*`, `inv-det-*`) + **22** smoke template
  artifacts in `growatt-vn` (11 NXT + 11 inventory, all 3-line `system_template`).
  **No real data harmed** — real Growatt NXT lives in the BCQT repos, was never
  ingested into data-hub. `nxt_artifacts`/`inventory_snapshots`/`nxt_lines` now 0
  rows; kept `growatt-vn`, `johnson-vn`, `sa-test-allowed/blocked`.

## Tests
- +7 in `tests/test_nxt_inventory_tier.py`; updated 5 existing upload tests to pass
  `period_year` (required-field contract change). **Full suite 1531 passed, 16
  skipped.** Test gap: detail-view pagination (uses shared `_paging`, low risk).

## What didn't work / gotchas (for next AI)
- **UI smoke required-field break:** the existing smoke uploaded without
  `period_year` → HTML5 `required` blocked submit → timeout. Fixed by filling year
  in every NXT upload step (incl. the mapping-page and re-upload steps).
- **Cross-link doesn't fire on real ingested data (I2 lossy join):** real NXT/
  inventory codes (e.g. `001.002`) don't match catalog `material_code` (e.g.
  `001.0001100`). The feature is correct (links only when resolvable); screenshots
  09/10 use a self-contained demo client to show it live. A
  catalog/`code_mappings` resolver pass is the natural next enhancement.
- **Year-supersede side effect:** the smoke's year-keyed upload to `growatt-vn`
  superseded other same-year current artifacts (all template junk here, so moot —
  but be aware on clients with real same-year artifacts).

## Release / deploy (done this session)
- `pyproject` 0.16.0→0.17.0 + `CHANGELOG.md` [0.17.0] (VN) on the branch
  (`e9d11cf`); merged PR #9 (`8921ebe`); tag `v0.17.0` + GitHub release; prod CD
  green; verified `/version`=0.17.0, `/healthz` 200. Handoff docs committed
  (`ccfc482`) + pushed → prod now on `ccfc482`.
- **Gotcha:** `gh pr merge --delete-branch` did the remote merge fine but then
  tried to switch the LOCAL checkout to `main` and failed on the uncommitted
  handoff docs (repo has `pull.rebase=true`), leaving local `main` 3 behind.
  Recovered with `git merge --ff-only origin/main` (preserves uncommitted work).
  **Lesson:** with a dirty tree, run `gh pr merge` *without* `--delete-branch`,
  then `git fetch && git merge --ff-only`.

## Open / next
1. **API for NXT + chốt tồn kho** (user ask, next session). Read API already
   exists (`/v1/hub` list/get/period-end-link, Bearer/sister-app) — scope first:
   (a) write/ingest API for programmatic push, (b) `/api/v1/*` cookie-UI JSON
   mirror for the web frontend (mirror per `project_api_routing_convention`, don't
   dual-auth a cookie route), or (c) richer/paged read endpoints. Confirm at start.
2. **I2 code-join resolver** — resolve NXT/inventory codes ↔ catalog through
   `code_mappings`/catalog so cross-links + `period_end_link` fire on real data.
   Could also make `period_end_link` year-aware directly (now coherent via the
   Dec-31 default).
3. **Carry-overs (prior session, still open):** cross-link BCQT to consume
   `/v1/hub` NXT/inventory; UoM review P4 (CO allocation unit guard); declarability
   prod rollout + CO adoption; outage tar-prune confirm after ~20/06.
- Pre-existing dirty tree (`uv.lock`, `.ai/BACKLOG.md`, untracked `.ai/sessions/*`)
  left uncommitted, as before — NOT from this session.
