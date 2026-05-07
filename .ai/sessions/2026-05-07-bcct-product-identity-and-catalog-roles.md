# 2026-05-07 PM — BCCT product identity resolver + catalog roles refactor

**Predecessor:** `2026-05-07-rename-and-phase-3.md` (this morning's vocab
rename + Phase 3 work).
**Topic:** Two large API features for sister-app consumption (CO + BCQT).
**Commits:** 7 (commits `2d73cf0..7792cdd`).

## What Was Done

### Feature 1 — BCCT product identity resolver (3 commits)

**Source:** CO API request `~/workspace/client/barry-CO-main/.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md`.

**Brief:** `.ai/features/2026-05-07-bcct-product-identity/brief.md`.

**Shipped:**
- `mig 032` — `bcct_rows.product_identity` jsonb column +
  `bcct_product_identity_review` audit table.
- `app/resolvers/bcct_product_identity.py` — pure 5-stage resolver
  (structured_field → goods_name_embedded_code → reviewed_line_mapping →
  code_mapping_candidate → missing). `ResolverContext.from_db` builds
  per-request memoized state.
- `app/parsers/bcct_adapters/{__init__,identity,growatt}.py` — adapter
  registry with Growatt regex `\(([A-Z]{2,}\d{2}\.[A-Za-z0-9._\-]+)\)` for
  paren-extracted BOM codes from goods_name.
- Wired into `_insert_bcct_with_cursor` for ingest-time persistence.
- Additive `product_identity` field on `/v1/hub/bcct` +
  `/v1/hub/bcct/invoice-matches` with `include_product_identity` +
  `product_identity_candidate_limit` query params.
- Lazy-fill at read for legacy NULL rows (no write-back).
- `scripts/resolve_bcct_product_identity.py` backfill (default skip-resolved,
  `--recompute`, `--dry-run`).
- Sister-app note `2026-05-07-bcct-product-identity-shipped.md`.

**Generalization (during /discover):** Original CO request was BOM-only
(`bom_product_code`). User flagged BCQT/NVL imports also need this.
Generalized to "canonical material/product identity for any kind"
(TP/BTP/NVL/CCDC). Output adds `resolved_code` (any kind) + retains
`bom_product_code` as conditional alias (set only when material has alive
BOM — preserves CO's existing `if bom_product_code: load_bom` logic).

**Tests:** +28 (13 resolver core + 4 ingest + 7 API + 4 backfill).

### Feature 2 — Catalog roles refactor (2 commits + 2 round-2 fixes)

**Brief:** `.ai/features/2026-05-07-catalog-roles-refactor/brief.md` (rev 5
after 3 review passes — first 2 caught real bugs, round 3 surfaced TP1-TP3
which got fixed; user flagged round 4 paralysis and we shipped).

**Triggered by:** BCCT identity resolver returns single `product_kind` from
`materials.category`. User: catalog single-value category is too rigid;
codes can play multiple roles (rework / cải chế per memory).

**Shipped:**
- `mig 033` — `hub.v_material_roles` SQL view deriving observed-role
  signals from data graph: atomic (`has_imports`, `has_exports`,
  `is_consumed_in_bom`, `has_own_bom`) + derived `observed_roles[]` +
  `is_multi_role` + `declared_observed_conflict`.
- ResolverContext.from_db joins view; resolver response carries new
  fields top-level (full set) + per-candidate (minimal: product_kind,
  observed_roles, bom_artifact_count, latest_flatten_status).
- `/v1/hub/materials*` exposes full role field set.
- `app/routes/catalog.py:_query_materials` inline subqueries replaced
  with view JOIN. is_dual_source heuristic kept (auto-detect badge,
  distinct from operator-confirmed btp_sourcing dropdown — D11).
- Catalog UI: declared category primary badge + observed_roles secondary
  chips + integrity-conflict warning.
- Sister-app note `2026-05-07-catalog-roles-shipped.md`.

**Round-2 fix #1 — mig 034 (NVL relax + declaration_type filter):**
User flagged 007.0081700 case: 1 E11 import, declared NVL, but
`observed_roles=[]` because old rule required `is_consumed_in_bom`.
Relaxed: `nvl ⟸ has_nvl_import AND NOT has_own_bom`. New atomic signal
`has_nvl_import` filters import declaration_types to canonical NVL set
{E11, E15, E21, E23, E31, E33} per QĐ 1357/QĐ-TCHQ. Excluded: E13
(mixed), E41 (TP), A-series (commercial), G-series (temporary).

**Round-2 fix #2 — UI rework + BOM-only fallback:**
User flagged dropdown UX confusing + tooltip generic. Rework:
- Tách `Nguồn cung BTP` thành cột riêng (giữa Khai báo và Quan sát).
- Dropdown options Vietnamese đầy đủ ("Tự sản xuất nội bộ (có BOM
  riêng)" v.v.) + label "BTP này có nguồn từ đâu?".
- Click ✎ icon to expand inline (default hidden).
- Observed cell shows atomic-signal hint "↓ nhập (chưa khớp role)" when
  there's BCCT activity but role rule doesn't fire. Tooltip per-code
  specific instead of generic.

Also caught regression: catalog roles refactor (commit `962a9cd`) silently
dropped 17 BOM-only product codes from resolver lookup (Growatt's
PV01.0117500 — spec golden case — broke because it has BOMs but no
materials registry entry). Fix: `from_db` backfills BOM-only products
with synthesized catalog entries (`category='tp'`, `has_own_bom=true`,
`observed_roles=['tp']`).

**Tests:** +30 (21 view + 5 resolver-roles + 4 API). After NVL relax:
+4 declaration_type filter tests. Total 606 pass.

### Sister-app coordination

- Both notes committed in `.ai/sister-app-notes/`.
- CO migration prompt staged at
  `~/workspace/client/barry-CO-main/.ai/sister-app-prompts/2026-05-07-data-hub-product-identity-migration.md`.

## Decisions Made

**D1 (BCCT identity scope expansion):** Generalized resolver to materials
catalog instead of BOM-only. Added `resolved_code` field; kept
`bom_product_code` as conditional alias to preserve CO consumer logic.

**D2 (catalog roles model):** Hybrid — declared `category` stays as
operator intent (auditable); view-derived `observed_roles[]` shows
data-graph truth. Two semantics, named correctly. Don't auto-edit
declared based on observed.

**D3 (D11 — keep is_dual_source AND btp_sourcing):** Round-3 review
proposed dropping is_dual_source heuristic. After investigation, they
serve distinct pipeline roles: is_dual_source = auto-detection badge
(visual hint for staff); btp_sourcing = operator-confirmed dropdown
(drives BOM resolver). Detection→confirmation pipeline, not duplicates.
Keep both, document the relationship.

**D4 (NVL rule rev 3):** Final form `nvl ⟸ has_nvl_import AND NOT
has_own_bom`. Filter by canonical NVL declaration_types per QĐ 1357.
Two earlier revisions had bugs (rev 1 flagged every TP as btp_sx; rev 2
contradicted domain semantic). Rev 3 verified domain-correct.

**D5 (BOM-only fallback):** Resolver synthesizes virtual catalog entries
for BOM-only codes (in `bom_artifacts` but not `materials`) so spec
golden case still resolves. CO contract unchanged — `bom_product_code`
still set as before. Bootstrap script to close data gap added to backlog.

**D6 (5-commit split for the original 5 commits):** Required temporarily
reverting bcct_product_identity.py + api.py to their pre-catalog-roles
state for commits 2-3, then restoring for commits 4-5. Each commit
internally consistent (no broken intermediate state).

**D7 (cap reviews at 2 passes — feedback memory):** User pushback after
round 4: "vai lon, kieu nay phai review den luc nao nua?". Saved
`feedback_review_depth.md`. Distinguishes concrete bugs (always fix)
from speculative findings (defer to BACKLOG after round 2).

## What Didn't Work

- **Iterative review loop (4 rounds on catalog-roles brief)**: rounds 3-4
  found progressively smaller issues + I introduced new bugs while
  fixing earlier ones (rev 2 of D4 contradicted itself). User pushed
  back. Lesson saved to feedback memory.

- **Strict NVL rule (mig 033 first version)**: required
  `is_consumed_in_bom`. Production data revealed 007.0081700 imported
  via E11 wasn't classified — staff regularly imports raw materials
  before the BOM of the consuming TP is uploaded. User caught it.
  Mig 034 relaxed.

- **Initial dispatcher hardcoding `code_resolution_mode == 'growatt'`**:
  Real Growatt clients have `code_resolution_mode='batch_aggregate_resolution'`,
  so the Growatt adapter never fired in production. Caught during live
  testing on port 8754. Fixed by mirroring `internal_code_parser_for`
  convention (mode='identity' → identity; everything else → Growatt).
  Test gap that hid the bug: ingest fixtures used 'growatt' literally.

- **Catalog roles refactor silently dropped BOM-only codes**: ResolverContext
  changed from `bom_product_codes` set (lookup against bom_artifacts.product_code)
  to `material_catalog` (materials.customs_code only). 17 Growatt codes
  with BOMs but no materials entry — including PV01.0117500 spec golden
  case — stopped resolving. Caught during round-2 thorough testing.
  BOM-only fallback added in commit `7792cdd`.

- **D11 first take (drop is_dual_source)**: Naive equivalence to
  btp_sourcing. After investigation, they serve different pipeline roles.
  User caught it; brief D11 reverted to "keep both with clear semantic
  separation".

## Open Items

- **PUSH** — 8 commits ahead of origin/main. Demo CI/CD waiting.
- **CO migration** — prompt staged in CO repo's `.ai/sister-app-prompts/`.
  Awaits CO session.
- **BCQT migration** — note posted but no prompt staged. Defer until
  CO migration proves contract.
- **Wipe + ingest fresh** (Growatt + Johnson) — pending user trigger.
  Per memory `project_reingest_pending.md`. Now that all role/resolver
  features shipped, this is unblocked.
- **Bootstrap script for materials registry**: 17 Growatt codes
  (BOM-only, not in materials). Eliminates need for resolver fallback
  long-term.
- **Phase 3a btp_sourcing scope expansion**: classifier currently
  iterates only `category='btp_sx'`. Codes mistakenly declared NVL but
  structurally purchased BTPs don't get `btp_sourcing` set →
  `observed_roles=['nvl'] + btp_sourcing IS NULL` is NOT a guarantee
  of pure NVL. Documented in sister-app note as known limitation.
- **Materialized view promotion** if catalog endpoint p95 > 500ms.
  Plain view measured 100-150ms on Growatt + Johnson; deferred.
- **For non-DNCX clients (regular SX domestic / commercial trade)**,
  A12 may carry NVL semantics — current `has_nvl_import` filter is
  DNCX/DNSXXK-tuned (E-series only). Per-client declaration_type
  whitelist override → backlog.

## Sister-app coordination state

| Repo | Status |
|---|---|
| Data Hub | 8 commits ahead of origin/main, not pushed |
| CO `barry-CO-main` | Prompt staged at `.ai/sister-app-prompts/2026-05-07-data-hub-product-identity-migration.md` |
| BCQT `BCQT-System` | Sister-app note posted, no prompt staged yet |

## Key facts the next session needs

- **Spec golden case** verified live: BIENTAN.17 (with `(PV01.0117500)`
  in goods_name) → `resolved_code=PV01.0117500`, `product_kind=tp`,
  `observed_roles=['tp']`, `bom_product_code=PV01.0117500` (alias set
  because PV01.0117500 has alive BOM artifacts).
- **Real-data resolution**:
  - Growatt: 22,333 / 23,080 = 96.8% (NVL relax: +228; BOM-only fallback: +133)
  - Johnson: 52,172 / 52,224 = 99.9%
- **Multi-role on Growatt**: 1 code (PV01.0104300, declared btp_sx,
  observed=['tp','btp_sx']) — canonical rework example.
- **Conflicts on Growatt**: 0 (catalog already aligned with observation).
