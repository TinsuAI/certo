# 2026-07-11 — Issue #31 shipped + CI LibreOffice-stall diagnosis and fix

## What was done

1. **Issue #31 (catalog phase 1) implemented, merged, deployed, verified.**
   - Branch `feat/materials-alive-only-filter`, commit `708e4bf`, PR #38,
     merge `cf8ed14`. TDD: `tests/test_materials_status_filter.py` (5 tests,
     red→green per route), full suite 1608 passed / 16 skipped.
   - Both `/v1/hub/materials` routes default to
     `status not in ('tombstoned','inactive')` via shared `_status_filter_sql`
     (app/routes/api.py); get-by-code gained `?status=` and 404s dead
     materials by default.
   - Docs: API_CONTRACT.md (both routes), API_CHANGELOG.md (2026-07-11
     Additive), CHANGELOG.md (VN, Unreleased).
   - `/code-review`: Spec axis clean (0 findings); Standards axis 0 hard
     violations + 4 judgement calls, 2 applied pre-merge (predicate extracted
     to one home; sister-repo line-number ref → function name
     `data_hub_client.get_material`). Not applied, deliberate: API_CHANGELOG
     stays "Additive" (Breaking = "sister apps must update code", false here)
     — note that the first real tombstone changes CO-visible responses with
     no notification fired.

2. **CI stall diagnosed** (user: "why does CD keep freezing").
   Three stalls in 26h, decomposed with evidence:
   - **2× recurring:** Test job's "Install LibreOffice" apt step on
     GitHub-hosted VMs — `azure.archive.ubuntu.com` throttled to ~40 KB/s
     (measured in run 29114048212's log: `libreoffice-common` 20.3 MB in
     7m54s). ~150 MB re-downloaded every run; no `timeout-minutes`
     (360-min default); `concurrency: cicd-<ref>` + `cancel-in-progress:
     false` queued the follow-up main run 12 min behind the stall.
   - **1× one-off:** deploy job waited ~12.5 min for the self-hosted runner
     during the 2026-07-10 box network outage (documented last session).
     CD leg is otherwise fast: deploys 74–100s.
   - Perception corrected: user assumed the local-runner CD leg; job
     metadata proved both hangs were CI on `ubuntu-latest`.

3. **Fix shipped: issue #39, PR #40**, commit `041d991`, merge `d3ad200`.
   - `actions/cache@v4` on `~/apt-debs`, key
     `apt-libreoffice-<apt candidate version of libreoffice-calc>` — hit
     installs offline; a LibreOffice point release rotates the key and
     re-seeds. `timeout-minutes: 3` (resolve) / `5` (install) replace the
     6h default.
   - Verified both paths: miss = 21s install + cache saved (89.54 MiB);
     hit (rerun) = restore 3s + install 15s, log shows "Cache restored
     successfully". Main's first run missed (GitHub cache is
     branch-scoped; PR-branch caches invisible to main), re-seeded a
     main-scoped copy — that one is visible to all future branches.
   - Prod after merge: `/version` → `d3ad200` (0.20.0), `/healthz` 200,
     anon `/v1/hub/dncxs` 401.

## Mid-session incident

Today's merge run (29118166424) itself hit the LibreOffice stall at 19:29Z
— Test stuck 19 min in apt. Cancelled + `gh run rerun` (same run id, fresh
VM): Test 2m, deploy 74s, prod verified at `cf8ed14` before the CI fix was
even built. Nothing half-deployed (Deploy job had never started).

## What didn't work

- `gh run list --jq` does NOT accept jq's `--arg` (it's gh's flag parser,
  not jq) — a background watcher died on `unknown command "sha"`. Use
  `gh run list --commit <sha>` instead of filtering by jq variable.
- Partial logs of an in-progress job are not fetchable
  (`jobs/<id>/logs` → 404 until completion); diagnose live hangs from the
  steps API (`.steps[].status/started_at`), which does update live.

## Decisions

- Cancel+rerun a mirror-stalled run instead of waiting: GitHub job timeout
  default is 360 min, deploy hadn't started, rerun reuses the run id.
- Cache key = exact apt candidate version, resolved in a prior step —
  chosen over a static `v1` key (which would re-download the delta forever
  after a point release) and over `dpkg -i` from cache (version-skew risk).

## Open items

- Carried unchanged from previous session: #37 decision (user call),
  CO refresh-token integration, `v0.19.0` tag absent, prod Postgres
  collation mismatch, `docs/agency-staff-guide` branch (`d5ae3ab`).
- Catalog order **1 → 0 → 2 → 3 → 4 → 5**: phase 1 (#31) DONE → next is
  **#30** (one open decision inside it: placeholder config placement).
- Merged branches deletable: `feat/materials-alive-only-filter`,
  `ci/cache-libreoffice-debs` (plus older `feat/sso-refresh-tokens`).
- CHANGELOG.md `[Unreleased]` now carries the #31 entry — next release cut
  (0.21.0) should sweep it.
