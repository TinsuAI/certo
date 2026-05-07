# Feature: Catalog roles — multi-role first-class

**Date:** 2026-05-07 (brief rev 5 — D11 corrected: is_dual_source and btp_sourcing serve distinct pipeline roles, both kept)
**Memory refs:** `project_bom_code_multirole.md`, `project_bom_3_shapes.md`
**Triggered by:** BCCT product identity resolver (`.ai/features/2026-05-07-bcct-product-identity/brief.md`) returns single `product_kind` from `materials.category`. User flagged the catalog model itself is too rigid — codes can be TP+BTP+NVL simultaneously (rework / cải chế). Resolver-side flag surfacing papers over the model.

## Scope

**In:**
- New SQL view `hub.v_material_roles` deriving observed-role signals from data graph (BCCT direction patterns + BOM membership).
- New top-level fields surfacing observed-role atoms + derived `observed_roles[]` to API consumers (CO, BCQT, BCCT product_identity).
- Update `app/resolvers/bcct_product_identity.py` to expose new fields + retain `product_kind` (declared primary).
- Update `/v1/hub/materials` + `/v1/hub/products` API to include observed-role signals.
- Update catalog UI to render observed-role chips next to declared category badge (already partially computed inline at `app/routes/catalog.py:_query_materials` line 489+ — promote into view).
- Tests pinning role derivation rules + integrity-conflict detection.

**Out:**
- Replacing or removing `materials.category` — stays as agency-declared primary.
- Auto-editing existing `category` values based on observed roles (would silently change BOM resolver Phase 3 stop-set semantics).
- BCQT consumer migration (separate sister-app work, after this lands).
- New write API for operator role override (defer to future).
- Backfill of pre-feature `bcct_rows.product_identity` snapshots (pending wipe + ingest fresh covers it).

## Decisions

**D1. Hybrid schema: `category` (declared primary) + derived view of observed signals.**
- Keep `materials.category` text NOT NULL as today. It's the agency-declared label, drives catalog UI primary badge + BOM resolver stop-set.
- Add `hub.v_material_roles` SQL view exposing per (client_id, customs_code):
  - **Atomic signals** (separate booleans, not nested):
    - `has_imports`        — appears in BCCT direction='import'
    - `has_exports`        — appears in BCCT direction='export'
    - `is_consumed_in_bom` — appears as child_code in some product's bom_edges, joined to alive bom_artifacts
    - `has_own_bom`        — owns ≥1 alive bom_artifact (META-signal, NOT a role — see D4)
  - **Derived field**:
    - `observed_roles[]` — array of {tp, btp_sx, nvl} computed from atomic signals per D4 rules
- Resolver + API expose both: `product_kind` (declared, single value) + atomic signals + `observed_roles[]` (derived array).
- Why hybrid over `roles[]`-only column: declared label is operator intent (auditable, history-preserved). Observed roles change as data changes — derived is correct. Two semantics, named correctly.

**D2. Plain view (not materialized) for v1.**
- Per-client materials cardinality: max ~11k (Johnson). View subqueries scan BCCT (indexed by client_id, direction) + bom_edges → bom_artifacts (indexed). Per-client query bounded.
- Plain view = realtime (recomputed each query). No REFRESH discipline.
- Defer materialization until catalog endpoint p95 > 500ms; backlog item if needed.

**D3. `observed_roles[]` enum: `tp` | `btp_sx` | `nvl`. Drop `btp_nm` and `ccdc` from observed.**
- `btp_nm` (BTP nhập mua = purchased BTP) cannot be derived from BCCT/BOM data alone — distinguishing purchased vs self-produced BTP requires the dedicated `btp_sourcing` column (Phase 3a).
- `ccdc` (công cụ dụng cụ = tools): structural signature (imported, not consumed materially) overlaps with `nvl`; cannot be derived. Declared-only.
- Observed roles are deterministic functions of BCCT direction + BOM membership only. The 3 mappable kinds are sufficient; the other 2 stay in declared-space.

**D4. Derivation rules** (codified in view) — **REV 3 after domain-correctness review**:

Domain semantics anchor (corrected per user feedback):
- **NVL** = vật liệu phải BỊ TIÊU THỤ trong BOM. Code chỉ import mà không consumed thì không phải NVL — có thể là CCDC, unused stock, hoặc data error.
- **BTP_SX** = sub-assembly có internal decomposition (own BOM) AND consumed in some parent product's BOM.
- **TP** = finished product exported.

```
'tp'      ⟸ has_exports
'btp_sx'  ⟸ is_consumed_in_bom AND has_own_bom
'nvl'     ⟸ has_imports AND is_consumed_in_bom AND NOT has_own_bom
```

Walk-through of all observable states:

| State | exp | imp | consumed | own_bom | observed_roles | Notes |
|---|---|---|---|---|---|---|
| Pure TP | ✓ | | | ✓ | `['tp']` | Normal finished good |
| Rework TP (cải chế) | ✓ | | ✓ | ✓ | `['tp','btp_sx']` | Multi-role |
| BTP self-produced | | | ✓ | ✓ | `['btp_sx']` | Own BOM + consumed in another |
| BTP purchased no-bom | | ✓ | ✓ | | `['nvl']` | Structurally collapses with Pure NVL — see note below |
| BTP purchased with own BOM (Growatt-derived) | | ✓ | ✓ | ✓ | `['btp_sx']` | |
| Pure NVL | | ✓ | ✓ | | `['nvl']` | Imported leaf consumed in some BOM |
| Imported-unused | | ✓ | | | `[]` | CCDC / pre-production / data error |
| Re-export trader | ✓ | ✓ | | | `['tp']` | Mua bán không transform |
| Trader-also-consumer | ✓ | ✓ | ✓ | | `['tp','nvl']` | Imp + exp + consumed-as-leaf, multi-role |
| Orphan TP | | | | ✓ | `[]` | Pre-production / metadata |

**Structural collapse note:** `BTP-purchased-no-own-bom` and `Pure NVL` are structurally identical from data-graph alone (both: imported + consumed + no own BOM). Observation cannot distinguish them. The distinguisher is Phase 3a `materials.btp_sourcing` column:
- `btp_sourcing IS NULL` (or `'self_produced_only'`) → treat as Pure NVL
- `btp_sourcing IN ('purchased_only', 'dual_source')` → BTP purchased

Consumer logic must read BOTH `observed_roles[]` AND `btp_sourcing` to get full picture.

**Lossy states (signal silently dropped, known limitation):**

The 4-bit truth table has 16 combinations; the rules cleanly capture 12. The remaining 4 lose at least one signal because the structural pattern is ambiguous or contradictory:

| (exp,imp,cons,bom) | Pattern | observed_roles | What's lost |
|---|---|---|---|
| `(F,F,T,F)` | consumed but not imported, no own BOM | `[]` | Phantom child — graph integrity error; consumed signal silent |
| `(F,T,F,T)` | imported + has own BOM, never consumed | `[]` | Pre-production purchased-BTP setup; partial signal |
| `(T,F,T,F)` | exported + consumed, no source | `['tp']` | Phantom source; consumption signal lost |
| `(T,T,F,T)` | exported + imported + has own BOM, never consumed | `['tp']` | imp signal lost (no NVL/BTP fire because not consumed) |

These are either rare integrity errors or transitional states. We accept the signal loss — declared `category` carries the operator-intended kind in these cases. Consumers who need full graph picture should query atomic signals directly, not rely on `observed_roles[]`.

**Critical rule note (rev 1+2 bugs corrected):**
- Rev 1 had `'btp_sx' ⟸ is_consumed_in_bom OR has_own_bom` — flagged every TP as btp_sx (every TP has own_bom).
- Rev 2 had `'nvl' ⟸ has_imports AND NOT is_consumed_in_bom AND NOT has_exports` — contradicted domain (NVL by definition IS consumed) and fired empty for re-export.
- Rev 2 also had `'btp_sx' ⟸ is_consumed_in_bom` alone — flagged Pure NVL as multi-role (NVL is consumed too).
- Rev 3 above is domain-correct after both passes.

`is_consumed_in_bom` = true when child_code appears in `bom_edges` joined to alive `bom_artifacts` (excludes tombstoned). View must spell this out:

```sql
exists (
  select 1 from hub.bom_edges e
  join hub.bom_artifacts a on a.artifact_id = e.artifact_id
  where a.client_id = m.client_id
    and e.child_code = m.customs_code
    and a.tombstoned_at is null
)
```

**D5. `btp_sourcing` (Phase 3a) keeps dedicated column — with caveat.**
- Phase 3a's `materials.btp_sourcing` ∈ {self_produced_only, purchased_only, dual_source} is the only signal that distinguishes btp_sx vs btp_nm. Don't fold into observed_roles.
- Resolver response surfaces it as separate top-level field. BCQT settlement uses `btp_sourcing` to split self-produced vs purchased quantity.

**Caveat (chicken-and-egg dependency):**
Phase 3a classifier (`scripts/detect_dual_source_btps.py`) only iterates over codes already declared `category='btp_sx'`. Codes that are STRUCTURALLY purchased-BTPs but mistakenly declared `nvl` (no fault of resolver — bootstrap classification) don't get `btp_sourcing` set. They keep `btp_sourcing = NULL`.

So when consumer sees `observed_roles=['nvl']` + `btp_sourcing IS NULL`, it's NOT a guarantee of pure NVL — it could also be a misdeclared purchased BTP. Phase 3a coverage assumes catalog declared kind is right. If consumer needs absolute certainty, fix declared category first OR extend Phase 3a classifier to handle declared-nvl scope (out of this brief — backlog).

Document this dependency explicitly in sister-app note for BCQT.

**D6. API exposure — top-level vs per-candidate scoping:**
- `/v1/hub/materials`, `/v1/hub/products` → per-item dict gets ALL new fields: `observed_roles[]`, `has_imports`, `has_exports`, `is_consumed_in_bom`, `has_own_bom`, `is_multi_role`, `btp_sourcing`, `declared_observed_conflict`.
- BCCT `product_identity` response:
  - **Top-level (resolved code)**: full set — atomic signals + observed_roles + is_multi_role + btp_sourcing + declared_observed_conflict + product_kind.
  - **Per-candidate (inside `candidates[]`)**: minimal — `product_kind`, `observed_roles[]`, `bom_artifact_count`, `latest_flatten_status`. Atomic signals NOT propagated to candidates (wire-format too noisy for ambiguous cases with 5+ candidates).
- Catalog UI (`app/templates/clients/catalog.html`) → declared category primary badge + observed_roles secondary chips + integrity-conflict warning chip when applicable.

**D7. `is_multi_role` rule generalizes.**
- Today (catalog.py:529): `is_multi_role = (category=='btp_sx' AND has_exports)`. Hardcoded BTP-only.
- New: `is_multi_role = len(observed_roles) >= 2`.
- Captures rework (TP+BTP), re-export trader (TP+NVL), and any future multi-role pattern uniformly.

**D8. `declared_observed_conflict` — precise rule:**
A code is in conflict iff data-graph activity exists AND declared kind doesn't match observed.
```
declared_observed_conflict =
  len(observed_roles) > 0
  AND declared IN {'tp','btp_sx','nvl','ccdc'}
  AND (declared = 'ccdc' OR declared NOT IN observed_roles)
```
- `btp_nm` declared codes: NEVER trigger conflict — observation cannot distinguish btp_nm vs btp_sx. Phase 3a `btp_sourcing` is the canonical signal there.
- Orphan declared codes (observed_roles=[]): NEVER trigger conflict — no evidence yet.
- Surface in catalog UI as warning chip ("declared CCDC, observed pattern: NVL — verify with operator").
- Don't HIDE observed_roles when declared conflicts — staff need data truth. Explicit flag prevents silent confusion.

Conflict matrix:

| declared | observed_roles | Conflict | Why |
|---|---|---|---|
| tp | [] | ❌ | Orphan TP, not yet transacted |
| tp | ['btp_sx'] | ✓ | Declared TP but only consumed |
| tp | ['tp','btp_sx'] | ❌ | Rework, declared matches |
| nvl | ['nvl'] | ❌ | Match |
| nvl | ['tp','nvl'] | ❌ | Re-export trader, declared still in observed |
| ccdc | ['nvl'] | ✓ | CCDC shouldn't show observable role |
| btp_nm | any | ❌ | Distinguished only by btp_sourcing, not observation |

**D9. Migration: backfill is automatic via view.**
- View computed on-read. No backfill column needed.
- Re-deploy = view replaced atomically. Catalog UI / API immediately see new shape.
- Rollback: drop the view. `materials.category` untouched.

**D10. `product_kind` field stays (don't rename).**
- Just-shipped BCCT product_identity resolver returns `product_kind` from declared category. Don't churn that field.
- Add `observed_roles[]` alongside. Consumer logic:
  - CO: prefers `product_kind` (declared) for origin sheets; checks `is_multi_role` for rework warning.
  - BCQT: combines `product_kind` + `direction` + `observed_roles[]` + `btp_sourcing` for full role inference.

**D11. Keep `is_dual_source` AND `btp_sourcing` — they serve different pipeline roles.**
- `is_dual_source` (catalog.py:526) renders an auto-detected "⇄ dual" visual badge in the catalog table (template line 117-119). Heuristic: `has_imports AND has_own_bom`. Read-only signal computed realtime.
- `btp_sourcing` (Phase 3a column) renders an editable `<select>` dropdown for operator confirmation (template line 124-129). Drives BOM resolver flatten strategy.
- They form a detection→confirmation pipeline:
  ```
  data graph → is_dual_source heuristic (auto badge)
             → operator notices, opens dropdown
             → btp_sourcing (operator-confirmed enum)
             → BOM resolver consumes
  ```
- NOT duplicates. Don't drop either. Document the pipeline relationship in code + sister-app note.
- Implementation impact: `is_dual_source` Python computation in catalog.py:526 keeps working as-is, OR can be migrated to read from view's atomic signals if convenient (same formula, different source). Either way the badge stays.

## Risks

**R1. View performance under load.**
Per-query subqueries scan BCCT + bom_edges. Johnson ~52k BCCT rows, ~340 bom_artifacts. Mitigation: existing indexes (`idx_bcct_customs`, `idx_bcct_direction`, `idx_bom_edges_artifact`) cover join paths. Measure on real data; promote to mat-view if catalog endpoint p95 > 500ms.

**R2. Stale view between writes.**
Plain view always fresh — no staleness possible at the view layer. Persisted snapshots in `bcct_rows.product_identity` jsonb (per BCCT identity D9) can drift; same trade-off as BCCT identity feature, addressed by reset+ingest at MVP.

**R3. CO + BCQT see new fields — backward compat?**
Additive at top level. Existing consumers ignore unknown fields per JSON conventions. Verify CO `data_hub_client.py` + BCQT consumer don't `assert set(keys) == {expected}` anywhere.

**R4. `is_multi_role` rule generalizes; on current data semantically equivalent to old rule.**
Old: `category=='btp_sx' AND has_exports` (rework-only). New: `len(observed_roles) >= 2`. On Growatt + Johnson today, the only multi-role state is rework TP — same code(s) flag under both rules. Expansion adds future coverage of `['tp','nvl']` (trader-also-consumer) — currently zero such codes. So on existing data: operator-visible-zero-change. Future-proof.

**R5. `bom_resolver` (Phase 3) stop-set logic.**
`app/stores/bom.py:483`: `coalesce(m.category, 'tp')` used for shallow walk stop-set (`category in ('btp_sx','btp_nm','tp')`). Doesn't reference `observed_roles`, untouched. Verify pre-merge with explicit regression test that golden Phase 3 BOM resolution case still passes.

**R6. Bootstrap script ordering bug (memory ref).**
Per `project_bom_code_multirole.md`: PV01.0104300 marked `btp_sx` or `tp` depending on which bootstrap ran first. With observed_roles, the truth surfaces regardless of bootstrap order. But the underlying bootstrap-order bug is not fixed here — same backlog.

**R7. CCDC declared codes will surface `observed_roles=['nvl']`.**
A real CCDC import has has_imports=true → observed_roles=['nvl']. Without `declared_observed_conflict` flag (D8), staff would see "declared CCDC | observed NVL" as conflicting badges. With the flag, UI renders integrity warning chip making it intentional.

**R8. View definition change = downtime?**
`CREATE OR REPLACE VIEW` is metadata-only, milliseconds. No downtime. Migration safe inside single transaction.

**R9. `btp_nm` divergence from observed.**
Declared `btp_nm` codes (purchased BTPs) will get `observed_roles=['btp_sx']` if consumed, or `['nvl']` if not yet seen consumed. This is by-design divergence — consumers needing the purchased-vs-self distinction read `btp_sourcing`. Document in CO/BCQT note: "for sourcing decisions, use `btp_sourcing`; for transactional role, use `observed_roles[]`; for declared identity, use `product_kind`."

## Locked decisions (post-discovery 2026-05-07)

- **Q1 → array**: `observed_roles[]` is the canonical field. Atomic boolean signals (`has_imports`, `has_exports`, `is_consumed_in_bom`, `has_own_bom`) are separate top-level fields, not nested.
- **Q2 → snapshot persist**: BCCT `product_identity` persists `observed_roles[]` + signals at ingest time inside the existing jsonb column. Stays consistent with the BCCT identity feature's D9. Catalog endpoints query the view directly = realtime.
- **Q3 → declared primary + observed secondary**: Catalog UI keeps declared `category` badge as primary visual; observed_roles render as smaller chips next to it. Operator intent stays visible.
- **Q4 → separate sister-app note**: This refactor gets its own note distinct from the BCCT identity one. Contract change is independent.
- **Q5 (mat view) → defer**: Plain view chosen for realtime semantics. Promote if catalog endpoint p95 > 500ms (backlog).

## Implementation Plan

**Order:**
0. **Perf sanity check** (BEFORE migration) — write the v_material_roles SELECT, run EXPLAIN ANALYZE on Growatt + Johnson. If any client > 500ms, escalate to mat-view design before continuing. ~15min.
1. **Migration 033** — `hub.v_material_roles` view + comment. Includes alive-only filter on bom_artifacts/edges. Output columns pinned: `(client_id, customs_code, has_imports, has_exports, is_consumed_in_bom, has_own_bom, observed_roles, is_multi_role, declared_observed_conflict)`. ~30min.
2. **Resolver wire-up** — `from_db()` joins view; resolver response gets atomic signals + `observed_roles[]` + `is_multi_role` + `btp_sourcing` + `declared_observed_conflict` at top level; per-candidate gets only `product_kind` + `observed_roles[]` + `bom_artifact_count` + `latest_flatten_status` per D6. ~1h.
3. **API surface + catalog inline replacement** — `/v1/hub/materials` + `/v1/hub/products` include all new fields. Replace inline atomic-signal SQL in `app/routes/catalog.py:_query_materials` (lines 495-513: has_imports/has_exports/has_bom subqueries) with view join. Update Python computation lines 525-531: `is_multi_role` reads from view's `observed_roles[]` per D7; `is_dual_source` keeps formula `has_imports AND has_own_bom` (per D11 — detection-pipeline role, distinct from `btp_sourcing`). ~1h.
4. **Catalog UI** — template renders observed_roles chips alongside declared category + integrity-conflict warning. ~1h.
5. **Tests** — view correctness (one test per row in D4 walk-through table), orphan case (code in materials with 0 BCCT/BOM), resolver regressions (rework code), per-candidate field scope (D6), API field presence, BOM resolver Phase 3 stop-set regression test (R5), CCDC conflict detection per D8 conflict matrix, btp-purchased-no-bom collapses to ['nvl'] (verify Phase 3a sourcing distinguishes). ~2-3h.
6. **Sister-app note** — new file `2026-05-07-catalog-roles-shipped.md`. Document the `observed_roles[]` + `btp_sourcing` dual-read pattern explicitly. ~30min.

**Estimate:** ~6-7h end-to-end.

**Test plan:**
- View row for each of 10 states in D4 walk-through table (synthetic test client). Includes orphan case (0 BCCT, 0 BOM) and trader-also-consumer (`['tp','nvl']`).
- View tombstone-aware (two independent tests):
  - Tombstoning the only consuming bom_artifact flips `is_consumed_in_bom` true → false.
  - Tombstoning the only own bom_artifact for code X flips `has_own_bom` true → false (and may flip btp_sx → not-btp_sx in observed_roles).
- Lossy state regression: confirm the 4 `(F,F,T,F)` / `(F,T,F,T)` / `(T,F,T,F)` / `(T,T,F,T)` patterns produce the documented partial output, no crash.
- Real-data smoke (env-gated): PV01.0104300 verified to have all 3 signals (export=1, consumed=1, own_bom=3, no imports). Real-data assertion pins `observed_roles=['tp','btp_sx']` + `is_multi_role=true`.
- Resolver: rework code top-level fields complete; per-candidate fields minimal per D6.
- D8 conflict matrix: each row gets a fixture + assertion (esp. CCDC+import, btp_nm always-no-conflict, orphan no-conflict).
- API: `/v1/hub/materials?client_id=...&customs_code=X` returns full top-level field set.
- Catalog UI: page render shows declared primary chip, observed secondary chips, conflict warning when applicable.
- BOM resolver Phase 3 stop-set: pin existing golden test in `tests/test_bom_resolver.py` still passes — no behavior change there.
- BTP-purchased-no-bom case: synthetic code with btp_sourcing='purchased_only' AND has_imports + consumed AND no own_bom. Assert observed_roles=['nvl'] (collapses) + btp_sourcing distinguishes downstream.

## Next Step

Brief at rev 4 — third-pass review fixes applied:
- TP1 — Trader-also-consumer (1110) added to walk-through; lossy-state section documents 4 cases where signal is silently dropped
- TP2 — D5 caveat: `btp_sourcing` chicken-and-egg dependency on declared category; consumer logic relaxed to acknowledge `observed_roles=['nvl']` + `btp_sourcing IS NULL` is NOT a guarantee of pure NVL
- TP3 — D11 corrected (rev 5): `is_dual_source` (auto badge) and `btp_sourcing` (operator dropdown) serve distinct pipeline roles, kept separately
- TP4 — Plan step 3 expanded: ALL inline atomic-signal SQL in catalog.py replaced (not just is_multi_role)
- TP5 — Test plan: independent has_own_bom tombstone test + lossy-state regressions
- TP6 — D8 conflict rule simplified (precondition pulled out)
- TP7 — R4 wording corrected: on current data, no operator-visible change; expansion is future-proofing

Ready for `/tdd` if no further questions.
