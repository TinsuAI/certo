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

---

## Round 2 (same day) — ⚙ Cấu hình: currency label, auto-recalculation, decimals

Three more operator reports on the config surface.

### 1. "Nguyên tệ (VND)" claimed nguyên tệ means VND
The parenthetical rendered `product.currency` — the FOB currency of THAT sheet — while the
NVL rows come from many import declarations and can each be in a different currency. Now
reads **"Nguyên tệ (theo tờ khai)"**, with a tooltip stating that neither option converts
anything: every lot carries both money lanes and this only picks which one is printed.

### 2. "Bảng tính tự tính lại như Excel ok chưa?" — it was not; now it is
`recommendation-override` only wrote the overrides. The split that matters:
- **criterion / threshold / form / optimization** change NUMBERS. `lvc_status` (the
  pass/fail colour) and `tariff_shift_status_label` (CTC) are stamped in
  `enrich_origin_product` at Tính, not derived at render — so the sheet kept saying
  "Đã tính" with a badge measured against the previous rule, and the modal hint just told
  the operator to remember a manual Tính.
- **currency_mode / display_decimals** are pure display; the browser already reformats.

Implemented: `NUMBER_AFFECTING_OVERRIDES` + `RECALCULABLE_SHEET_STATUSES` in
`app/routers/co_case.py`. On a real change the route recalculates that sheet
(`recalculate_origin_sheet_and_status`) and marks the sheets after it stale, because stock
is allocated in sheet order. `locked` (filed, ledger holds its claims) and `draft` (never
calculated, nothing to update) are skipped. The case-level criterion route recalculates
every sheet that inherits the choice; a sheet with its own `criteria_override` is untouched.

**Why this was safe to do inline:** measured against the real johnson-vn case —
**1.3s per sheet on a warm snapshot**, 22.5s only for the first cold snapshot read. The
comparison of before/after must read a NORMALISED state: `set_origin_sheet_config_override`
ends in `attach_origin_sheet_states`, which fills defaults, so comparing raw-vs-normalised
reported a change on every save (caught by the first test run).

### 3. Decimals on VND money cells
New `app/money_display.py`: `money_decimals` / `format_money`, a Jinja filter `money`, and a
JS mirror `fmtMoney` in `co_case.html` (the browser is the authoritative formatter — it
rewrites these cells on the Tiền tệ swap and on every client-side edit, so both sides have to
agree; verified in the browser that the settled text is the JS one).

The count keys on **the currency the CELL is printed in**, not the sheet mode — a nguyên-tệ
sheet mixes VND and USD rows. VND → 0; otherwise 6 for an đơn giá, 2 for a trị giá. Per-sheet
override `display_decimals` in ⚙ Cấu hình → **Số lẻ** (Theo tiền tệ / 0 / 2 / 4 / 6), applied
to the grid immediately on change like the currency switch.

**The guard is not optional:** a non-zero value never renders as "0". johnson-vn declares
đơn giá 0.078 VND, and "0" is exactly how this app says *thiếu đơn giá* — printing it over a
priced row sends the operator hunting a defect that is not there. The first significant
decimal is found by TRUNCATION: rounding would call 0.078 visible at one decimal, which reads
"0,1" — a different number.

**Export deliberately untouched.** `bang_ke_xml_generator` takes `number_decimals` from the
HQ template and writes the raw value with a display format, so the filed file keeps full
precision and the agency's template owns its formatting. Screen formatting is an operator
preference; the filed artifact is not.

### Bug the new e2e found
`normalize_threshold` returned `str(Decimal("40").quantize(Decimal("0.01")).normalize())` =
`"4E+1"`, so the LVC chip read "/ 4E+1%" for **every round threshold an operator types**
(10, 20, 30, 40…). Now formatted with `format(d, "f")` and trimmed.

### Verification
- `uv run pytest` — **1156 passed / 17 skipped**.
- New: `tests/test_money_display.py` (14), `tests/test_config_save_recalculates.py` (10),
  plus the threshold-notation and Review-chip cases in `test_criteria_choice.py`.
- Browser: `.ai/scripts/e2e_config_autorecalc_and_decimals.cjs` ALL PASS — label, decimals
  auto vs override applied without Lưu, save recalculates in place (`recalculated=true`,
  sheet stays "Đã tính", LVC chip reads "/ 40%"), reset returns to the recommendation.
- Screenshots refreshed: `.ai/screenshots/2026-08-19-e2e-2-sessions/` (16) and
  `.ai/screenshots/2026-08-19-config-autorecalc/` (3). The grid shot now shows VND đơn giá
  without decimals AND the guard working on the same screen: rows reading 0,032 / 0,018 /
  0,0095 would all have printed "0".

### Shipped
Pushed and deployed 2026-08-19: `origin/main` = prod `barry-co` = nightly `demo-co` =
**`d51581f`**, version **0.18.0**. CD run `32272054677` green on all three jobs (Python
tests, Docker config and build, Deploy demo); `/version` verified on both hosts.
The push also landed two files dirty since 2026-08-18: `uv.lock` (still said 0.14.0) and the
parked 2026-07-17 BACKLOG reconciliation.

### Open
- The Data Hub ĐVT-factor endpoint request
  (`.ai/api-requests/2026-08-19-client-uom-factors-read.md`) is still awaiting approval; until
  it ships, an operator confirms each cross-quantity ĐVT pair once in CO.
