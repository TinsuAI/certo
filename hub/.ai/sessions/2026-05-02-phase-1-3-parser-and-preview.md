# Session: 2026-05-02 — Phase 1+2+3 (parser bug fixes + universal preview + LLM fallback)

Three-phase autopilot run continuing the prior Tier 1 real-data smoke
(`2026-05-02-tier-1-real-data-smoke.md`). 4 commits + ~2,400 LoC. All
done in one continuous session: /discover → /rev → /tdd → fix → UI smoke
+ screenshots → /rev → commit, repeating per phase.

## What was done

### Pre-work — feature brief + 2 critic reviews

- `/discover` produced `.ai/features/2026-05-02-universal-preview-and-parser-fixes.md`.
  Captured 3-phase scope, decisions (drop pass-2 entirely, leave cache
  orphans, universal preview applies to BCCT all-NEW too), risks, open Qs.
- 1st critic round flagged: alias-aware row scoring fragile on edge sheets,
  pass-2 substring is structurally unsafe (not just empty-cells), `_cat_from_sheet`
  BTP/TP collision (Bug D, new), drop pass-2 needs an audit before shipping.
- 2nd critic round on hybrid (rigid + LLM) plan flagged: LLM laundered Bug A
  into "confirmed" cache because file_signature is computed from header_row
  output. Pivoted back to deterministic-first.
- Synthesis: rigid fix → universal preview → LLM as second-tier escape hatch.

### Phase 1 — rigid parser fixes (commit 338be91)

`tests/test_real_data_external.py`: 5 xfails converted to positive assertions
with regex-shape guard (`^[A-Z]{1,4}\d+\.[A-Z0-9]+`) catching Bug C garbage
that count-only checks miss. Suite went red as expected (TDD red step).

`scripts/audit_pass2_deps.py`: instruments `index_headers` to record every
pass-2 substring match across the full real-data + fixture corpus. Output:

| Module  | Field        | Alias            | Real header matched          |
|---------|--------------|------------------|------------------------------|
| bcct    | line_no      | `'line'`         | `line no` (Do Thanh × 6)     |
| bcct    | invoice_ref  | `'invoice'`      | `invoice ref` (Do Thanh × 6) |
| bcct    | total_value  | `'value'`        | `customs value` (Do Thanh × 6) |
| bom     | qty_per_unit | `'comp qty'`     | `comp qty cun` (Johnson SAP) |

These 4 production deps were promoted to explicit pass-1 aliases.

`app/parsers/_excel.py`:
- `header_row()` rewritten to take optional `aliases=None` kwarg. When passed,
  scores each candidate row by `len(index_headers(row, aliases))`; picks the
  row with most matches if ≥`min_alias_matches=2`; earliest row breaks ties.
  Falls through to non-empty-count fallback when threshold not met or aliases
  is None — backwards-compatible with callers that don't pass aliases yet.
- `index_headers()` pass-2 substring matching DROPPED entirely. Pass-1 exact
  match only, with `if not h or not target: continue` guard.
- All 6 callers (bcct + bom × 3 profiles + code_mappings + materials) updated
  to pass aliases.

`app/parsers/code_mappings.py`: added `Mã ERP` / `Mã NPL/TP` aliases (Bug B);
fixed `_cat_from_sheet` BTP-before-TP order (Bug D).

UI smoke: 6/6 jobs match expectation. DB confirmed:
- Growatt 2900 BQD mappings + 293 BOM versions / 23,897 rows / 212 distinct products
- DKE 242 BQD mappings (NEW from Bug B)
- Johnson 2 BOM versions
- Real codes: `B700.0192500`, `ST06.0018700`, `DV01.D401720` — no garbage.

### Phase 2 — universal preview-confirm pattern (commit 359ebec)

Every upload (BCCT/BOM/BQD/Catalog) now: parse → stash to `upload_pending`
→ preview UI (sample rows + counters) → staff confirms or rejects → ingest.
Eliminates the "rigid happy path skips preview" gap on BCCT all-NEW and
extends the pattern to the 3 modules that had no preview today.

**BOM/BQD/Catalog (new):**
- 3 new POST routes per module: `/preview/{id}/confirm` + `/preview/{id}/reject`
- 3 new GET preview routes rendering module-specific templates
- 3 new templates with sample rows + counters + Lưu/Reject/Quay-lại-sau
- Module-specific summary panels (BQD: 1-to-N count; Catalog: category /
  status breakdown; BOM: top 5 products × 4 rows each, grouped — guards
  against flat-sample hiding wrong product_code mapping per /rev finding)

**BCCT (changed):**
- `_ingest_rows` now stashes for preview unconditionally (not just on
  diff/orphan). Closes the all-NEW bypass gap.
- `bcct_upload_preview.html` grew an all-NEW branch (different heading +
  no diff/orphan tables; just sample-row preview). Existing
  confirm-on-update flow + 13 unit tests in `test_bcct_confirm_flow.py`
  unchanged (all internal — don't go through the route).

**/rev fixes applied before commit:**
1. **Critical** — BOM partial-commit: original code DELETEd pending +
   flipped parse_status BEFORE the create_version loop. If a version
   creation failed mid-loop, pending was gone, partial state. Reordered:
   load pending → create all versions → only then DELETE + flip status.
2. `expires_at > now()` guard added to all confirm SELECT/DELETE WHERE
   clauses (previously relied on lifespan-time purge alone).
3. All confirm/reject endpoints now use `connect(user_id=user.user_id)`
   for symmetric audit-attribution plumbing (defensive — no triggers on
   these tables today).
4. CSS classes: `banner banner-success/warning` don't exist in app.css;
   replaced with existing `toast / toast-error`.

UI smoke: 9/9 jobs match expectation (added BCCT manual_test fixture).

### Phase 3 — LLM fallback for BOM + BQD (commit 5d44b60)

Routes through Phase 2 preview, no separate column-mapping UI. Pattern:
rigid parse fails → cache lookup → LLM proposes mapping → re-parse with
override → stash to upload_pending → preview shows sample rows (staff
eyeballs result) → confirm caches the mapping in `parser_mappings` for
future hits.

**Why route through Phase 2 preview (not BCCT-style 2-stage UI):** BOM has
6 logical fields, BQD has 4. A column-by-column dropdown adds friction
without much value vs. eyeballing sample rows in the existing preview —
which staff has to do anyway as defense against LLM hallucination.

- `app/routes/_llm_fallback.py` (new): module-agnostic helpers
  (lookup_cached_mapping, record_mapping_use, request_llm_mapping,
  cache_confirmed_mapping, headers_per_sheet, sample_rows_first_sheet).
- `app/parsers/{bom,code_mappings}.py`: parsers now accept
  `mapping_override: dict[str, str] | None`.
- `app/routes/{bom,bqd}.py`: upload_submit does rigid → cache → LLM in
  that order. _stash_pending carries used_mapping/file_signature/proposed_by
  metadata into pending.diff_summary. preview_confirm reads it; if
  proposed_by == 'llm_proposed', persists mapping to parser_mappings.

**Manual verification:** built synthetic BQD with English-only headers
('Internal' / 'Customs' / 'Note') that don't match any rigid alias.
Upload → rigid raised → LLM called → returned mapping
`{Internal→internal_code, Customs→customs_code, Note→notes}` → parser
re-ran → 3 rows extracted → 303 redirect to preview ✓.

## Decisions made

- **Drop `index_headers` pass-2 substring matching entirely.** Critic 2 was
  right — `'hq' in 'shq'`, `'code' in 'customs code'`, `'' in target` all
  unsafe. Pass-1 exact + curated alias growth (Bug B style 1-line addition)
  is the safer engineering choice. Audit script ensured no real-corpus
  regression.
- **`header_row(ws, aliases=None)` is backwards-compat.** Optional kwarg;
  fallback to non-empty-count when no row hits `min_alias_matches=2`. All
  6 callers in the codebase now pass aliases; new callers can omit.
- **No cache invalidation migration.** `parser_mappings` was empty at fix
  time (no LLM calls had landed yet). Bug A's signature-change-on-fix
  would orphan rows but they're harmless — `confirmed_at IS NULL` filter
  in cache lookup would skip them anyway. Documented in BACKLOG.
- **Phase 2 universal preview applies to BCCT all-NEW too.** Defense in
  depth against future parser regressions; the 1-click cost is tolerable.
- **BOM partial-commit fix:** load pending without DELETE, create
  versions, ONLY THEN delete. Hash-dedup in `stores.bom` makes successful
  retry idempotent.
- **LLM fallback uses Phase 2 preview, not BCCT-style column-mapping page.**
  Single confirm UI across all 4 modules; less divergence; sample-rows
  preview is the eyeball check that catches LLM hallucination.
- **Test-first per phase.** Phase 1 converted xfails to positive
  assertions (suite went red) before touching parsers. Phase 2/3 used
  Playwright UI smoke as the "test" since pytest TestClient isn't
  patterned in this codebase.

## What didn't work / surprises

- **Initial `header_row` rewrite would have broken edge sheets.** Critic 1's
  "legend row matches 1 alias and beats real header" counter-example forced
  the `min_alias_matches=2` threshold + earliest-row tie-break.
- **Hybrid plan (LLM-first) was worse than rigid fix.** Critic 2 showed
  LLM would launder Bug A into confirmed cache because file_signature
  computes from header_row output. Pivoted to rigid-fix-first.
- **`index_headers` pass-2 also broke on `'hq' ⊂ 'shq'`** — not just empty
  cells. The /rev for Phase 1 caught this; my initial proposed fix
  (`if not h or not target: continue`) was incomplete. Changed to drop
  pass-2 entirely.
- **BCCT route 800+ LoC made me wary of refactor.** Avoided pulling
  parse_mapping_confirm onto Phase 2's preview gate; left it as a noted
  pre-existing gap (LLM confirm bypasses diff-preview). Phase 3 BOM/BQD
  uses the cleaner pattern.
- **Auto-seed `_insert_mappings` import** broke the server when I refactored
  to `_insert_mappings_with_cursor`. Restored the wrapper for seed callers.
- **CSS class `banner banner-success` doesn't exist** — used `.toast` /
  `.toast-error` per the existing pattern. Caught at /rev.
- **First Playwright button selector matched topnav lang-toggle** instead
  of the upload form's submit (multiple `button[type=submit]` on page).
  Scoped to `form[action*='/upload'] button.btn-primary[type=submit]`.

## How to resume

```bash
cd ~/workspace/client/data-hub
# Server probably still up on :8754 (--reload mode). If not:
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload

# Tests
uv run pytest -q                                                 # 104+15skip
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q        # 119/119

# Full UI smoke (regenerates 9 screenshot triples)
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run python scripts/smoke_real_uploads.py

# Audit pass-2 (defensive: re-run when adding new aliases)
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data PYTHONPATH=. uv run python scripts/audit_pass2_deps.py

# Login: admin@data-hub.local / admin123 (role=dev)
```

## Open items rolled forward

- BCCT LLM-fallback `parse_mapping_confirm` bypasses the diff-preview gate.
  Pre-existing — Phase 3 didn't fix because BCCT has its own 2-stage UI.
  Follow-up: route LLM-confirmed parse through `_ingest_rows` (which now
  always stashes for preview) instead of calling `_apply_bcct_rows` directly.
- Duplication: 3 module preview/confirm/reject route trios still ~150 LoC
  duplicated. Defer factoring until 5th customer forces shape change.
- Focused unit tests for `header_row` + `index_headers` edge cases (deferred
  from Phase 1 /rev).
- `normalize_header` caching for BCCT-scale workbooks (deferred from
  Phase 1 /rev — preview path now re-parses, doubling cost).
- `expires_at` guard added to BOM/BQD/Catalog confirm SELECTs but NOT to
  GET preview_view (low priority — purge function clears stale rows).
