# Session 2026-05-08 — BCCT identity + parser-rules + payload promotion bundle

**Outcome:** end-to-end bundle shipped in 14 commits (`046601e..37b8046`).
Suite: 626 pass / 15 skip / **0 fail**. 7 migrations applied (035-041).

## What was done

### Phase 0 — investigation (audit)

User noticed Growatt BCCT has `internal_code` column equal to
`customs_code` for all 666 export rows. Dug into the regex parsing
chain in `app/parsers/goods_name.py`:
- F1 anchor `\)\s*$` too strict — fails on Growatt export shape
  `BIENTAN.17#&...(PV01.0117500)#&VN` because of trailing `#&VN`.
  Result: F1 misses, F3 fallback returns leading prefix
  (= customs_code). 666/666 export rows wrong.
- F1 disjunction `\d{3}\.\w+|[A-Z]{2,}\d{2}\.\w+` too narrow — misses
  `B700.x`, `00G.x` shapes (~14 import rows).
- 778 NULL imports turned out to be correct (F4 dot-prefix marker for
  equipment).
- 524 identity-match imports correct (customs_code IS the agency NVL
  code).
- 75 borderline imports F3-fallback to leading prefix — semantically
  wrong but not catastrophic.

User reframed: "internal_code is just a parsed cache of `goods_name`,
never persist a pure function". Surfaced predecessor brief mig 032's
R4 wording was based on misreading those buggy values as legitimate
"agency ERP codes".

### Phase 1 — design pivots

User dictated three architectural pivots:
1. **Rename `product_identity` → `material_identity`** (resolver scope
   covers TP/BTP/NVL/CCDC; "product" was a leftover from CO's original
   request shape).
2. **Drop `internal_code` column entirely** (denormalized cache of a
   pure regex function over goods_name; runtime compute instead).
3. **Configurable per-client regex via web UI** (not hardcoded patch
   to F1; the right architecture is `hub.client_parser_rules` table
   editable by staff).

Pre-production status (no agency live) licensed hard-cut API breaking
changes for the CO sister app.

### Phase 2 — implementation

**Engine core (Phase 1, commit 046601e)**:
- `app/parsers/client_parser_rules.py` — TDD'd CompiledRule dataclass +
  `evaluate_compiled_rules` (priority-order, capture/reject,
  next_rule/return_null) + `compile_pattern` via google-re2 with
  ReDoS guard + length cap + backreference rejection.

**Schema + sweep (Phase 2, commit 92581fe)**:
- Mig 035: rename column + table + index, drop `internal_code`,
  create `client_parser_rules` + history table + AFTER trigger.
- Module rename `bcct_product_identity` → `bcct_material_identity`
  (5 files + 4 test files + 1 script).
- 14 SQL sites swept to drop `internal_code` from SELECT/INSERT.
- Helper `compute_internal_code(row, *, client)` stub (identity
  short-circuit + None fallback for non-identity).

**Wire + Growatt seed (Phase 3, commit 119927b)**:
- `load_rules` DB layer + module-level cache + `clear_rules_cache()`.
- `compute_internal_code` wired to `evaluate_compiled_rules`.
- Mig 036 seeds 5 patterns for `growatt-vn` (NVL, TP, PCBA, alpha-suffix
  shapes). Verified: 7/7 sample shapes pass including 3 bug shapes.

### Phase 3 — /rev iteration

`/rev` skill flagged 4 findings on commits 046601e..119927b:
- #1 (Important): bcct.html template still referenced dropped
  `internal_code` column.
- #2 (Important): `_attach_material_identity` lazy-fill produced
  degraded `display_code` for rows without `internal_code`.
- #3 (Important deferral): CRUD endpoints + UI not built.
- #4 (Important deferral): `bcct_adapters/` not deleted; drift risk.

Fixed #1+#2 in commit `5e5cb66`:
- Template: drop sort link, render `material_identity.display_code`.
- Resolver: `_resolved.display_code = code` (resolved canonical),
  `_empty_result.display_code = customs_code`.
- `_attach_material_identity`: load client config once, inject
  `compute_internal_code` per row before resolver call (lazy-fill
  parity with ingest path).

Fixed #4 in commit `f6ece41`:
- Engine extension: `extract_all_matches_from_compiled` (multi-match
  via finditer for Stage 2 candidates).
- `CompiledRule` gains `notes` field (rule.notes flows to
  `evidence.match_rule`).
- Resolver Stage 2: `adapter.parse_candidates(row)` →
  `_stage2_candidates(ctx, row)` calling rule engine.
- Mig 037 seeds Growatt `material_identity_candidates` rule.
- Deleted `bcct_adapters/{growatt,identity,__init__}.py`.

Fixed #3 in commit `ab09d83`:
- 5 JSON CRUD endpoints under
  `/v1/hub/clients/{id}/parser-rules` (GET/POST/PATCH/DELETE/test).
- UI page `/clients/<id>/parser-rules` with rule list + create form +
  disable button + single-sample test panel.
- Auth: `can_edit_client_technical` (dev role only).
- `clear_rules_cache()` on every write path.
- 11 TDD tests.

### Phase 4 — deferred polish (commit ae77a74)

- GET history endpoint (audit timeline per rule).
- PATCH UI: separate edit page route + template.
- Test panel grows from single-mode to 3 modes (single / recent 50 rows
  / coverage over 1k rows).
- Predecessor brief Amendment 2026-05-08 section (R4 correction).
- Sister-app note `2026-05-08-material-identity-rename-and-internal-code-drop.md`
  for CO + BCQT (6-site audit, before/after diffs, CI gate).

## Decisions

- **Pre-production hard cut on CO sister app**: brief D8/D9 chose to
  break CO consumer simultaneously with Data Hub mig deploy, rather
  than carry alias debt. CO has 6 read sites updated in the
  sister-app note.
- **Display_code semantic**: `resolved_code` when resolved,
  `customs_code` fallback. Decoupled from row's `internal_code` so
  lazy-fill matches ingest output.
- **Soft-disable only, never DELETE**: rules table follows memory
  `project_bom_immutable_principle.md`. Audit trigger keeps every
  insert/update/delete in `client_parser_rules_history`.
- **`evidence.matched_text` includes parens**: full regex match span
  (more informative) vs bare capture group (= product_code, redundant).
- **`parser_adapter` becomes constant**: `"client_parser_rules"`. Per-rule
  semantics flow via rule.notes → evidence.match_rule.
- **Cache invalidation wholesale, not per-key**: simpler; rule edits
  are rare. Could optimize later if perf demands.

## Things that didn't work / had to revert

- Tried to delete `bcct_adapters/` in Phase 2 — broke resolver Stage 2
  immediately. Restored, deferred deletion to #4 fix.
- First Stage 2 rule pattern `\((\w+)\)` rejected real codes like
  `PV01.0117500` because `\w` doesn't match `.`. Fixed seed pattern
  to `\(([A-Z]{2,}\d{2}\.[A-Za-z0-9._\-]+)\)`.
- Initial test fixture passed `internal_code="BIENTAN.17"` reflecting
  the buggy state. Updated to use computed value (PV01.0117500) post-fix.

## Phase 5 — mid-session pivots driven by user feedback

After the original brief was committed, user raised 4 architectural
issues during verification:

### Issue 1: row 308416454160-3 — Stage 1 too eager

User clicked into a Growatt export row and saw display_code =
BIENTAN.20 (the customs prefix), not PV02.0228801 (agency BOM code
in goods_name parens). Investigation: both codes were in materials
catalog but Stage 1 fired first, returning customs_code as resolved.

**Fix (commit `a41f84e`)**: swap stage order in
`resolve_material_identity`. Stage 2 (paren-extract) goes first;
Stage 1 falls through. Identity-mode clients (no rules) naturally
fall through to Stage 1.

### Issue 2: per-row inspect view request

User wanted a way to see all fields per row including computed ones
+ visual marker distinguishing computed from raw DB columns.

**Fix (commit `6a31fc9`)**: extend `/clients/<id>/bcct/history/<txn>/<line>`
into a full inspect page with two sections:
- "Trạng thái hiện tại" — all 35 raw row columns + computed fields
  (internal_code, full material_identity jsonb expandable).
- "Lịch sử thay đổi" — original audit events table.

UI markers: header gets `ƒ` (math-function symbol) with tooltip;
cell gets italic + opacity + tooltip showing `resolution_source`.

### Issue 3: row 308382318920-1 — currency=USD with VND amounts

User caught a Johnson export with `currency=USD` and
`total_value=57,456,231.43` — USD doesn't have those magnitudes.

Root cause: parser ALIASES conflated FX-domain ("Đơn vị tiền tệ",
"Trị giá NT", "Đơn giá") with VND-converted ("Đơn giá tính thuế",
"Tổng trị giá") into single fields. Stored VND amounts but tagged
with FX currency. ~70k rows affected.

**Fix (mig 039 + 040 + 041, commits `932ea10` + `db0f1ef` +
`37b8046`)**:
- Phase 1 (Tier 1): rename `currency` → `currency_nt` (FX
  semantic). Add `total_value_nt`, `unit_price_nt`, `total_tax`,
  `unloading_location` typed columns. Backfill from payload jsonb.
  Parser ALIASES split FX vs VND.
- Phase 2 (Tier 2): add `contract_no`, `contract_date`,
  `internal_mgmt_no`, `package_marks`. Same backfill pattern.
- Phase 3 (prune): drop 38 typed-already keys from payload jsonb
  (~2.86M jsonb entries removed across 75k rows). Parser
  `payload` build now skips `typed_indices`.

User's framing: "lôi hết đống trong payload ra bên ngoài thành các
cột" — payload should only carry data NOT extractable to typed
columns. Aligns with the same principle as mig 035/038 (no
duplicate-cache).

**Field semantic post-mig 039**:
- FX-domain: `currency_nt`, `total_value_nt`, `unit_price_nt`.
- VND-domain (taxable): `total_value`, `unit_price`, `total_tax`,
  `exchange_rate`.

Bug user reported now resolved: row 308382318920-1 has
`currency_nt=USD`, `total_value_nt=2114.10` (FX), `total_value=57.4M`
(VND). Domains explicit + consistent.

## Open items (carry to next session)

1. `git push origin main` — 22 commits ahead.
2. **CO consumer migration session** — sister-app note has detailed
   migration steps for ALL changes (rename, drops, currency split).
   CO's `data_hub_client.py` reads at 6+ sites need updating;
   `payload->>'Tên doanh nghiệp'` etc. must switch to typed columns.
3. Wipe + ingest fresh Growatt + Johnson (memory
   `project_reingest_pending.md`). Now triple-unblocked: rule engine
   works, FX/VND domains split, payload pruned. Next ingest will
   produce clean rows from scratch.
4. **BACKLOG** — 3 scripts that lost SQL `material_identity` access
   (settlement_resolver, detect_dual_source_btps, agent/tools).
   Need Python-side `compute_internal_code()` rewrites.
5. Optional polish:
   - Playwright E2E for parser-rules UI.
   - Per-key cache invalidation in `client_parser_rules` engine.
   - preview_token belt-and-suspenders on rule writes.

## Memory updates needed

Defer to next session per brief D12 — write memory after dev
behavior verified across a few sessions. Candidates:
- `internal_code` + `material_identity` columns gone; runtime-derived.
- Hardcoded growatt regex replaced by `hub.client_parser_rules`.
- BCCT field semantic split: FX (`*_nt`) vs VND domains.
- Resolver Stage 2 (paren-extract) wins over Stage 1 (customs).
- Payload jsonb now sparse; typed columns are source of truth.
