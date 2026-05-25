# Johnson UoM audit + btp_sx uom bug fix

**Date:** 2026-05-25
**Branch:** main → `bc4fb3b` (after handoff commit). Code at `d7508ef`.
**Scope:** Local DB + code patch + demo box deploy + password rotation.
**Demo:** `ttdatahub.tinsu.ai` deployed and verified live.

## What was done

### 1. Johnson reply status audit

Verified Johnson reply 2026-05-21 ("EA = SET, CAY = EA") was loaded
into `hub.client_uom_overrides`:

| Pair | Rows | Source date |
|---|---|---|
| EA → CAY | 90 | 2026-05-21 |
| PIECES → CAY | 90 | 2026-05-21 |
| SETS → CAY | 90 | 2026-05-21 |
| SETS → PIECES | 58 (new) + 29 (evidence audit) | 2026-05-21 + 2026-05-14/15 |
| ROLL → PIECES | 2 | 2026-05-14 |

→ 357 overrides at session start.

`.ai/STATUS.md` did NOT reflect this insert — was applied after 2026-05-21
handoff was written, undocumented until this audit.

### 2. Inventory gap audit: 3 EA→mass codes from `factor_inventory.md` (2026-05-12)

Factor inventory chốt 2026-05-12 noted 3 codes needing EA→KG/MT
override (BCCT∩BOM intersection where BOM raw=EA + BCCT/catalog=mass):

- `1000478156` — Thép tấm 10×1500×3000mm — KILO-GRAMMES
- `1000480137` — Thép tấm 12×1500×3000mm — KILO-GRAMMES
- `K60000900` — Dây hàn ER70S-6 box 250kg — METRIC-TONS

Verified via M16 cross-check: SAP tech_flat qty "0.813 EA" === M16
declared qty "0.813 KILO-GRAMMES" byte-identical for same product.
Distribution proof: 100% fractional qty (median 1.8, p95 17.1) — mass
pattern, NOT count.

**Insert: 3 overrides**
- EA → KILO-GRAMMES = 1.0 (×2)
- EA → METRIC-TONS = 0.001 (×1)

Pattern: SAP label "EA" for these codes is mass synonym. Factor 1.0
(or 0.001 for MT scale). Note ghi rõ evidence path.

### 3. Re-ingest tech BOM (materialize cleanup-stale)

Ran `scripts/materialize_shallow_and_full_flat.py --client johnson-vn
--cleanup-stale --commit`.

**Unexpected scope:** main loop inserted 3,137 shallow + 3,137 full_flat
for raw_graph artifacts that were missing shapes (pre-existing
deficit, not caused by this session). Plus cleanup-stale refreshed
2,719 stale artifacts.

After run:
- tech_flat: 9,340 active (5,895 fresh + 3,445 stale) + 2,719 tombstoned
- 3 EA→mass codes' rows: `applied_uom_factor` populated, source=client_specific

### 4. Investigated 3,445 remaining stale tech_flat

Drift breakdown:
- 440 codes flagged `factor_missing` EA→KG
- 156 codes flagged `unconfirmed_default_1to1` EA→SETS
- 20 codes SETS→SETS (same-uom, weird)
- ~5 minor outliers (EA→EA, G→EA, Chai/Lọ/Tuýp→EA)

User asked: "tao tưởng confirm hết cả mấy cái Cay = EA rồi" — pointed
me to investigate why 440 EA→KG persists despite agency reply.

### 5. Root cause: 440 EA→KG drift = bug in `fixup_johnson_btp_sx_after_bom.py`

All 440 codes are btp_sx (BTP nội bộ, never in BCCT). Catalog uom was
set by `fixup_johnson_btp_sx_after_bom.py` (2026-05-11 onboarding).
Script queried `bom_edges.uom WHERE parent_code = code` — uom of inputs
the BTP CONSUMES (= SAP Base UoM = `KG` for these 440). Per project
memory `project_bom_component_unit_canonical`: Component unit is
canonical; Base UoM is SAP stockkeeping internal and must NOT populate
catalog.

Verified 100%:
- AS_CHILD mode (Component unit): EA for 440/440
- AS_PARENT mode (Base UoM via inputs): KG for 440/440

Distribution evidence aligns: 99.86% integer qty (689/690 rows),
range 0.5-4 → real count, NOT mass-mislabeled (which would be
fractional, like the 3 thép tấm).

**Fix:**
1. UPDATE catalog: 440 `materials.uom` KG → EA. Provenance note ghi
   bug context + memory pointer.
2. Patch script: `e.parent_code = code` → `e.child_code = code`.
3. Update 3 tests in `tests/test_fixup_johnson_btp_uom.py` —
   previously asserted KG (the buggy behavior); now assert EA.

Tests: 3/3 PASSED.
Commit: `d7508ef fix(catalog): btp_sx uom auto-capture uses Component unit, not Base UoM`

Rerun materialize cleanup-stale → 352 stale cleared (3,445 → 3,093).

### 6. Quick win: 156 EA→SETS override gap

Johnson reply 2026-05-21 confirmed EA=SET synonym. Overrides table
had SETS→PIECES (the direction triggered by codes with catalog=PIECES
and BOM raw=SETS) but NOT EA→SETS (the direction triggered by codes
with catalog=SETS and BOM raw=EA). 156 codes flagged due to this gap.

**Insert: 156 EA→SETS = 1.0 overrides.** Note references Johnson reply
date + inverse-direction justification.

Rerun materialize → 281 more stale cleared (3,093 → 2,812).

### 7. Local DB cleanup + demo box deploy

After landing all DB changes locally, prepared and shipped the full
bundle to demo box (`ttdatahub.tinsu.ai` / `100.84.189.87:8754`):

- **Cleanup local DB**: deleted 6 inactive/test clients
  (`demo-precision-manufactu-{480e,68f7}`, `dke-vietnam-d0e3`,
  `do-thanh-vietnam-2614`, `sa-test-{allowed,blocked}`). FK CASCADE
  handled all dependents (materials/bcct/bom/overrides). Local now
  Johnson + Growatt only.
- **Push code**: `d7508ef` + `bc4fb3b` to `origin/main`.
- **DB sync**: `pg_dump postgresql:///data_hub --schema=hub
  --format=custom --no-owner --no-acl` (302MB compressed) → scp →
  demo `data-hub-db-1` container → `pg_restore`. Row counts on demo
  match local exactly: 13,589 materials / 88,926 BCCT / 13,602 BOM
  artifacts / 167,581 BOM rows / 518 overrides.
- **Code deploy**: `git pull` on demo (fast-forward to `bc4fb3b`),
  `docker compose build app`, `docker compose up -d app`. Healthz
  HTTP 200 + clean startup logs.
- **Verified session changes on demo**: btp_sx EA=2614 (KG=0),
  EA→SETS overrides=156, EA→mass overrides=3.
- **Password rotation**: after DB sync, `admin@data-hub.local`
  password hash was the LOCAL seed value (`local_test_password`) —
  not the demo `.env` value. Generated argon2id hash via
  `docker exec data-hub-app-1 python -c "from app.auth import
  hash_password; print(hash_password('sS3EZgj9lf5b741'))"` and
  UPDATE'd `hub.users`. Login flow verified end-to-end through
  `https://ttdatahub.tinsu.ai/login`.

## Final state

```
Catalog (Johnson btp_sx + source=bom_observed):
  Before:  2,174 EA + 440 KG + 1 G
  After:   2,614 EA + 1 G

Overrides (Johnson, hub.client_uom_overrides):
  Before session: 357
  After:          516
    +3   EA → KG/MT     (mass synonym for thép tấm + dây hàn)
    +156 EA → SETS      (synonym inverse direction)

Stale tech_flat:
  Session start:  2,543
  Peak (post-1st materialize):  3,445
  Final:          2,812

Stale-flagged drift codes:
  Session start:  ~180 unique
  Final:          39 unique
```

## Remaining drift (39 unique codes)

| Drift kind | Catalog | BOM raw | Codes |
|---|---|---|---|
| `unconfirmed_default_1to1` | SETS | SETS | 20 (same-UoM drift — weird, alias case?) |
| `unconfirmed_default_1to1` | SETS | EA | 15 (residual, not in 156-set ban đầu) |
| `factor_missing` | EA | EA | 2 (same-UoM factor_missing — weird) |
| `factor_missing` | G | EA | 1 (gram outlier) |
| `unconfirmed_default_1to1` | Chai/Lọ/Tuýp | EA | 1 (Vietnamese token đa nghĩa) |

## Decisions

1. **Catalog fix over override** for the 440 btp_sx — chose root-cause
   over workaround. Memory rule: "fix underlying issue rather than
   bypassing safety checks" + `feedback_no_derived_in_source` lean.
2. **Insert mass overrides directly** for 3 thép tấm/dây hàn —
   evidence from M16 + dimensional reasoning sufficient; no need to
   wait on Johnson confirmation.
3. **Bidirectional synonym requires bidirectional override rows** —
   data model treats `from_uom → to_uom` as directed; agency confirm
   "EA = SET" must produce BOTH `EA→SETS` AND `SETS→PIECES` overrides
   per affected code, depending on each code's catalog uom mode.

## What didn't work

- **First materialize run** unexpectedly created 6,274 new shallow+
  full_flat artifacts (raw_graph deficit pre-existing). User asked
  ahead but I did not catch this scope explosion before running. Net
  result coherent, but I should have done a dry-run first.

- **Polling background tasks** — multiple times tried to peek
  intermediate output (got blocked by sleep guard); waited for
  notification each time as designed.

- **First pg_restore on demo lost all big tables** (materials,
  bcct_rows, bom_artifacts, bom_artifact_rows). Symptom: "33 errors
  ignored on restore" with cryptic FK constraint failures and
  "relation hub.materials does not exist" for every dependent. Root
  cause was earlier in the chain: `materials.description_embedding` is
  `vector(1536)`, and `DROP SCHEMA hub CASCADE` on demo had dropped
  the `vector` extension (which lived in hub schema on demo). Restore
  couldn't create the column type, so CREATE TABLE silently failed
  and every later dependent failed too. Fixed by explicitly
  `DROP EXTENSION vector CASCADE; CREATE EXTENSION vector WITH SCHEMA
  public` BEFORE re-running `pg_restore`. Lesson: `pg_dump --schema`
  does NOT include extensions; verify extension presence + location
  on destination before restoring.

- **`--data-only` retry** between fresh DROP and successful re-restore
  caused 60 duplicate-key errors (background_jobs, deployment_config
  seed rows already populated). Burned a few minutes diagnosing
  before realizing the right path was a full clean restart.

## Open items

1. **39 codes drift unresolved** — 5 buckets per table above. 20
   SETS→SETS most suspicious (same-UoM shouldn't drift).
2. **Cross-repo**: bug fix `d7508ef` doesn't touch consumer code (CO/
   BCQT read catalog uom). Schema unchanged. CO consumer transparent.
3. **Stakeholder demo readiness**: demo box hot at
   `ttdatahub.tinsu.ai` with full Johnson + Growatt data. Smoke path
   for next walkthrough documented in STATUS Next Steps.

## Files touched (in commit `d7508ef`)

- `scripts/fixup_johnson_btp_sx_after_bom.py` — 1 SQL clause + comment
- `tests/test_fixup_johnson_btp_uom.py` — 3 tests + module docstring

## Data changes (NOT in any commit — local DB only)

- 440 `hub.materials` rows: uom KG → EA + provenance note
- 159 `hub.client_uom_overrides` inserts (3 EA→mass + 156 EA→SETS)
- ~9,000 `hub.bom_artifacts` re-derived via 3 materialize passes;
  ~6,000 `bom_artifact_rows` got `applied_uom_factor` populated.

## Verification

- Tests: `tests/test_fixup_johnson_btp_uom.py` 3/3 PASSED
- DB state checks (catalog, overrides, stale count) — all queried
  and verified post-each-step.
