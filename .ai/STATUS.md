# Project Status

## Current State
- **2026-08-19 (afternoon) — ⚙ CẤU HÌNH BẢNG KÊ: 3 operator reports fixed + verified. NOT DEPLOYED.**
  Working tree only; version **0.17.0 → 0.18.0** + CHANGELOG. Suite **1156 pass / 17 skip**.
  e2e `.ai/scripts/e2e_config_autorecalc_and_decimals.cjs` **ALL PASS** on johnson-vn
  `co-case-e0b390ead3b0`. Screenshots: `.ai/screenshots/2026-08-19-config-autorecalc/` and
  `.ai/screenshots/2026-08-19-e2e-2-sessions/` (gitignored).
  **(1) "Nguyên tệ (VND)"** — the parenthetical was `product.currency`, i.e. the FOB currency
  of THAT sheet, while the NVL rows come from many declarations and can be in different
  currencies; it read as "nguyên tệ means VND". Now **"Nguyên tệ (theo tờ khai)"**. Neither
  option converts anything — every lot carries both lanes and this picks which one is printed.
  **(2) Saving the config now RECALCULATES.** `recommendation-override` only persisted. The
  criterion and the threshold decide the LVC pass/fail and the CTC verdict, and both are
  **stamped at Tính**, not derived at render → the sheet kept reading "Đã tính" with a badge
  measured against the PREVIOUS rule. The route now recalculates when a NUMBER-changing
  override moved (`NUMBER_AFFECTING_OVERRIDES` = form / criteria / both thresholds /
  optimization) and calls `mark_origin_sheets_stale(index + 1)`; `locked` and `draft` sheets
  are skipped (`RECALCULABLE_SHEET_STATUSES`). Choosing a criterion for the whole lô
  recalculates every inheriting sheet (one with its own `criteria_override` is left alone).
  `currency_mode` + `display_decimals` do NOT recalculate — display only.
  **Measured on real johnson-vn: 1.3s per sheet on a warm snapshot** (22.5s for the first,
  cold one), which is what made auto-recalc viable instead of a stale marker.
  **(3) Decimals follow the currency** — new `app/money_display.py` + Jinja filter `money` +
  JS mirror `fmtMoney`. Count keyed on the currency OF THE CELL (a nguyên-tệ sheet mixes VND
  and USD rows): **VND 0**, otherwise 6 (đơn giá) / 2 (trị giá); per-sheet override in
  ⚙ Cấu hình → **Số lẻ** (`display_decimals` on `origin_sheet_states`). **Mandatory guard:**
  a NON-ZERO value is never printed as "0" (real data has đơn giá 0.078 VND, and "0" is how
  this app says *thiếu đơn giá*) — such a cell keeps its significant digits, found by
  TRUNCATION not rounding (rounding says 0.078 is visible at one decimal, which reads 0,1).
  **Screen only**: the export keeps the full value and takes `number_format` from the HQ
  template (`bang_ke_xml_generator`).
  **Found by the new e2e:** `normalize_threshold` returned
  `Decimal("40").quantize(Decimal("0.01")).normalize()` = `Decimal("4E+1")`, so the LVC chip
  read "/ 4E+1%" for EVERY round threshold an operator types (10/20/30/40…).
  **Also fixed today (`fc16d5c`):** the Review row read only `criteria_override`, so after
  choosing a criterion for the whole lô every row still said "tiêu chí: khuyến nghị".

- **2026-08-19 — CLIENT FEEDBACK (6 items) on johnson-vn: 5 fixed + shipped locally, 1 blocked
  on a Data Hub contract. NOT DEPLOYED.**
  Working tree only; version bumped **0.16.0 → 0.17.0** with a CHANGELOG entry. Full suite
  **1127 pass / 17 skip** (was 1114/17). Browser e2e `.ai/scripts/e2e_case_criteria_modal.cjs`
  ALL PASS against local `:8001` on the real johnson-vn case `co-case-e0b390ead3b0`.
  Session: `.ai/sessions/2026-08-19-criteria-picker-uom-modal-search-and-bulk-recalc.md`;
  forwardable VI reply: `.ai/feedback/2026-08-19-client-questions-uom-criteria-search.md`.
  **(2)+(3) Tiêu chí** — the case-level criterion was a `window.prompt` with a free-text box,
  and free text is not inert: the engine reads criterion TOKENS, so a typo lands on no rule
  while the UI still reads "chosen". Replaced with a modal that REUSES the per-sheet ⚙ Cấu
  hình markup (`[data-criteria-panel]` + `data-criteria-seg` WO/PE/CC/CTH/CTSH/RVC/LVC/PSR +
  `Khác…` + "hoặc" alternates + Ngưỡng %), so `initCriteriaSegments` wires it with **no change
  to that function**. New `refreshCaseShellInPlace()` (fetch current URL as `text/html` →
  existing `replaceCaseShellFromResponse`) removes the F5 from the criterion save, the
  per-sheet ⚙ **Lưu** (which previously only toasted — the actual surface in the screenshot)
  and **Reset**, and the ĐVT save.
  **Bug found: "Bỏ chọn" tiêu chí NEVER worked** — `set_case_criteria_route` popped
  `criteria_choice` off the dict, but `update_case_record` copies only keys PRESENT in the
  incoming case (`co_case_store.py:182` whitelist). Now writes `{}`.
  **(4) "Đủ tồn cho tất cả SP" over sheets reading "Cần tính lại"** — NOT a ĐVT bug. Stock is
  allocated sequentially, so `bulk-substitute`/`bulk-delete-rac` mark every downstream sheet
  stale but recalculated only `edited_codes`, while the aggregate ran a fresh whole-case
  preview. New `origin_codes_to_recalculate()` returns every code from `min(edited index)`
  onward, minus locked.
  **Adjacent defect fixed: `calculate_all_route` silently unlocked locked sheets** —
  `allocate_whole_case_preview` rebuilds EVERY product (`prepare_case_origin_products` has no
  locked skip) and the route stamped `calculated_sheet_status` on every code, rewriting a
  filed snapshot while the ledger still held its `co_stock_claims`. Locked products are now
  restored and their status left alone.
  **(1)+(5) ĐVT — real fix is BLOCKED on Data Hub.** DH johnson-vn holds **516** factors in
  `hub.client_uom_overrides` (mig 055) exposed ONLY as an HTML admin page
  (`app/routes/client_uom_factors.py`); there is no `/v1/hub` route, and CO's own
  `co_uom_factor` is empty for this client → every cross-quantity pair (EA↔CAY) blocks Chốt.
  Contract written and STOPPED per the AGENTS.md rule:
  `.ai/api-requests/2026-08-19-client-uom-factors-read.md` (pins direction —
  `qty(to_uom) = qty(from_uom) × factor`, same as `resolve_uom_factor`, so
  `from_uom → bom_uom`, no inversion — plus decimal-string precision, pagination, consumer
  plan). **No `hub.` read from this repo and no CAY added to `_ALIASES`** (DH's own note says
  "synonym in **Johnson** context" = per-client data).
  CO-side interim SHIPPED: row button now reads "Cần hệ số EA→CAY" and opens a modal asking
  one question with a **scope** choice (chỉ mã này / mọi mã có cặp EA → CAY — the store
  already supported client-wide rows, the route just always posted `scope: "material"`); new
  material field `uom_converted` hides the `⇄` badge on rows that convert 1:1 (alias
  EA/PIECES/CÁI), which had been marking 145 rows of a Johnson sheet where nothing changed.
  **(6) Substitute search returned 20** — the picker never sent `limit` (route default 20)
  and `build_stock_first_candidates` filtered on a whole-phrase, accent-sensitive substring.
  Now `limit=200` client-side, route caps at 200, `rank_matches`/`search_case_material_rows`
  caps to 500, stock-first uses `material_search.match_score`'s rule (fold accents, AND
  across tokens). Measured on `co-case-e0b390ead3b0` / MFW0525-39: `bu lông` **21 → 192**,
  `bu long` **192**, `bo oc vit bu long` **111**, ordered tồn-desc; a count line and the
  known tồn now render immediately instead of "0 tồn".
  **OPEN:** DH endpoint approval; deploy (CD not run). `.ai/BACKLOG.md` + `uv.lock` were
  already dirty from 2026-08-18 and were NOT included in these commits.
- **2026-08-17 — CLIENT QUESTIONS on johnson-vn VNG26020033: 3 defects FIXED + SHIPPED + DEPLOYED + VERIFIED
  LIVE; johnson-vn rác-cleanup flag turned ON in prod.**
  `origin/main` = prod `barry-co` = nightly `demo-co` = **`72de4eb`** (CD runs `31995246886` + `31996774344`
  green: Python tests + Docker build + Deploy demo; `/version` verified BOTH hosts). Full suite **1035 pass /
  17 skip**. Session: `.ai/sessions/2026-08-17-client-questions-missing-price-belt-and-labels.md`;
  client-facing findings + forwardable VI reply: `.ai/feedback/2026-08-17-client-questions-vng26020033.md`.
  **Operator report:** "Tổng hợp NVL" said "Đủ tồn — có thể Chốt tất cả" → "Chốt tất cả" returned "Đã chốt 0
  sheet · bỏ qua 2" → F5 showed "Cần xử lý: thiếu đơn giá" on a bảng kê where EVERY row had an đơn giá.
  **All measured on live prod (read-only):** MPL0108-39 = 145 rows (82 declarable/ready + 35
  `declarable_unmatched` + 28 `excluded_non_material`), MFW0509-39 = 86 (62 + 19 + 5); **0 rows** carry
  `valuation_status == missing_unit_value` on either sheet.
  **D1 `lvc_missing_price` fired on rác (`co_case_context.py:3233`)** — the flag ORs on `unit_value_missing`,
  which a no-lot row ALWAYS sets (`material_value = None`), while its `valuation_status` is deliberately
  `partial_allocation` (ADR 2026-07-11 `:2734` — a no-lot line's defect is the missing DOCUMENT, not a price).
  It also never excluded `bom_technical_noise` the way its sibling `lvc_allocation_shortage` (`:3255`) does →
  shortage false, missing_price true, wrong remedy shown. Fix = `and not material.get("bom_technical_noise")`.
  **D2 bulk routes stamped `"calculated"` blind** (bulk-substitute + bulk-delete-rac) → a belt-blocked sheet
  read "Đã tính" while the lock gate refused it; **this is the F5 story, NOT a client-side repaint gap.**
  Fix = new `recalculate_origin_sheet_and_status` (`co_case.py`) used by both.
  **D3 aggregate invited "Chốt tất cả" while blocked** — `case_shortfall_rollup` routes all-noise materials
  into `folded_rac`, never `materials` (`material_count == 0` → ✓ invite), and the client DROPPED `folded_rac`
  when the flag was off. **Decision: the flag gates bulk ACTIONS, not visibility of a blocker** → rác is now
  listed read-only regardless of the flag, and the panel warns instead of inviting Chốt while
  `declarable_unmatched` remains. `excluded_non_material` does NOT block (after D1), so the ✓ invite survives
  when only phi-vật-tư rows are left — pinned by an e2e assertion.
  **D4 relabel (`72de4eb`)** — the chip read "NVL chưa khớp tồn", which reads as a QUANTITY shortfall, i.e.
  exactly what the other label ("thiếu tồn") means. Unified 4 phrasings onto **"NVL chưa có tờ khai nhập"**
  across chip / lock error / per-sheet filter chip / rác quick-select / row tag / per-row mark / fold toggle;
  details now say "không phải thiếu số lượng" + name remedies (sửa mã / thay mã / xoá dòng). "BCCT" dropped
  from operator text; `declarable_unmatched` kept in the lock error as a support anchor.
  **PROD CONFIG (not code): `features.bulk_delete_junk_rows` = ON for johnson-vn** — first real client to get
  it. `config_version` 1→2, `co_config_fingerprint` UNCHANGED `17c95904c2712c54` (→ no stock re-derivation),
  `allocation_code`/`co_stock`/`bcct` untouched; written via `_local_config_store().save_client_config`,
  verified through `portfolio_service.get_client_config`.
  **Q1 "uploaded BCCT but codes still missing" = NOT a CO bug, NOT an upload gap.** DH johnson-vn import BCCT
  = 84,231 rows / 10,393 codes / 2025-04-18→2026-08-05, and CO `co_stock_rows` = 84,231 (1:1, refreshed
  03:25Z, no declaration-type filter). All **53** unmatched codes appear in **0** BCCT rows either direction;
  they sit in `hub.materials` as `provenance={"seen_in_bom_only": true}` with `name == material_code`
  (matched codes carry `provenance.seen_in_bcct` + a real description). Client-wide **3,822/14,527** catalog
  materials are BOM-only and `hub.code_mappings` has **0 rows for johnson-vn** (growatt-vn: 2,913) → a BOM
  code that isn't literally the declared customs code can never match. Earliest import = 2025-04-18, so any
  Jan–mid-Apr 2025 declaration never landed. Needs agency confirmation + possibly a DH-side mapping
  (`data-hub` repo — guardrail, not from here).
  **Q5 "chọn tiêu chí PSR/CTH?" = already exists** — per-sheet `⚙ Cấu hình` → Tiêu chí segments
  WO/PE/CC/CTH/CTSH/RVC/LVC/PSR + "Khác…" + "hoặc" alternates + Ngưỡng % (`co_case.html:1332-1381`). The
  criterion drives the LVC threshold and the CTC preview (`tariff_shift_rule_from_criterion:3441`); both
  sheets run empty "(khuyến nghị)" criteria, hence "CTC —". LVC fail does NOT block lock.
  **Verified live after deploy:** deployed code run in-container against `co-case-6cb034e91cb7` →
  `missing_price=False` on both sheets (was True), `unmatched=True`, status `bom_loaded`, chip = "Cần xử lý:
  NVL chưa có tờ khai nhập". The case is still (correctly) not lockable — 35 + 19 unmatched rows remain; with
  the flag ON the operator clears them from "Tổng hợp NVL" in one pass, Tính lại, then Chốt.
  **OPEN (decision needed, NOT fixed):** `co_case.py:3358` (per-sheet "Lưu bảng kê") + `:3556` (mở chốt) carry
  the SAME hardcoded-`"calculated"` defect as D2 (`:3556` can't reuse the helper — reopen has no recalculation
  before it). **Adjacent/inert:** VNM sums `non_origin_cif_value` over noise rows (`co_case_context.py:2455-2460`,
  no noise filter — harmless while noise rows carry no value). **Cosmetic:** LVC "Tạm đạt/Tạm tính" + "Thiếu
  tồn CO N dòng" quality warning still count noise rows (`:2461`, `:3208-3226`); does not block lock.
- **2026-08-07 — "NVL rác" REDESIGN: inline select + per-row substitute + row UI, SHIPPED + DEPLOYED.**
  `origin/main` = prod `barry-co` = nightly `demo-co` = **`0055b17`** (CI/CD run `31149953052` green: build +
  Python tests + Deploy demo). Full suite **1031 pass / 17 skip**. Continues the 2026-08-06 feature below (same
  session file `.ai/sessions/2026-08-06-bulk-delete-nvl-rac.md`).
  Operator feedback drove three changes to the "xoá NVL rác" surface (aggregate + per-sheet):
  **(1) select-then-act, not delete-only** — rác rows render INLINE; checkbox at the START of each row; selecting
  highlights the WHOLE row; two quick-select buttons by kind (không có trong BCCT / phi vật tư) + a bulk "Xoá
  dòng đã chọn" → scrollable confirm modal → delete.
  **(2) substitute option** — each `declarable_unmatched` ("không có trong BCCT", a REAL NVL) row gets "Chọn mã
  thay thế…" (aggregate → bulk-substitute picker; per-sheet → reuses the sheet's per-row substitute trigger);
  `excluded_non_material` (phi vật tư) is delete-only (not a material). Fixes the earlier "chỉ để đó hoặc xoá".
  **(3) neutral labels** — dropped the "rác đã loại" wording; per-row tags "chưa khớp tờ khai" / "phi vật tư".
  **Impl:** rollup `folded_rac` entries now carry full substitute data (`using`, short_count…); route
  `bulk-delete-rac` `kind` is now OPTIONAL → a MIXED selection deletes in one call (declarable/thiếu-tồn rows
  never touched). Shared `racPanelHtml`/`wireRacPanel` render+wire the panel for BOTH the aggregate and each
  per-sheet grid (`[data-sheet-rac-mount]` + `initSheetRacPanels`; per-sheet delete scoped by `product_code`).
  Row markup = `.rac-row` (checkbox-first flex; `.rac-row-checked` whole-row highlight; kind-colored tags).
  Verified: full suite + browser e2e ON/OFF on the Johnson clone (aggregate 48 unmatched / 23 phi-vật-tư; per-sheet
  panel 6 rows; screenshots `.ai/screenshots/2026-08-06-bulk-delete-rac/`). Flags reset OFF; clone removed.
  **Note:** the earlier docs commit `9144ade` deploy FAILED on runner disk-full (`tinsu` `_diag` logs); this
  deploy (`0055b17`) succeeded → runner disk has since been freed.
- **2026-08-06 — BULK-DELETE "NVL RÁC" (aggregate + per-sheet, 2 kinds) SHIPPED + DEPLOYED.**
  `origin/main` = prod `barry-co` = nightly `demo-co` = **`27980bb`** (merge of PR #23 `review/clean-fixes`;
  feature commit **`d6bdebb`**; CI/CD run `31116327808` green: build + Python tests + Deploy demo). Full suite
  **1030 pass / 17 skip**. Session: `.ai/sessions/2026-08-06-bulk-delete-nvl-rac.md`.
  PR #23 = review-batch integration (this feature + ~15 already-reviewed agent branches: LK1/DC3b force
  re-Tính, cold-start overclaim block, calculate lot-scoping, dup-BOM-propose guards, secure cookies, N+1 claim
  batch, CO-stock refresh reason, test/harness hardening).
  **Feature:** per-company opt-in `features.bulk_delete_junk_rows` (default **OFF**) → bulk-delete folded rác
  NVL, split into 2 kinds by `customs_relevance`, on BOTH the "Tổng hợp NVL" aggregate sheet AND each per-sheet
  grid: **NVL không có trong BCCT** (`declarable_unmatched`) + **NVL phi vật tư** (`excluded_non_material`);
  shared scrollable confirm modal (checkbox list). Per-sheet made consistent with aggregate (same buttons +
  modal, route scoped by `product_code`); old mis-targeted `⊘ Lọc dòng lỗi` removed.
  **Key finding ("sửa logic cho đúng"):** cross-tab on real Johnson data (267 rows, `co-case-e0b390ead3b0`
  clone, deletions reverted) proved `customs_relevance` deterministically encodes BCCT-lot presence —
  `declarable` ⟺ in BCCT (short = genuine **thiếu tồn** → THAY THẾ, not delete); the two folded kinds ⟺
  candidate 0 (rác → xoá). `allocation_count == 0` alone is **NOT** a rác signal (a declarable material with 0
  lots is thiếu-tồn, lots exhausted/date-excluded); the first no-stock build was WRONG and reworked. Route
  `POST .../origin/bulk-delete-rac` (kind ∈ {declarable_unmatched, excluded_non_material} + optional
  `product_code` scope) filters by `customs_relevance` server-side; rollup `case_shortfall_rollup` returns
  `folded_rac` (grouped code+kind, locked excluded) and keeps pure-rác OUT of the thiếu-tồn/substitute list.
  Aggregate substitute scope default flipped `only_short` → `everywhere` ("thay hết", aggregate UI only).
  Config: `features` section in default/migrate + **DH-mode `to_save` whitelist** (else the toggle is silently
  dropped in prod DH source-mode) + config-page checkbox. Verified: unit/route tests + browser e2e on Johnson
  (48 unmatched + 23 phi-vật-tư; delete removed 63 rows, folded_rac 71→23, kinds isolated); flags reset OFF +
  e2e clone removed after. Committed feature files only (never `.ai/BACKLOG.md`/`uv.lock`/untracked docs); no AI
  trailer.
  **Open (low, product call):** `declarable_unmatched` is in the delete bucket as "không có trong BCCT" but is a
  real NVL **chờ đối soát** (recoverable via Ctrl+Z; modal tags each row). If the client wants it split from true
  phi-vật-tư with a stronger warning (not one-click delete), split Nhóm 1 further — not requested yet.
- **2026-07-27 — CO 524 (origin timeout) ON CASE-OPEN + SUBSTITUTE MODAL: BOTH FIXED, DEPLOYED, VERIFIED LIVE.**
  `origin/main` = prod `barry-co` = nightly `demo-co` = **`8556ee1`** (CI/CD green all 3 commits; behavior
  verified live on prod johnson-vn). Full suite **935 pass / 14 skip**. Session:
  `.ai/sessions/2026-07-27-co-524-shipment-substitute-narrow-fetch.md`.
  **Client feedback = 2 items.** (1) **Data Hub** BCCT-import "Apply confirmed changes" disabled + yellow/green
  "đơn vị tính khác họ (604)" unclear → **`data-hub` repo, NOT CO** (guardrail); handed to user as a ready
  `/diagnosing-bugs` prompt for a parallel DH session. NOT fixed here. (2) **CO** case-open → Cloudflare 524.
  **Fix 1 shipment 524 (`544840e`)** — `co_case_source_context` skip-heavy branch (`data_hub_client.py:886`)
  EXCLUDED export-declaration cases (`and not export_declaration_nos`) → the default shipment tab did the full
  ~65k-BCCT + ~12k-materials pull SYNC on the async event loop (`co_case_detail` is `async def` calling sync
  `co_case_context`). As Johnson grew to ~73k BCCT, the pull crossed 100s → 524. F5 "worked" because the
  background preload persisted `source_snapshot` → next open hit the cached path. **Fix:** route export-decl
  light path through `origin_invoice_matches` (narrow per-declaration `list_bcct(declaration_no=)` +
  `match_case_bcct_exports`, the same fetch the origin tab has used since 2026-05-31, byte-identical 43/43 on
  Johnson). Prod: **124.88s → 0.31s**, same 2 matches. **Fix 2 substitute modal 524 (`c104615`)** — found by
  the fable review of fix 1: `co_case_origin_sheet_substitute_candidates` (`co_case.py:2384,2423`) called
  `co_case_source_context_cached` (full ~125s pull) but ONLY read `material_rows`. **Fix:** new
  `DataHubPortfolioService.material_catalog` (materials-only, drops `tp`) + `co_case_material_catalog_cached`
  (client-wide 300s cache; file-store falls back to in-memory). Prod: **~125s → 15.69s** (14 calls, **0 bcct**),
  12943 rows (= heavy-path count). **Parity test (`8556ee1`)** — `material_catalog == heavy material_rows`
  byte-for-byte (locks the invariant after the user asked whether "chỉ list_materials" is safe: YES — the
  modal only ever used material_rows, which is identical; RVC/tồn/bảng kê compute elsewhere with independent
  snapshot stock, per `test_recalc_stock_source_parity`).
  **Residual (NOT done, not urgent — no 524):** (A) narrow fetch omits `include_material_identity` → item_code
  display-code vs raw on non-origin cold window (display only); fix touches shared `origin_invoice_matches` →
  ticket. (B) H2: `co_case_detail`/`co_case_step`/substitute endpoint are `async def` calling sync pulls →
  the residual ~15s first-open still blocks the event loop (15s < 100s so no 524); offload to a thread later.
- **2026-07-17 (PM3) — CODE-VOCAB BATCH #18–#22 FULLY CLOSED + USER GUIDE SHIPPED. `TinsuAI/co` = 0 open issues.**
  `origin/main` = prod `barry-co` = nightly `demo-co` = **`dacb70d`** (CI green; `/version` verified BOTH:
  prod build `05:57:52Z`, nightly `05:58:23Z`). 4 new commits this session; full suite **932 pass / 14 skip**.
  Session: `.ai/sessions/2026-07-17-code-vocab-19-20-22-close-and-user-guide.md`.
  **User guide (`c1d8d9c`)** — VI operator guide `docs/huong-dan-su-dung/` (README + PDF + 22 screenshots),
  CO + Data Hub end-to-end, fictional `Demo Furniture Co.` (no agency data). Repro tooling under
  `.ai/features/2026-06-20-co-datahub-user-guide/` (was built 2026-06-20, untracked → committed now).
  **#19 (`acb135d`) — NARROW-CLOSED, task 1 only.** Renamed module-private `resolved_code`/`review_code`
  → `_resolved_allocation`/`_review_allocation` (3-owner token collision). Tasks 2 (return-shape prefix) +
  3 (`bom_product_code`→`product_code` locals) DROPPED — task 2 would rewrite #21's just-canonicalized
  value-set; task 3 unsafe where both codes coexist as distinct BOM-match keys (`co_case_context.py:839,911,987`).
  **#20 (`daf1732`)** — `tests/test_code_identity_invariants.py` (4) pins INV-1 (claim.customs_code ==
  source lot.customs_item_code) + INV-2 (`co_stock_rows.material_code` = derived allocation_code, NOT catalog)
  + adapter/overload comments at 4 sites (issue line numbers had drifted).
  **#22 (`dacb70d`) — INVESTIGATION → keep all 3 DH→CO normalize fallbacks; remove 2 DEAD links + pin contract.**
  Verified vs LIVE local DH (`psql data_hub`, `hub.*`): johnson-vn 13,131 materials / 60,173 stock rows
  (declared==internal, all collapse), growatt-vn 457 / 38,287 (33,748 declared≠internal → `item_code`=DECLARED,
  not internal). Erasures need row shapes the DH SCHEMA can't produce (material w/ only customs_code; bcct w/
  internal_code). Dropped `normalize_bcct_row` `or internal_code` (mis-ordered) + `normalize_material_row` dead
  `or customs_code`. Zero behavior change → NO re-derivation (corrects the issue's #14-S3 hedge).
  `tests/test_dh_normalization_fallbacks.py` (10, 3 layers: growatt/johnson/contract).
  **#21 (`5838d2c`, pre-session) + #15/#16/#17** — all CLOSED (code already shipped; issues closed this session).
  **STILL PENDING (user-manual, unchanged):** (1) run calibrated growatt-vn regex seed
  (`scripts/seed_growatt_vn_allocation.py`, `b98156a`) on prod + nightly — applied LOCALLY only; prod/nightly
  still broad regex. (2) flag Mingjie VN + Minghui VN on growatt-vn suppliers screen.
- **2026-07-17 (PM2) — LOCAL bugfixes SHIPPED + DEPLOYED: /clients 500 + growatt-vn calculate-all "toàn 0"; prod seed config change PREPPED, not run.**
  **PUSHED + DEPLOYED** — `origin/main` = prod `barry-co` = nightly `demo-co` = **`d769012`** (CI/CD run
  `29529764304` green: build + 910 tests + Deploy demo; `/version` verified BOTH hosts `git_sha=d769012`,
  build `2026-07-16T19:54Z`). 3 commits: `8e10948`, `b98156a`, `d769012` (STATUS). **Only `8e10948` is a
  runtime change** (portfolio page hardened vs null-tax_code clients); `b98156a` = seed script NOT in the
  Docker image (no runtime effect); `d769012` = docs.
  **(1) `/clients` + `/` → 500 "Internal Server Error" (`8e10948`).** Root cause: DH `list_clients()` returns
  test clients with an explicit `tax_code: null` (local DH `:8754` has ~60 junk `nxt-*`/`sa-test-*` clients);
  `upsert_client` (`app_state_store.py:76`) bound the NOT NULL text cols with `payload.get(col, "")`, which
  returns `None` when the key is present-but-null → `NotNullViolation` on the first such client → the whole
  portfolio page 500s. Fix = `payload.get(col) or ""` for name/code/status/tax_code/contact. Local-dev-only
  today (prod clients carry real tax codes). Junk DH clients NOT cleaned (DH-side data; guardrail).
  **(2) growatt-vn "Chạy tồn tất cả → mọi sheet 'Đã nạp BOM', toàn 0" (case `co-case-3c13e6b34eb3`).**
  Root cause: **LOCAL dev growatt-vn was never seeded with #14 `description_regex`** — the 2026-07-17 seed hit
  prod+nightly in-container only; local config was still `same_as_customs_code`. BOM uses dotted internal codes
  (`001.*`, `012.*`); under `same_as_customs_code` only **25/850** match a lot → every material shortage +
  missing-price → `calculated_sheet_status` hard-blocks to `bom_loaded` (`co_case.py:2104-2112`). NOTE local
  lot data differs from prod: internal code lives in **`material_description`** parens (not `goods_name`),
  34,835/38,287 rows have it. Ran `scripts/seed_growatt_vn_allocation.py` LOCALLY (→ `description_regex` + full
  re-derivation) → 848/850 match, 3/6 sheets calculate.
  **(3) Residual `012.0001400` = CODE-EXTRACTION error, NOT out of stock (`b98156a`).** 20 lots, tens of
  thousands of units available. Lot descriptions carry TWO parens — a mfr part number + the internal code:
  `...M(SCK10202MSY). Hàng mới 100%(012.0001400)`. The broad regex matched BOTH → `resolve_allocation_code`
  (`client_config_store.py:145`) blanked it as `multiple_regex_matches`. **Fix = calibrate growatt-vn's
  per-client `description_regex` to `\(\s*([A-Z0-9]+\.[A-Z0-9]+)\s*\)`** (single alnum·dot·alnum filling the
  whole paren) — keeps every real shape (`012.0001400`, `B700.0141600`, `PE07.0073300`, `001.SK0002900`),
  rejects part numbers/specs (`SCK10202MSY`, `150W`, `380-415`, `1.25-16MM2`). **848→849, 38→0 blanked, no
  regression.** Deliberately in the **per-client config (the #14 seam), NOT the shared resolver** — user flagged
  that hardcoding "prefer dotted" in `resolve_allocation_code` would overfit to Growatt; the ambiguity guard
  stays intact as a general safety net. `DEFAULT_DESCRIPTION_REGEX` + other clients untouched. Seed script
  generalized (normalizes strategy/regex/fallback, idempotent, **stdin-safe** so it runs piped in-container —
  `scripts/` is NOT in the Docker image). Applied LOCALLY → **5/6 sheets calculate, missing_codes=[]**
  (`PV06.0010800` = genuine `lvc_status=fail`; `PV01.0117900` = genuine `missing_bom`). 38 config/alloc/refresh
  tests pass.
  **PENDING (user manual):** run the calibrated seed on **prod `co-app-1` + nightly `nightly-co-app-1`** (prod
  growatt-vn still has the broad regex → same blanked lots expected). Command (via `ssh tinsu`, from a checkout):
  `docker exec -i co-app-1 /app/.venv/bin/python - < scripts/seed_growatt_vn_allocation.py` (+ nightly). Vet
  first: confirm container names + check growatt-vn for locked cases (re-derivation changes stock
  `allocation_code`). The seed script (`b98156a`) is already on `origin/main` — pull a checkout before running.
  **Follow-up (optional):** `DEFAULT_DESCRIPTION_REGEX` (`client_config_store.py:40`) is still the broad
  over-matching pattern — the demo `growatt` client uses it; consider calibrating the default too.
- **2026-07-17 — #18 + #14 S1–S4 SHIPPED + DEPLOYED + growatt-vn SEEDED (prod + nightly).**
  `origin/main` = prod `barry-co` = nightly `demo-co` = **`d74e8fb`** (CI green, `/version` verified both).
  `/implement` per the #14 spec, `/tdd` per slice. 4 commits: `2479111` (#18), `0f0812f` (#14 S1–S4),
  `f240964` (docs), `d74e8fb` (source_summary display fix, below).
  **#18 (`2479111`)** — dropped `allocation_code` from `allocation_line_matches_stock`
  (`co_case_context.py:1092`); saved allocation lines now rebind to their lot by
  `source_row`/`decl_no`/`line_no` (all strategy-invariant) after a strategy flip. `tests/test_allocation_line_rebind.py` (6).
  **#14 (`0f0812f`)** — ownership-partition per the ADR. **S1** `data_hub_client.py`:
  `get_client_config` = local base + DH `bcct` overlay; `save_client_config` writes the CO-owned
  sections locally, rejects a `bcct` edit. Hardened beyond the literal spec: DH-supplied `co_stock`
  fields (`min_days_before_export`) are preserved while local `lot_policy` wins → no eligibility
  regression. Store selection via one `_local_config_store()` (DB store or file store). **S2** `pages.py`:
  the config route rejects a declaration-type change UP FRONT, then saves allocation/lot_policy — no
  more partial-save-then-409 (was `require_local_source_writes()` at `:313` after the overlay upserts).
  **S3** `co_stock_materializer.py` + `co_case_context.py`: `co_config_fingerprint` (hashes BOTH
  `allocation_code` and `co_stock`, NOT `config_hash`) stamped in `co_stock_refresh_state`
  (**migration 021**), `config_current` added to the delta guard → forces one full re-derivation on
  mismatch (self-healing default `''`). **S4** `scripts/seed_growatt_vn_allocation.py` (idempotent:
  save `description_regex` through the new path + force the full re-derivation) + regression test pinning
  the effective strategy and a `(920.0042600)` lot resolution. New tests: `test_co_owned_client_config.py`,
  `test_config_route_co_owned.py`, `test_co_stock_refresh_config_fingerprint.py` (+ 3 existing refresh-dispatch
  tests updated for the new guard).
  **Verify:** full suite **910 pass / 14 skip**; migration 021 applies; a real Postgres `client_configs`
  round-trip flips `same_as_customs_code` → `description_regex` with DH `bcct` still overlaid.
  **`/code-review` (Standards + Spec parallel agents):** no hard violations; 3 standards fixes (middle-man +
  dup store-dispatch → `_local_config_store()`; renamed the `record_refresh_state` param that shadowed
  `co_config_fingerprint`); the S2 partial-save Spec finding fixed up-front.
  **Browser e2e (real CO+DH stack) caught a display bug → fix `d74e8fb`:** the config page AND the
  case-context derivation read `source_summary["client_config"]`, built via `normalize_data_hub_client_config`
  (DH `bcct` + the code default), so a saved CO-owned strategy persisted but never SHOWED / never reached that
  derivation path. Fix = `_partition_merge_config` shared by `get_client_config` AND `source_summary`
  (`data_hub_client.py`). e2e now PASS (set `description_regex` → page + hard-reload reflect it, DH `bcct`
  intact, restore returns baseline). +1 regression test.
  **PUSHED + DEPLOYED (`d74e8fb`):** CI/CD green; prod `barry-co` + nightly `demo-co` both `/version`
  `git_sha=d74e8fb`. Migration 021 ran on deploy (additive col; each client's next Refresh tồn goes one full
  re-derivation — same config → same codes, just heavier once).
  **growatt-vn SEEDED — nightly THEN prod** (advisor-vetted vs LIVE prod: growatt-vn **0 cases / 0 claims /
  no aggregate-policy config** → #18 rebind had nothing to orphan; johnson-vn untouched; write is one atomic
  `refresh_co_stock_for_client` txn). In-container `docker exec -i {co-app-1|nightly-co-app-1}
  /app/.venv/bin/python`: strategy → `description_regex`, forced full re-derivation `mode=full
  rows_persisted=38287`, fingerprint `44176834c0abb7b1` (**identical both envs**),
  **34,388/38,287 (90%) rows now carry dotted internal `allocation_code`** (DIOT→008.0035900,
  PCBA→B700.0141600, BBD→010.0005000) vs 4,469 short-code fallback. 4.5% → ~96% BOM-code match unblocked.
  **STILL PENDING (user manual step, independent of the seed):** flag 2 NCC on growatt-vn
  `/clients/growatt-vn/suppliers` — `CONG TY TNHH MINGJIE VIET NAM` + `CONG TY TNHH MINGHUI VIET NAM`
  (verify spelling vs live BCCT; NEVER the HK namesake `MINGJIE INDUSTRIAL (HK)`).
  Rollback (if ever needed): set strategy back to `same_as_customs_code` + refresh — fingerprint mismatch
  forces a full re-derivation to the old codes; no case/claim state to unwind for growatt-vn.
- **2026-07-16/17 — #14 RESOLVED (design + docs only, NO code); code-vocab DICTIONARY + AUDIT; 5 issues filed.**
  `/grill-with-docs` on #14 (growatt-vn allocation strategy blocker). **Empirically settled vs live DH
  Postgres:** growatt-vn lots embed the internal code in `goods_name` parens `(008.0006100)`;
  `description_regex` takes BOM-code match **4.5% → 96%** (101 → 2,145 / 2,236); `material_identity.internal_code`
  null on **0/38,287** rows (short-circuit inert). Config problem, NOT keyspace — Option 3 (reseed) dead.
  **DECISION — SUPERSEDES the old "option 2 CO-side overlay blob" recommendation below:** client_config
  ownership is **partitioned** — DH owns `bcct` (declaration types), **CO owns `allocation_code` + `co_stock`**,
  persisted through the EXISTING local `client_configs` store (`app_state_store.py:96-144`), NOT a new
  `bang_ke_overrides`-style blob. DH-mode `get_client_config` = local base + DH `bcct` overlay;
  `save_client_config` writes CO-owned sections locally. **Rejected:** Option A (DH-side, two-repo);
  gap-filler precedence (a DH backfill of the `same_as_customs_code` default would silently revert
  growatt-vn cross-repo). ADR `.ai/DECISIONS.md` [2026-07-16].
  **Spec** `.ai/features/2026-07-16-co-owned-client-config-allocation.md` (S1–S4). **S3 is mandatory:**
  fingerprint BOTH CO-owned sections in `co_stock_refresh_state` (`co_config_fingerprint`) + force full
  re-derivation, else the fix silently no-ops on the 60k snapshot (delta never rewrites unchanged rows).
  NOT keyed on `config_hash` (unstable in DH mode). Mirrors the 020/`DERIVATION_SCHEMA_VERSION` pattern.
  **DICTIONARY** `.ai/GLOSSARY.md` new "Material & lot codes" (7-concept model: `customs_item_code` identity /
  `material_code` / `material_identity` / `product_code` / `bom_code` / `allocation_code` derived / config)
  + "Runtime modes" (Axis-1 source backend, Axis-2 persistence, DH `code_resolution_mode`). 3-agent audit +
  independent logic review (all claims CONFIRMED, numbers reproduced to the digit).
  **Issues filed `TinsuAI/co`:** **#18** T0 correctness bug (`allocation_line_matches_stock:1097` orphans
  saved allocation lines on a strategy change; growatt-vn safe today = no saved cases) `ready-for-agent`+`bug`,
  linked to #14; **#19** T2 safe helper renames; **#20** T3 invariant tests + adapter docs; **#21** T4
  allocation_code `_source`/`_confidence`/`_status` value cleanup (**blocked by #14**, rides S3); **#22** T6
  DH→CO fallback investigation (`needs-triage`, behavior-risk). T5 (persisted-column renames) intentionally
  NOT filed. All docs uncommitted on local `main`; no code. Session
  `.ai/sessions/2026-07-16-issue-14-co-owned-config-and-code-vocab-dictionary.md`.
- **2026-07-11 (PM) — 2 STANDING ITEMS CLOSED + SUPPLIERS-SCREEN BUG FIXED + DEPLOYED.**
  `origin/main` = prod = nightly = **`9f38afa`** (CI green, `/version` verified both).
  (1) **`missing_price` belts 2/3** (`b89e187`): lock gate + export blockers re-check
  `lvc_missing_price` (shortage takes precedence — no-lot NVL trips both flags, remedy = document).
  (2) **Prod audit locked SHORTAGE sheets: NO exposure** — 0/10 locked sheets flagged (16 cases,
  82 sheets); 4 johnson-vn `calculated` sheets carry flags → now correctly hard-blocked until re-Tính.
  (3) **Suppliers screen empty root cause + fix** (`9f38afa`): pre-VN-origin snapshots lack
  `consignee_name` and "Refresh tồn" takes the DELTA path (never rewrites unchanged rows) → CO-side
  derivation field additions never backfilled. Fix = migration **020** `derivation_schema_version`
  stamp; dispatch forces ONE full re-derivation on mismatch (`DERIVATION_SCHEMA_VERSION=2`).
  **Prod + nightly BACKFILLED in-container** (both clients 100% consignee coverage, 0 removed,
  stamps=2) — prod NCC screen is populated NOW. (4) **QA issues #15/#16/#17 filed**
  (`ready-for-agent`, independent): long-name horizontal scroll, suppliers search box, client-tabs
  missing on case view. Suite **887 pass / 14 skip**. Session:
  `.ai/sessions/2026-07-11-missing-price-belts-stock-refresh-backfill.md`.
  **USER ACTION PENDING:** flag 2 NCC on prod UI (`CONG TY TNHH MINGJIE VIET NAM` +
  `CONG TY TNHH MINGHUI VIET NAM`, spellings verified vs live BCCT; NEVER the HK namesake);
  decide **#14** (recommendation: option 2 — CO-side allocation override on client overlay).
- **2026-07-12 (overnight) — VN-ORIGIN FEATURE BUILT: ALL 8 TICKETS (#6–#13) IMPLEMENTED,
  TESTED, COMMITTED, ISSUES CLOSED.** Autonomous run per user directive. **PUSHED + DEPLOYED 2026-07-12** (user go-ahead): `origin/main` = `51fe273`,
  CI/CD green, prod `barry-co` + nightly `demo-co` both verified `git_sha=51fe273`. Live e2e
  screenshot tour done (see session addendum); finding **#14** filed (growatt-vn allocation
  strategy hard-defaults `same_as_customs_code` in DH mode → technical BOMs match no on-spot
  lots — onboarding blocker for the day-one beneficiary, needs-triage); backlog **ST1**
  (readiness chip: guard-parked sheets still read "Đã nạp BOM" after batch Tính). Suite **757 → 881 passed** (124 new tests), file-mode green after every
  ticket; migration 019 verified against local Postgres. Per-ticket two-axis reviews caught and
  fixed 3 real bugs (shortage reason precedence #8; override version-rebind hole #7; locked-sheet
  re-stamp #10). Full handoff: `.ai/sessions/2026-07-11-vn-origin-implementation-all-8-tickets.md`
  (includes build-time decisions, gotchas, accepted edges). **Deploy-day manual steps:** flag
  Mingjie VN + Minghui VN on growatt-vn via the new `/clients/{id}/suppliers` screen (verify
  spellings vs live BCCT; NEVER the HK namesake); Johnson stays zero-flag. **Next:** decide #14
  (unblocks VN-origin on growatt-vn prod) + flag the 2 NCC on prod when ready; then the 2
  standing action items (audit locked SHORTAGE sheets in prod; `missing_price` one-belt hole).
- **2026-07-11 (PM) — VN-ORIGIN SPEC + 8 TICKETS PUBLISHED; GitHub Issues = TRACKER OF RECORD
  (docs only, no code).** Spec `.ai/features/2026-07-11-vn-origin-materials/spec.md` (12 ADR
  synthesized; seam test duyệt: Tính recompute + route + pure-fn). Tickets = **TinsuAI/co #6–#13**
  (`ready-for-agent`; frontier = #6, #7, #8, #13; #8 shortage guard độc lập — legal urgency; graph
  #9←#6,#7 · #10←#9 · #11←#6 · #12←#7,#9,#11). **Convention mới:** implementation issues lên GitHub
  qua `gh` (5 triage labels đã tạo), specs/BACKLOG/api-requests vẫn `.ai/` — xem
  `docs/agents/issue-tracker.md` (viết lại) + `AGENTS.md`. Commits `c55e433` (spec+tickets) +
  `f9d79f2` (tracker switch) + handoff — **đều docs-only, local `main`, CHƯA push**
  (origin/main = `312e58d`). Session: `2026-07-11-vn-origin-spec-tickets-github-tracker.md`.
  **Next:** `/implement` từng ticket một (fetch `gh issue view <n>`), fresh context mỗi vé —
  design ĐÃ CHỐT, không grill lại.
- **2026-07-11 — VN-ORIGIN GRILL PART 2: CLOSED (design only, NO code).** All part-1 leftovers
  settled + phase 2 killed. **5 new ADRs** (`.ai/DECISIONS.md` 2026-07-11): (1) col-9 unknown label =
  **free-text** client-config `bang_ke.unknown_origin_label`, default "Không xác định", unknown bucket
  only; (2) flag flips always allowed, **ON→OFF = confirm + damage list** of locked sheets, append-only
  log, no effective-dating; (3) evidence store = **CO-side Postgres `co_supplier_evidence_events`**
  (fork-review re-affirmed CO over DH; boolean → **evidence record** with `evidence_kind`; `doc_no/doc_date`
  DEFERRED by user; Tính snapshots `supplier_key` + col-12/13 text per row); (4) **dncx preset → +E13**
  (growatt-vn on-spot = 83% E13; empty config = no filter, live configs untouched) + per-type counts on
  config form; (5) **phase-2 in-bloc DEFERRED until demand** — trừ-lùi workbook scan: Form D/AK/E = 0 hits,
  agency files **B, X, EUR.1, AI** only; `BẢNG THEO DÕI TỒN CO` = material inventory, NOT a C/O register;
  3 constraints pinned (form-scoped resolution; consignment-grain evidence; ATIGA partial = number-only).
  **Staff facts:** Growatt = 2 NCC Phụ lục X (**Mingjie VN + Minghui VN**, pure E15; beware distinct
  `MINGJIE INDUSTRIAL (HK)`); **Johnson = 0 NCC** → all-VNM treatment is CORRECT for Johnson; day-one
  beneficiary = Growatt only; no seed script (2 rows via UI). **Updated 7-ticket build order** in session
  `2026-07-11-vn-origin-grill-part2-close.md`; BACKLOG **FX1** (Form X missing in `co_forms.py`) + XX1
  marked DESIGNED. Next: build per ticket order, or the 2 standing non-grill action items (audit locked
  SHORTAGE sheets; `missing_price` hole).
- **2026-07-10/11 — VN-ORIGIN DESIGN GRILL (design only, NO code shipped).**
  `/grill-with-docs` on how CO handles VN-origin (and later in-bloc) materials. Output = **7 ADRs**
  (`.ai/DECISIONS.md`, 2026-07-10/11), 2 knowledge files, glossary, corrected memory. Full handoff:
  `.ai/sessions/2026-07-11-vn-origin-design-grill.md`. **Key finding:** VN-origin materials already sit
  in `hub.bcct_rows` as on-spot imports (E15/E13, `origin='VIETNAM'`, NCC in `consignee_name`) — Johnson
  6,272 rows / 1,252 codes / 64 NCC — but CO never lets `origin` touch `origin_status`, so they're all in
  VNM and RVC is understated. **No Data Hub change needed.** Rule decided: originating iff
  `origin_country`→VN **AND** supplier flagged for Phụ lục X (24/64 NCC sell mixed-origin, so the flag
  alone must not flip a row). **Decisions:** row grain = BOM line (CO already matches agency); split rows
  when a BOM line's lots differ in origin (render fan-out, key `(material_sequence, origin_status,
  column9_text)`); **shortage blocks issuance** (three-belt, ship independently — legal urgency);
  col (9) content = client-default+per-case mode (country|qualification_label) materialized at Tính;
  override key = `material_sequence` made version-aware (no UUID). **Prerequisite tickets (ordered):**
  (1) plumb `origin_country`+`consignee_name` into sheet material at Tính (col 9 blank in prod today);
  (2) re-key overrides to `material_sequence`; (3) shortage guard; (4) col-9 mode + `app/origin_country.py`;
  (5) per-row VN resolver. **Non-grill action items (don't drop):** audit already-locked SHORTAGE sheets
  in prod (claims written — legal exposure); resolve `missing_price` one-belt hole (leaks via save-route);
  `dncx` preset E11/E15 drops 13/38 E13-only VN suppliers. **Still open (deferrable):** supplier-flag
  curation UI + NCC name normalization; phase-2 in-bloc cumulation (Form D/AK not in `co_forms.py`).
  **NO git change this session** — `.ai/` docs only.
- **2026-07-10 — PROD BUG: CO session chết mỗi ~10 phút → FIXED (2 tầng) + MERGED + DEPLOYED.**
  User report (Johnson VN): "Tìm NVL thay thế" **mất kết nối mỗi ~10 phút**, `TypeError: Failed to fetch`,
  **mất sạch việc thay-NVL client-side** (phải làm lại từ đầu). **Root cause:** phiên CO = DH access token
  trong cookie `co_data_hub_session`, set 1 lần lúc login `max_age = expires_in or 600` (~10 phút — xác nhận
  `expires_in=600` với DH thật), **KHÔNG refresh** → hết hạn thì XHR guarded bị **303 sang trang SSO
  cross-origin** (không CORS header) → browser ném `Failed to fetch`. Dev không tái hiện (`CO_AUTH_REQUIRED=0`).
  **Fix 2 tầng — PR #4 → `origin/main`=`306e2b4` → job `Deploy demo` SUCCESS:**
  **(1) CO-side resilience:** `guard_response` trả **`401 {code:session_expired, login_url}`** cho request
  XHR (nhận diện `Sec-Fetch-Dest`≠document / `X-Requested-With` / JSON `Accept`), giữ **303 cho điều hướng
  trang**; `base.html` fetch-wrapper → overlay đăng-nhập-lại (mở tab mới, giữ trang) + **tự refresh & replay
  GET** (liền mạch, không mất việc). **(2) Refresh-token flow (trị gốc):** DH ship rotating `refresh_token`
  ở `/v1/auth/exchange` + `POST /v1/auth/refresh` (sliding idle-TTL, trần **7 ngày**, reuse-detection); CO
  tiêu thụ: cookie `co_data_hub_refresh` + route `POST /auth/refresh` + client silent-renew → **hết bị đá ra
  mỗi ~10 phút** (làm liên tục → phiên sống tới 7 ngày). Commits `84182cd`(fix guard)+`c8a5316`(api-request)
  +`8797d16`(feat consumer). **Verify:** suite **760 pass/10 skip** (+9 test); CO↔DH round-trip **THẬT** (SSO
  → refresh token thật → rotation+reuse-detection); **browser E2E** (Chrome thật, auth-on CO→DH thật: xoá
  session cookie→silent `/auth/refresh`→retry 200 không prompt; hết refresh token→overlay graceful).
  Session `.ai/sessions/2026-07-10-session-expiry-xhr-refresh-flow.md`; DH contract
  `.ai/api-requests/2026-07-10-session-token-refresh*.md`.
  **Deployed smoke (prod `barry-co` + nightly `demo-co`, cả hai `git_sha=306e2b4`):** XHR + phiên hết hạn
  → **401 `session_expired`** (hết `Failed to fetch` — root cause đã sửa **trên prod**); NAV → 303
  `/auth/login`; `POST /auth/refresh` không cookie → 401 `session_expired` (route mới live).
  **CHƯA verify trên deployed:** nhánh success có refresh token hợp lệ (200 + rotation) — mint credential
  trên DH live bị **permission classifier chặn**; 3 phương án ghi ở Open items của session summary.
  **GIT: 2 commit cuối phiên (docs handoff + guardrail) đã PUSH lên `origin/main`** — docs/hook only, không đổi
  app, CI chỉ chạy lại `Deploy demo`. Nhánh `fix/session-expiry-xhr-401` đã merged và **đã xoá** (local+remote).
  **Guardrail đã đổi:** `git push` và `gh pr merge` giờ **hỏi xác nhận** (PreToolUse `permissionDecision: "ask"`)
  thay vì bị chặn cứng — agent push/merge được nhưng user duyệt từng lần; các lệnh phá huỷ (hard reset, forced
  clean, force-delete branch, whole-tree checkout/restore, **force-push**) vẫn **chặn cứng**, và được kiểm TRƯỚC
  nhánh ask. **Hạn chế đã biết:** hook substring-match cả command string → lệnh chỉ *nhắc tên* pattern trong text
  (commit message, `grep`) cũng bị chặn oan; né bằng `git commit -F <file>`.**
- **2026-07-09 — TOOLING (no app change): synced + mattpocock/skills + git guardrails.**
  Local `main` synced 23 behind → `origin/main` (`ecd9179`, FF); then **`da6e381`** (chore/workflow) on top
  → ~~`main` ahead of `origin/main` by 1, UNPUSHED~~ **(RESOLVED 2026-07-10: `da6e381` went up as an ancestor
  of PR #4 → now on `origin/main`=`306e2b4`, deployed).** Installed the
  `mattpocock/skills` engineering set global at `~/.claude/skills/` (`/tdd`,`/handoff` now Pocock's;
  `rev/fix/discover` retiring), guide `~/.claude/skills-guide.md`. Enabled **project git guardrails**
  (`.claude/` blocks `push`/`reset --hard`/`clean`/`branch -D` for the agent). Session:
  `.ai/sessions/2026-07-09-skills-workflow-standardization-git-guardrails.md`; memory
  `[[mattpocock-skills-global-install]]`. **The `main = cfb3e6e` line lower down is now STALE** (real head `da6e381`).
- **2026-07-08 (PM2) — cross-dossier tồn contention REVIEWED (multi-hồ-sơ/1 công ty) + fix D + COMMITTED.**
  Branch **`feat/co-flow-guards`** (base `840fb74`): **`ceabdb5`** (feat #1/#2/D) + **`a0ec3f6`** (agent docs);
  `uv.lock`+`dev.sh` cố ý để uncommitted (local-only). Handoff:
  `.ai/sessions/2026-07-08-cross-dossier-review-substitute-stock-fix.md`. **`/code-review` 22-commit vs `origin/main`:** Standards SẠCH
  (0 hard, hợp 2 ADR); Spec = đa số "thiếu" là UI Pending có chủ đích + **1 lỗi precedence thật (c): resolver bỏ
  rơi override/client_default hợp lệ khi pin echo cũ unusable → rơi thẳng dh_latest — ĐÃ VÁ** (duyệt candidate
  theo precedence, kiểm usable từng bước; +3 test). Suite **746 pass / 15 skip**. Verdict:
  cơ chế cốt lõi ĐÚNG — chốt cứng (`record_sheet_lock` khoá `co_stock_rows FOR UPDATE`, net Σ claims
  case KHÁC, abort over-claim, sort chống deadlock); đường Tính/batch net claims qua
  `apply_used_qty(used_qty_by_lot)`. **Fixed D:** `/substitute-stock` (`co_case.py:~2553`) trước báo tồn
  **gross** (không trừ claims hồ sơ khác) → nay overlay `apply_used_qty` trước pool (mirror đường Tính);
  test `tests/test_substitute_stock_claims_overlay.py`. **Còn mở F** (cold-start no-snapshot → overclaim
  guard bị bỏ, `co_stock_ledger.py:198-204`) → BACKLOG **D2**. Chi tiết phân tích 6 kịch bản race: BACKLOG D2.
- **2026-07-08 (PM) — #1 BOM-selection + #2 substitute-search IMPLEMENTED (grill→tdd→e2e).**
  Branch **`feat/co-flow-guards`**, **all UNCOMMITTED**, suite **741 pass / 15 skip** (+12 new).
  Shipped: **#1a** one precedence resolver `resolve_selected_product_version` (honour-the-pin
  fix — snapshot writer no longer shadows the client-default layer); **#1b** provenance chip
  `.bom-version-why` + **batch BOM-selection modal** on "Tính tồn tất cả (SP)" + **save-mirror-leak
  fix** (only a DELIBERATE deviation becomes a case override, not every SP's echo); **#2**
  `app/substitute_discovery.py` stock-first discovery wired into the substitute-candidates search
  (stock-only NVL now findable) + smart lots-collapse. Grill wrote GLOSSARY (8 terms) + 2 ADRs +
  spec `.ai/features/2026-07-08-bom-selection-and-substitute-search.md`. Browser-verified on real
  `growatt-vn e2e-batch-real` (Playwright; auth toggled off→**restored =1**). **User caught a real
  bug in the old handoff:** `declarable_unmatched` = DH "no import match", NOT "missing catalog" →
  stock substitutes are declarable, not blocked. Full handoff:
  `.ai/sessions/2026-07-08-bom-selection-substitute-search-impl.md`. **Pending UI polish** (data
  flows, presentation only): batch inline picker row (optional), stock-first modal badges/dimming.
  **NEXT (user ask): review batch-flow logic for MULTIPLE dossiers per same company** — cross-dossier
  stock contention (claims overlay, overclaim guard) is the open correctness question.
- **2026-07-08 — batch auto-flow: "Tổng hợp NVL" tab + substitute correctness + BOM/catalog design review.**
  Branch **`feat/co-flow-guards`** (NOT on main; `840fb74..HEAD`, suite **729 pass**). Shipped: batch
  **"Tính tồn tất cả (SP)"** now calculates + PERSISTS every sheet (`calculate-all`); **"Tổng hợp NVL" is a
  first-class origin sub-view/tab** (Variant A + undo-per-row + collapsible ledger); reseed `e2e-batch-real`
  with **real DH codes** (root cause of "no BOM": app resolves BOM by product `code`, not `bom_product_code`);
  no-BOM sheets no longer report "✓ Đủ tồn"; **proved** substitute stock accounts for whole-lô consumption
  (`test_substitute_shared_pool.py`, no bug). **3 OPEN design items** (agreed, NOT built) — see handoff
  `.ai/sessions/2026-07-08-batch-tong-hop-tab-bom-catalog-review.md`: **#1** BOM-selection table + fix the
  shadowed client-default precedence bug (`attach_case_bom_snapshot` pre-pins latest, ignoring
  `client_defaults`); **#2** substitute search → stock-first ⟕ catalog (stock-only NVL currently
  unfindable); **#3 DEFERRED**: compliance nuance for stock-only substitutes (`declarable_unmatched` /
  DC3c) — **review before building #2's picker**.
- **2026-06-25 — bảng kê blank-export root cause + fix (`763fe74`, on `main`, PUSHED → CI deploying).**
  Client report "xuất bảng kê vẫn bị trống" = fast `/calculate` truyền catalog rỗng → materials mất
  TÊN **và** `customs_relevance` → rác/`declarable_unmatched` không bị loại → lọt export thành dòng
  trống (prod johnson: 1019/1909 trống → 0 khi có catalog). **OVERTURNS 2026-06-20 DC2 tên-theory**
  (DH có đủ tên). Fix: nạp catalog ở 4 chỗ build (Tính/load-bom/preview/recalc) + fallback tên/HS từ
  CO-stock; **export = render thuần** (customs_relevance round-trip form + web fold `declarable_unmatched`
  "không xuất" → export == web grid); per-sheet **undo/redo server-side** sống qua save; autosave
  2s→30s configurable. Suite **706 pass**; e2e + file-export + screenshot johnson thật verified.
  Session: `2026-06-25-bangke-blank-export-undo-export-parity.md`. **HARD RULE mới: export KHÔNG có
  logic riêng — mọi logic ở bước Tính** (memory [[bangke-export-equals-web-invariant]]).
- **`main` = `origin/main` = `cfb3e6e`** (pushed). **prod = nightly = `c483673`** (v0.16.0; verified
  `barry-co.tinsu.ai/version` + `demo-co.tinsu.ai/version` both `c483673`, build 2026-06-19T15:0x) — the
  two docs commits on top (`56f750d` reconcile + `cfb3e6e` handoff) are docs-only, so CI/CD will advance
  prod/nightly git_sha to `cfb3e6e` with no app change. Tree clean except `uv.lock` (unrelated, uncommitted).
  **v0.16.0 RELEASED** (`bfd7aff`) — the 3 features below + CHANGELOG shipped; `c483673` renders
  `**bold**` in changelog bullets on the "what's new" UI.
- **This session shipped 3 features** (all live on `c483673` / v0.16.0):
  1. **NVL thay thế — ưu tiên lịch sử** (`4e40b63`): substitute modal pins materials previously used to
     replace this NVL in past **locked** dossiers to the TOP, badge "↺ đã từng thay ·N", ranked by usage
     count; injects history substitutes even when Data Hub never proposed them. CO-owned signal mined from
     case `origin_sheet_states[*].material_overrides` — **no Data Hub dependency** (distinct from DH-side
     ranking #4). See `app/substitution_history.py`.
  2. **Graceful error pages** (`a13661a`): global `HTTPException`/`RequestValidationError` handler renders
     a styled `error.html` for browser navigations, keeps JSON for fetch/XHR — a failed native form submit
     no longer dumps a raw `{"detail":…}` blob. Export "bảng kê HQ" form now submits via fetch → downloads
     on success, toasts the error in place.
  3. **Global fetch error surfacing** (`bad2c1a`): `base.html` wraps `window.fetch` → ANY non-ok response
     auto-toasts the server `detail` (no more silently-swallowed AJAX errors). `{quietError:true}` opt-out
     for self-handled/background calls; toasts de-dupe by visible text; `co_case` `toast()` delegates to
     the shared global `coToast`.
- Tests: full suite **691 pass, 10 skip** (+`test_substitution_history.py` 6, +`test_substitute_history_route.py`
  3, +`test_error_handling.py` 9). Browser-verified on live `:8001` w/ real growatt-vn data: history
  pin/inject, 404 → error page, blocked export → toast (stays on page), global fetch wrapper.
- **DATA NOT PURGED.** prod `co-db-1` có cases thật (johnson-vn) + Growatt cost-allocation. **Do NOT
  seed/test against prod; dùng nightly HOẶC local dev DB.**
- Cost-allocation, Mục 6, empty/no-BOM guard (#13c), missing-price guard, ★ BOM default, wizard — vẫn nguyên.

## Recent Changes (this session — live on `c483673` / v0.16.0, pushed to main)
- `4e40b63` feat(origin): pin previously-used NVL substitutes (`app/substitution_history.py`, route integ,
  badge + top-pin in `co_case.html`, `.origin-substitute-prior` CSS, 9 tests).
- `a13661a` feat(web): graceful error handling — `error.html` + `error_response()`/`_prefers_html_error()`
  in `main.py` (HTTPException + RequestValidationError + CaseClosedError/DH handlers routed through it);
  export form → fetch+download+toast; `.error-page` CSS; 9 tests.
- `bad2c1a` feat(web): global `window.fetch` wrapper in `base.html` (auto-toast + quietError + dedup).
- `bfd7aff` release: v0.16.0 — substitute-history priority + graceful error handling (CHANGELOG + version bump).
- `c483673` fix(whats-new): render `**bold**` in changelog bullets safely on the "what's new" UI.
- `56f750d` docs: **reconcile BACKLOG/STATUS with shipped work** (verified 16 items vs code at `c483673`
  via 5 parallel agents) — **NOT pushed yet**. See session `2026-06-19-backlog-status-reconciliation.md`.

## Next Steps (priority order)
000000. **2026-08-17 client-question batch is CLOSED and LIVE on `72de4eb` — do NOT re-diagnose it.** The
   "thiếu đơn giá on a fully-priced bảng kê" report was `lvc_missing_price` firing on rác, the "Đã chốt 0
   sheet" was the two bulk routes stamping `"calculated"` blind, and the F5 difference was that same stamp —
   all fixed and verified in-container against the live case. **What remains is not CO code:**
   (A) **Waiting on the agency for Q1** — the 53 codes in VNG26020033 have never appeared in any tờ khai;
   they need to say whether the `1000…`-series are internal codes needing a DH `code_mappings` row, domestic
   VAT purchases, or pre-2025-04-18 imports. A mapping is `data-hub` repo work (guardrail).
   (B) **Operator action on the case** — clear the 35 + 19 `declarable_unmatched` rows from "Tổng hợp NVL"
   (the flag is ON for johnson-vn now), Tính lại, then Chốt.
   (C) **Decide the D2 siblings** — `co_case.py:3358` ("Lưu bảng kê") + `:3556` (mở chốt) stamp
   `"calculated"` without re-deriving, same as the two routes just fixed. File as issues if wanted; `:3556`
   needs its own approach (reopen has no recalculation before it).
   (D) **Optional cleanups** — noise rows still enter the VNM sum (`co_case_context.py:2455-2460`, inert) and
   the LVC "Tạm đạt/Tạm tính" + "Thiếu tồn CO N dòng" labels (`:2461`, `:3208-3226`, cosmetic).
00000. **CO 524 fixes SHIPPED + DEPLOYED 2026-07-27 (see Current State).** Two follow-ups, neither urgent
   (both no-524): (A) add `include_material_identity="true"` to the narrow fetch (`data_hub_client.py:962-966`
   in `origin_invoice_matches`) for item_code/material_identity display parity on non-origin cold window —
   shared with the origin tab, so needs its own test before shipping (could shift origin behavior). (B) **H2
   async-offload:** run `co_case_context` / the substitute catalog pull off the event loop in
   `co_case_detail`/`co_case_step`/`co_case_origin_sheet_substitute_candidates` (all `async def` calling sync
   pulls) — removes the residual ~15s first-open stall and stops one slow request stalling others.
   **Parallel track:** user is running a `data-hub` repo session for feedback #1 (BCCT-import Apply disabled +
   yellow/green unclear) — CO side has nothing to do there.
0000. **CODE-VOCAB BATCH #18–#22 ALL CLOSED 2026-07-17 (PM3); #15/#16/#17 also closed. `TinsuAI/co` = 0 open
   issues.** See Current State. **Nothing agent-ready remains on the tracker.** Do NOT reopen #19 tasks 2/3
   (task 2 obsolete post-#21; task 3 unsafe — `bom_product_code`≠`product_code` coexist) or re-litigate #22
   (fallbacks are safe by the DH schema — verified vs live data, both clients). Do NOT re-litigate the #14
   design (ownership-partition shipped).
000. **REMAINING = user-manual growatt-vn prod ops (NOT code):** (1) run calibrated regex seed
   `scripts/seed_growatt_vn_allocation.py` (`b98156a`) on prod `co-app-1` + nightly `nightly-co-app-1`
   (`docker exec -i {c} /app/.venv/bin/python - < scripts/seed_growatt_vn_allocation.py` via `ssh tinsu`;
   vet container names + locked cases first) — applied LOCALLY only. (2) flag `CONG TY TNHH MINGJIE VIET NAM`
   + `CONG TY TNHH MINGHUI VIET NAM` on `/clients/growatt-vn/suppliers` (verify spelling vs live BCCT; NEVER
   the HK namesake). Johnson = 0 flag. Old standing items (audit locked SHORTAGE sheets; `missing_price` hole)
   **ĐÃ XONG 2026-07-11**.
00. **(DONE 2026-07-12 — see Current State)** ~~Build VN-origin feature theo 7-ticket order~~ trong
   `.ai/sessions/2026-07-11-vn-origin-grill-part2-close.md` — design đã chốt 12 ADR, KHÔNG cần grill thêm.
   **Spec (ready-for-agent): `.ai/features/2026-07-11-vn-origin-materials/spec.md`** — tổng hợp 12 ADR
   + seam test đã duyệt (Tính recompute + route + pure-fn). **Tickets = GitHub Issues TinsuAI/co
   #6–#13 (tracker of record từ 2026-07-11**, label `ready-for-agent`; archive copies
   `.ai/features/2026-07-11-vn-origin-materials/issues/`; col-9 tách 2 vé: #9 materialization +
   #10 flip lifecycle; frontier khởi đầu = #6, #7, #8, #13). Convention mới:
   `docs/agents/issue-tracker.md` — implementation issues lên GitHub, specs vẫn `.ai/`:
   (1) plumb `origin_country`+`consignee_name`+`supplier_key` vào sheet material tại Tính; (2) re-key
   overrides → `material_sequence` version-aware; (3) shortage three-belt guard (độc lập, legal urgency);
   (4) col-9 mode + `app/origin_country.py` + `bang_ke.unknown_origin_label`; (5) `co_supplier_evidence_events`
   migration + curation screen + flip flow; (6) per-row VN resolver; (7) dncx preset +E13 + per-type counts
   (nhỏ, độc lập). Đồng thời 2 action items đứng riêng: audit locked SHORTAGE sheets prod; vá `missing_price`
   one-belt hole. Growatt seed = flag 2 NCC qua UI (Mingjie VN + Minghui VN — check spelling `consignee_name`
   lúc build); Johnson = 0 flag.
0. **(REVIEWED 2026-07-08 PM2) Batch-flow cho NHIỀU hồ sơ / cùng 1 công ty — xong review + fix D.**
   Kết luận: chốt cứng + đường Tính/batch đều net claims cross-dossier ĐÚNG; `/substitute-stock` báo
   gross → **đã vá (D)** overlay `apply_used_qty`. Còn **F** (cold-start overclaim-guard bị bỏ) → BACKLOG
   **D2** (hẹp). Full phân tích 6 kịch bản race + verdict trong BACKLOG **D2**. **Next:** cân nhắc vá F
   (chặn Chốt khi chưa có snapshot) HOẶC gói `feat/co-flow-guards` để `/code-review` so `840fb74` + commit
   (#1/#2/D đều UNCOMMITTED). Tùy chọn: seed multi-dossier e2e (lock A → tính/thay-NVL B) làm regression sống.
0b. **(2026-06-25 follow-ups)** — (a) **P2 perf** (BACKLOG): fast `/calculate` giờ pull thêm catalog
   (~13k, cache 90s) cho tên+`customs_relevance` → tối ưu bằng materialize vào snapshot tồn. (b) Sheet
   **đã CHỐT trước fix** giữ materials `customs_relevance=0` → export vẫn theo bản cũ; cần mở chốt +
   Tính lại để dọn (KHÔNG vá ở export — đúng nguyên tắc). (c) Verify prod sau deploy: `curl …/version`
   + export 1 hồ sơ johnson thật ra 0 dòng trống.
1. **Ranking mã thay thế #4 (DH-side)** — history-priority (CO-side, shipped) only floats *previously-used*
   codes; the root issue that a high-score-but-low-stock candidate gets buried (FINDINGS #2) is still
   DH-side. Needs `.ai/api-requests/` for a score+feasibility blended ranking from Data Hub.
2. **Phase 2 bulk/wizard rework** — **backend đã BUILT, KHÔNG phải placeholder**: routes
   `preview_stock_all_route` / `bulk_substitute_route` / `bulk_lock_route` (`co_case.py:1635/1646/1732`)
   chạy được; nút "Chạy tồn"/"Chốt tất cả" bị **gate tắt cố ý** ("đang xây dựng", `834e1da`, routes untouched).
   - Quyết định: re-enable batch flow mạch lạc HAY retire — pre-flight summary trước batch-lock (sheet nào lock/skip + lý do).
   - Wizard: vẫn **chọn BOM version im lặng** — show "BOM: #N (mặc định)" trước Tính (`co_case.html:6018-6021`, chưa đọc dataset version).
3. **Client feedback 2026-06-05 còn lại:** **#12** số tồn TỔNG = **PARTIAL** (`#13a c9f5183` đã gộp thiếu-tồn
   per-material `co_case_context.py:1675-1716`, nhưng **chưa có cột SUM tổng across SP** — `co_case.html:5782` chỉ "Thiếu tồn: N mã/M SP"); **#4** ranking (DH-side, = #1).
4. **Correctness (backlog, ưu tiên):** **DC3a** update-BOM còn ship rác · **DC3c** `declarable_unmatched=0 → LVC thổi`
   **chưa chặn cứng** Chốt/Xuất (DC3b export đã strip render-time, nhưng sheet pre-mig-078 còn lọt tới khi re-Tính);
   **B6** re-scoped → verify **độ chính xác FX** (toggle native↔VND đã chạy, hết "luôn VND").
5. `compact` PDF profile toggle; **EX1** column-K ref; **XX1** NVL có xuất xứ cột M-N (mới blank M-N tạm).
   Backlog mở: **M1** (cả 2 sub-bug còn) · **D1** (còn C/E/F + parity harness) · **P1** (~40s) · **T1** (DB isolation) · **DC2** · **CS3** park ×2 · **LK1** review rộng.

## Notes for Next AI Session
- **Prod perf diagnosis pattern (2026-07-27, reusable):** measure a cold path read-only IN the prod container
  before/after — `ssh tinsu` → `docker exec -i co-app-1 python -` piping a harness that builds
  `data_hub_client_from_env()` (picks up the prod service token from the config file) + wraps `client._get`
  to count HTTP calls per path and time them. This is how the 524 was root-caused (124.88s, 74 bcct pages)
  and the fix verified live (0.31s / 15.69s). `co_case_source_context`/`origin_invoice_matches`/
  `material_catalog` are read-only (safe on prod); do NOT call `preload_co_case_origin_context` on prod (it
  writes the case record). App access log has NO request duration and a 524 still logs `200 OK` after the
  origin finishes — don't trust the access log for slow-request timing. **Engineering lesson:** when a narrow
  replacement for a heavy DH call is introduced, audit EVERY call site of the heavy call — the origin tab got
  `origin_invoice_matches` in 2026-05, but the shipment light path AND the substitute modal kept the full pull
  for over a year → two separate 524s.
- **HANDOFF CONVENTION (decided 2026-07-17 — do the right thing, not ad-hoc):** session-end handoff =
  **`/v_handoff`** ONLY (writes `.ai/sessions/YYYY-MM-DD-*.md` + overwrites `STATUS.md`). Do NOT hand-roll
  the summary, and do NOT use Pocock's global **`/handoff`** for session-end — that one compacts the live
  conversation into a fork-bridge file (for `grill → prototype → back`), a different artifact/format.
  `/handoff` is ONLY for a deliberate mid-work fork (rare here: the harness already auto-summarizes long
  context). **Known hazard:** `CLAUDE.md`'s "Session end: /handoff" line still points at the wrong one;
  pinning the split into `CLAUDE.md` + a `feedback` memory is **PENDING user approval** (offered, not yet done).
- **BACKLOG is freshly reconciled vs code (2026-06-19, `56f750d`)** — markers are accurate as of `c483673`.
  Newly-closed since last backlog edit: **B7** (`cb3504b`), **CS1** (`ca11c37`); **D1** mostly done
  (`2c856da`, only C/E/F + parity left); **B6** re-scoped (toggle works, verify FX only); **DC3b** export
  strips rác render-time. Still-open w/ refreshed refs: **M1**, **DC3a/DC3c**, **#12** (partial), wizard "BOM #N".
- **Substitution history** (`app/substitution_history.py`): mines `origin_sheet_states[sp].material_overrides`
  across the client's cases; counts ONLY sheets with `status=="locked"` (committed dossiers); keyed by the
  base BOM `material_code` (= what the substitute-candidates route receives). 60s TTL cache, busted via
  `invalidate_co_case_source_cache` (called on lock/reopen). Pure `build_substitution_history` is unit-tested;
  route pins via `previously_used`/`history_rank`; client floats them in `reorderRecommendedByStock`.
- **Error handling pattern:** `error_response(request, code, detail)` in `main.py` picks HTML-vs-JSON via
  `_prefers_html_error` (browser = `Sec-Fetch-Dest: document` OR (`text/html` Accept & no `X-Requested-With`);
  fetch = JSON). New error-prone routes get this for free. **Global fetch wrapper** (`base.html` `<head>`)
  toasts every non-ok fetch — pass `{quietError:true}` for background/self-handled calls; `coToast` de-dupes.
  500s deliberately NOT caught (keep dev tracebacks); add a friendly 500 page only if prod needs it.
- **Sequential pipeline (quan trọng):** origin sheets xử lý **tuần tự + xen kẽ** — `/calculate` sheet N
  đòi N-1 đã **locked**. Wizard xen kẽ tính→chốt là đúng thiết kế.
- **★ chỉ render khi có DH BOM:** picker version chỉ populate từ DH BOM artifacts; local dev không có cho
  hầu hết SP. Ngoại lệ: **`growatt-vn` PV00.0048500 CÓ** DH BOM #3 (~300 NVL) → dùng để verify ★/wizard.
- **Local dev = auth-off + DB-mode** (`.env`: `CO_AUTH_REQUIRED=0`, `BARRY_DATABASE_URL`→`barry_co`,
  `DATA_HUB_ENABLED=1`→DH `:8754`). `npm run co:serve` = `:8001` (--reload watches app/ *.py/*.html/*.css).
- **Scratch e2e harnesses (gitignored, under `.ai/screenshots/`):**
  - `2026-06-19-substitute-history/seed_and_shoot.py` (+`shoot.cjs`) — seed locked-history case + drive
    modal; opens it via a synthetic `[data-origin-substitute-trigger]` (run-stock button disabled, and
    hand-seed `-vn` rows don't render in detail).
  - `2026-06-19-error-handling/seed_and_shoot.py` (+`shoot.cjs`) — 404 page + blocked-export toast;
    `global_fetch_check.cjs` — global fetch wrapper (toast/quietError/dedup).
  - `2026-06-19-co-flow-walkthrough/` — earlier lifecycle/wizard harnesses + FINDINGS.md.
  - Run with `.env` sourced + `PYTHONPATH=$(pwd)` + `NODE_PATH=$(pwd)/node_modules` via `uv run python`.
- **Verify after merge:** `curl …/version` git_sha (prod=barry-co, nightly=demo-co). **NEVER** ghi literal
  CI-skip token trong commit msg → skip cả pipeline ([[ci-skip-token-in-commit-msg]]).
- **Test env:** full file-mode (NO `.env`) = **691 pass**. DB/in-container e2e cần `.env`.
- PR convention (rule của user): commit/PR English, **không** trailer/co-author AI.
