# Feature: Universal preview-confirm + parser bug fixes + LLM fallback for BOM/BQD

Three phases shipped sequentially. Each phase commits independently; Phase 3 depends on Phase 1.

## Scope

**Includes:**
- **Phase 1 — Rigid parser fixes:** Bug A (header_row picks data row) + Bug B (DKE BQD alias gap) + Bug C (silent empty-cell substring corruption) + Bug D (`_cat_from_sheet` BTP/TP collision). Convert 5 xfails to positive assertions with `strict=True` first. **Includes: pass-2 dependent alias audit + promotion to explicit pass-1 aliases** (validated: `materials.py` bare `"mã"`, `bcct.py` bare `"hs"`/`"line"` rely on substring today).
- **Phase 2 — Universal preview-confirm pattern:** Every upload (BCCT/BOM/BQD/Catalog) goes through preview before commit. BOM/BQD/Catalog get sample-row + counter previews; BCCT keeps richer NEW/UPDATED/DELETED/NOOP diff. `upload_pending` already permits all 4 modules — no schema change.
- **Phase 3 — LLM fallback for BOM + BQD:** rigid fail → cache lookup → LLM propose → unified preview from Phase 2 → confirm caches the mapping. Re-uses `app/llm.py` + `hub.parser_mappings`.

**Explicitly NOT in scope:**
- BOM profile auto-detection (`manual_flat` / `growatt_multi` / `johnson_sap`) — that's row-semantics, not column mapping. Separate problem.
- Multi-sheet `file_signature` enrichment (BQD NVL + TP in same workbook). Documented as known limitation; revisit if a customer hits it.
- Catalog provenance / BCCT staleness / CSRF / manual mapping UI when LLM disabled (all in BACKLOG).
- Diff-vs-DB preview for BOM/BQD/Catalog. Decision (a): sample-row + counter only, append-only/upsert behavior makes diff low-value.

## Decisions

1. **`header_row(ws, *, aliases=None, ...)` keeps default-args backward compat.** All 6 existing callers (`bcct.py`, `bom.py × 3 profiles`, `code_mappings.py`, `materials.py`) keep working without changes; alias-aware scoring activates only when caller passes its alias dict. New callers will pass aliases.

2. **Drop `index_headers` pass-2 substring matching entirely.** Bug C empty-cell guard is incomplete (`'hq' in 'shq'` etc. still wrong). Compensate with curated alias list growth — Bug B already shows that's a 2-line cost per customer.

3. **Cache invalidation for `parser_mappings`: leave orphans, don't migrate.** When Bug A fix lands, files where header_row previously picked the wrong row will compute different `file_signature`. Old rows become unreferenced, harmless — `parser_mappings.use_count` stops incrementing on them. New uploads re-cache under correct signature. No DELETE migration; documented.

4. **Universal preview = always preview, no rigid happy-path bypass.** Rationale: critic warned LLM fallback laundered Bug A into "confirmed" cache. Universal preview gives staff an eyeball check on rigid output too — defense in depth. The 1-click "Lưu" button is one extra click cost; protects against silent corruption forever.

5. **`upload_pending` reused for all 4 modules** (CHECK constraint already permits). For BOM/BQD/Catalog, `parsed_rows` jsonb stores the parsed payload; `diff_summary` jsonb empty for these (no diff). Single confirm endpoint shape per module; templates differ.

6. **BCCT all-NEW uploads now route through preview.** Today BCCT all-NEW uploads (no existing rows to overwrite) skip preview and ingest direct; uploads with UPDATED/DELETED rows already go through `upload_pending` + confirm-on-update gate; LLM fallback uses parse-mapping flow. Phase 2 closes the "all-NEW skips preview" gap by routing those through the existing confirm-on-update template, with all rows in the NEW bucket. Parse-mapping (LLM) flow and confirm-on-update flow are unchanged.

7. **LLM extension entry point per module.** BOM: rigid fail → LLM proposes column mapping (with profile passed in as context); flat output, store mapping keyed by `file_signature + profile`. BQD: rigid fail → LLM proposes 2-column mapping. Phase 2's preview doesn't change; Phase 3 just plugs into the upload-pending → preview pipeline.

8. **Test-first per task.** Convert xfails to assertions BEFORE touching parsers (Phase 1 step 1). Write new test for each Phase 2 / 3 route before route lands.

## Risks

1. **BCCT route refactor risk.** `app/routes/bcct.py` is 800+ lines. Phase 2 inserts a preview step into the all-NEW happy path. **`tests/test_bcct_confirm_flow.py` has 13 test functions, several of which assume rigid happy path = direct ingest; those tests need updating to navigate the preview step.** Allow 2-4h for test update. **Mitigation:** preserve existing routes; add the all-NEW path through the same confirm-on-update gate by populating `parsed_rows` with all rows in NEW bucket and routing redirect to `/confirm/{pending_id}` instead of direct ingest.

2. **GUC plumbing for BCCT audit only.** `connect(user_id=...)` sets `app.user_id` for the BCCT row-history trigger. **Trigger exists on `hub.bcct_rows` only** — `bom_versions`, `code_mappings`, `materials` have no equivalent trigger. Risk applies only when extending audit to other modules; not a Phase 2 blocker.

3. **LLM "confirms wrong mapping" is forever-cached.** Critic raised: BCCT has diff preview that surfaces row-level oddness; BOM has no such guard. **Mitigation:** universal preview ALSO renders sample rows for BOM (same UI as rigid happy-path preview). If LLM mapped `material_code` → wrong column, sample rows in preview show wrong values. Staff must look. Add a "Show 20 sample rows" panel mandatory in BOM preview UI. Same for BQD.

4. **Migration numbering.** Existing 010 → 012 (no 011). Next migration is 014. No new migrations required for this work — every table this needs already exists. Documented to avoid Phase 1/2 reviewers asking.

5. **`compute_file_signature` is sheet-order sensitive.** Doesn't sort sheets, only sorts headers within a sheet. Customers could submit BQD with NVL/TP in either sheet order → cache miss. **Mitigation:** explicit out-of-scope; document in BACKLOG. Revisit if a customer trips on it.

## Open Questions

1. **Universal preview for SUCCESS case in BCCT — does staff actually need to confirm a 0-diff upload?** If user uploads idempotent file (NOOP), all rows match DB exactly — preview shows "0 NEW / 0 UPDATED / 0 DELETED / N NOOP". One-click confirm seems wasteful. **Default behavior:** still require confirm, with prominent "Tất cả khớp DB hiện tại — không đổi gì" banner + 1-click Lưu. Single mental model is worth the extra click.

2. **BOM preview rendering — flatten or group by product?** Real Growatt BOM TP has 50 products × ~4-10 rows. **Default:** top 5 products × first 4 rows each = 20 rows total, grouped visually by `product_code`. Staff sees product diversity at a glance — guards against LLM mapping `material_code` → wrong column landing in cache.

3. **LLM cost cap for BOM specifically.** `hub.llm_usage` tracks per-day per-client usage. BOM workbooks can be large (Growatt TP 963KB). Header sample for LLM prompt is small (header rows + 5 data rows per sheet). Should be fine within existing budget. Document a unit test that asserts prompt size < 4KB for the largest fixture.

## Manual test plan

**Phase 1 verify:**
- `DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest tests/test_real_data_external.py -v` — all 14 cases pass (no xfail).
- Re-run `scripts/smoke_real_uploads.py` — Growatt BOM TP previously errored, now should preview successfully (rigid path, alias-match scoring picks header row 1). DKE BQD added to JOBS list, expect ok.
- **Materials parser smoke:** drive DKE NPL+SP catalog upload through `/clients/dke-vietnam-d0e3/catalog/upload` — DB row count matches parser output (~190 NPL + ~85 SP); no garbage `product_code` (regex match against expected DKE shape).
- **Pass-2 audit verify:** dry-run all 5 parsers (`bcct`, `bom × 3 profiles`, `code_mappings`, `materials`) against the full real-data corpus + `tests/fixtures/manual_test/` with `index_headers` pass-2 disabled — every previously-matching parse must still succeed (alias additions compensate).

**Phase 2 verify:**
- Upload BQD TP → preview shows 73 sample mappings + counter "73 NEW" → click Lưu → list page shows toast "✓ Đã lưu 73 mã quy đổi" + DB count goes up.
- Upload BCCT (idempotent file from data/manual_test/) → preview shows "0 NEW / 0 UPDATED / 0 DELETED / 3 NOOP" + 1-click Lưu.
- Upload BOM Johnson SAP → preview shows 1 product (ASM-001) + 2 sample rows.
- Upload Catalog (any DKE file) → preview shows N material rows + counter.

**Phase 3 verify:**
- Upload DKE BQD `dke/bqd.xls` to Growatt-vn (cross-client misuse) → rigid fails (alias gap relative to that client's expected shape, or actual format mismatch) → LLM proposes mapping → preview UI shows it → confirm caches → second upload of same file goes through cache (no new LLM call).
- Confirm `parser_mappings` row written for `(growatt-vn, bqd, <signature>)` with `proposed_by='llm'`, `confirmed_at` set.

## Done criteria

- All 4 bugs fixed; xfails removed.
- Real-data smoke 14/14 passing (no xfail).
- Pass-2 substring matching dropped from `index_headers`; all 5 parsers + real-data corpus + manual_test fixtures still parse successfully (alias promotion compensated).
- Materials parser smoke driven through HTTP for DKE — no garbage rows.
- UI smoke 5/5 with screenshots, including BOM TP success + DKE BQD via LLM.
- BCCT/BOM/BQD/Catalog all route through `upload_pending` → preview → confirm. No "ingest direct from POST" path remains.
- Preview page renders in <500ms for any fixture in `data/manual_test/`.
- Full pytest suite green.
- `.ai/STATUS.md` + new session log written.
- All 3 phases committed separately (Phase 4 is verification-only, may roll into Phase 3 commit if no new code).

## Recommended next step

`/tdd` for Phase 1 in this exact order:

1. **Convert xfails → positive assertions, strict=True.** Tests must be red-able.
2. **Audit pass-2 dependents.** Compile every header in real-data + fixture corpus that matches today only via substring; promote to explicit aliases.
3. **Drop pass-2 in `index_headers`** (Bug C complete fix).
4. **Run full suite.** Must stay green after pass-2 drop. If anything breaks, the audit in step 2 missed something — return to step 2.
5. **Fix Bug A** (`header_row` alias-aware scoring with min-2 threshold + earliest-row tie-break + non-empty fallback).
6. **Fix Bug B + Bug D** (small, low risk — bundled commit).
7. **UI smoke + screenshots**.
8. **/rev review** + commit.

Step 2 is the load-bearing change. If it's wrong, step 4 fails and Phase 1 stretches into a debugging hunt.
