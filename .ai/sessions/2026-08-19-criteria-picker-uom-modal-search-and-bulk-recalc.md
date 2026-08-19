# 2026-08-19 — Tiêu chí picker, ĐVT modal, tìm NVL đầy đủ, bulk recalc

Six issues reported by the operator (Thanh Tâm) on johnson-vn, from screenshots of
VNG26030079 / VNG26030107. All six addressed; one of them (reading Data Hub's ĐVT
factors) is blocked on a Data Hub contract and stops at an API-request artifact by
project rule.

Client-facing answers (forwardable Vietnamese):
`.ai/feedback/2026-08-19-client-questions-uom-criteria-search.md`.

## What was done

### 1. Tiêu chí cho cả lô — segmented picker instead of `window.prompt`
`initCaseCriteria` opened a native prompt with a free-text box. Free text is not inert:
the engine reads criterion TOKENS (`primaryCriterionToken`, `criterion_family`,
`lvc_threshold_from_criterion`, `tariff_shift_rule_from_criterion`), so a typo landed on
no rule at all while the UI still showed a chosen criterion.

Replaced with a modal that reuses the per-sheet ⚙ Cấu hình markup verbatim —
`[data-criteria-panel]` + `data-criteria-seg` (WO/PE/CC/CTH/CTSH/RVC/LVC/PSR) + `Khác…`
+ the "hoặc" alternates + `[data-criteria-threshold-row]`. `initCriteriaSegments` already
loops every `[data-criteria-panel]` and is null-safe on `costBlock`/`formSel`/`summaryText`,
so the case-level panel wires with **no JS change** to that function; only the save/clear
handlers are new. The threshold posts as `lvc_threshold`, which `attach_origin_sheet_states`
already inherits when `criteria_source == "case"` (`co_case_context.py:1396`).

### 2. No F5 after saving a criterion or a sheet config
New `refreshCaseShellInPlace(fallbackMessage, options)` — fetch the current URL as
`text/html` and hand it to the existing `replaceCaseShellFromResponse`, which already
restores the origin sub-view and re-runs `refreshCaseShellInteractions`. Wired into:
- case criterion save/clear (was `window.location.reload()`),
- per-sheet ⚙ Cấu hình **Lưu** (was a toast and nothing else — this was the actual
  surface in the operator's screenshot) and **Reset** (was a hard reload),
- the ĐVT factor save.

Gotcha found while wiring: `initOriginSettingsModal` MOVES `.origin-config-disclosure`
(and the Save button with it) into the ⚙ modal, while `[data-origin-recommendation]`
(`.origin-config-bar`) stays on the sheet — so `panel.closest("[data-origin-settings-modal]")`
is null. Close through the button instead (`closeSettingsModal`).

### 3. "Bỏ chọn" tiêu chí never worked
`set_case_criteria_route` did `record.pop("criteria_choice")`, but `update_case_record`
copies only keys **present** in the incoming case (`if key in case`, `co_case_store.py:182`
— the whitelist whose own comment says that is how the criterion choice first vanished).
The stored choice therefore survived every clear. Now writes `{}`.

### 4. "Đủ tồn cho tất cả SP" over a sheet list saying "Cần tính lại"
Not a ĐVT bug, contrary to the operator's guess. Stock is allocated sequentially down
`origin_product_order`, so `bulk-substitute` / `bulk-delete-rac` call
`mark_origin_sheets_stale(min(edited_indices))` — every downstream sheet goes stale — and
then recalculated **only `edited_codes`**. The aggregate panel meanwhile runs a fresh
`allocate_whole_case_preview` over the whole case, so it reported đủ tồn.

New `origin_codes_to_recalculate(case, order, edited_codes)` returns every code from
`min(edited index)` onward, minus locked sheets. Used by both bulk routes.

**Adjacent defect found and fixed:** `calculate_all_route` persisted the output of
`allocate_whole_case_preview`, which rebuilds EVERY product (`prepare_case_origin_products`
has no locked skip), and stamped `calculated_sheet_status` on every code — i.e. "Tính tồn
tất cả (SP)" rewrote a locked sheet's filed snapshot and silently unlocked it while the
ledger still held `co_stock_claims` against the old allocation lines. Locked products are
now restored from the persisted case and their status is left alone.

### 5. ĐVT — the real gap is on the Data Hub side
Data Hub johnson-vn holds **516** factors in `hub.client_uom_overrides` (migration 055),
exposed only as an HTML admin page (`app/routes/client_uom_factors.py`) — there is no
`/v1/hub` route. CO keeps its own `co_uom_factor`, empty for this client, so every
cross-quantity pair (EA↔CAY) blocks Chốt even though the agency already answered it.

Per the Data Hub rule in `AGENTS.md`, wrote the contract and stopped:
`.ai/api-requests/2026-08-19-client-uom-factors-read.md`. It pins the direction convention
(`qty(to_uom) = qty(from_uom) × factor` — same as CO's `resolve_uom_factor`, so
`from_uom → bom_uom` with no inversion), decimal-string precision, pagination, and the
consumer plan (merge UNDER `uom_factor_store.factor_map` inside `_uom_factors`).

CO-side interim, shipped:
- the row button reads **"Cần hệ số EA→CAY"** instead of `⇄ CAY?`;
- it opens a modal asking one question ("1 CAY = mấy EA") with a **scope** choice —
  *chỉ mã này* vs *mọi mã có cặp EA → CAY*. The store already supported the client-wide
  row (`material_code=""`); the route just always posted `scope: "material"`;
- new material field `uom_converted`: only `uom_family` / `operator_confirmed` factors
  that are not 1 count as a conversion. Alias pairs (EA/PIECES/CÁI) and unknown units are
  1:1, so the `⇄ PIECES` badge stopped appearing on 145 rows of a Johnson sheet where
  nothing was converted.

### 6. Substitute search returned 20 rows
The picker never sent `limit`, so the route defaulted to 20 (`min(limit, 50)`), and
`build_stock_first_candidates` filtered on a whole-phrase, accent-sensitive substring —
"bu lông" missed "Bộ ốc vít, bu lông…" and "bu long" missed everything.

Now: client sends `limit=200`; route caps at 200; `rank_matches` /
`search_case_material_rows` caps raised to 500; stock-first matching uses the same rule as
`material_search.match_score` (fold accents, split tokens, AND across tokens / OR across
fields). A count line ("N NVL khớp … · mã có tồn xếp trước") sits above the list.

Measured on johnson-vn `co-case-e0b390ead3b0`, sheet MFW0525-39:
`bu lông` 21 → **192**; `bu long` → **192**; `bo oc vit bu long` → **111**; ordering is
tồn-descending (0000093519 · 102.708).

## Verification
- `uv run pytest` — **1127 passed / 17 skipped** (was 1114/17; +13 new).
- New tests: `tests/test_bulk_recalc_downstream_sheets.py` (6), plus additions to
  `test_criteria_choice.py`, `test_uom_conversion.py`, `test_substitute_discovery.py`,
  `test_preview_stock_all_route.py`.
- Browser e2e: `.ai/scripts/e2e_case_criteria_modal.cjs` — ALL PASS against local
  `:8001` on the real johnson-vn case (no native prompt, 8 segment buttons, RVC reveals
  Ngưỡng %, save swaps the shell with the JS context intact, 4 sheet chips inherit
  "theo lô hàng", clear survives F5).
- Screenshots: `.ai/screenshots/2026-08-19-tieu-chi-picker/` (gitignored).

## Decisions
- The case-level criterion modal REUSES the per-sheet markup rather than a second
  component, so `initCriteriaSegments` stays the only place composition logic lives.
- Reading Data Hub factors was NOT implemented from this repo — contract first
  (`AGENTS.md` Data Hub rule). No direct `hub.` schema read, and no `CAY` entry added to
  `_ALIASES`: the Data Hub note says "1 EA = 1 CAY (synonym **in Johnson context**)",
  which is per-client data, not a universal alias.
- Locked sheets are excluded from every recalculation path touched here.

## Open
- `.ai/api-requests/2026-08-19-client-uom-factors-read.md` needs Data Hub approval before
  CO can consume it. Until then the operator confirms cross-quantity pairs once per pair
  in CO.
- Not deployed. Version bumped 0.16.0 → 0.17.0 with a CHANGELOG entry; CD not run.
- `.ai/BACKLOG.md` and `uv.lock` were already dirty when this session started (left from
  2026-08-18) and were NOT included in these commits.
