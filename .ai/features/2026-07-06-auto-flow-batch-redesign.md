# Feature: Luồng CO tự động hoá — batch tính + sheet tổng hợp thay NVL thiếu

Source: khách phản hồi "flow quá nhiều thao tác" (1 lô 30 SP = 30 sheet). Scoping mở màn
`.ai/sessions/2026-07-06-auto-flow-batch-substitute-scoping.md`. Bản này = **discovery/design**
(dùng skill `codebase-design`), **đã VERIFY code** (session 2026-07-06). **Chưa code** — chờ user
chốt các quyết định ở cuối trước khi vào `/tdd`.

## Flow lý tưởng (khách)
Nhập TKX → auto load SP + BOM từng SP → **auto tính tất cả sheet**. Thiếu tồn → gom NVL thiếu vào
**1 sheet tổng hợp**; ở đó thay **phần thiếu** hoặc **thay hết** sang NVL khác, **sync xuống từng
sheet SP**. Vẫn sửa được **từng sheet riêng** để tối ưu LVC. Có nút **check/tính lại** để đảm bảo
không tranh tồn / lỗi logic.

## Sự thật mở khoá cả redesign (VERIFIED C3)
**Thứ tự lock KHÔNG đổi kết quả phân bổ tồn.** Lot→sheet được cố định ở bước **TÍNH**, theo
`origin_product_order` (thứ tự index) chạy trên **một** pool per-material dùng chung
(`prepare_case_origin_products` → `stock_pool` `co_case_context.py:816`, trừ tại chỗ `:2318`).
`record_sheet_lock_claims` (`co_case.py:177` → `co_stock_ledger.py:150`) chỉ **persist** các dòng đã
tính; an toàn tương tranh là `FOR UPDATE … order by source_row` (StockOverclaimError nếu âm).

⇒ **Gate tuần tự per-index là tiện ích audit/consistency, KHÔNG phải ràng buộc thuật toán.** Có thể
relax an toàn thành **material-overlap** — đúng như câu hỏi của khách: chỉ NVL **chung** mới tranh
tồn của nhau.

## Verified facts (session 2026-07-06, số dòng hiện tại)
| Claim | Kết quả | Vị trí thật |
|---|---|---|
| Pool per-material, object dùng chung, trừ tại chỗ | CONFIRMED | `co_case_context.py:1746` (key `:1783`), calc `:785/816/2318` |
| Gate thuần index (`previous_unlocked`/`later_locked`), **0 nhận biết NVL** | CONFIRMED | `co_case_context.py:1396` (vars `:1407-1416`; bản song song cho nút `:1304-1313`) |
| Lock order không đổi allocation; ledger chỉ persist; FOR UPDATE order-by-source_row | CONFIRMED | `co_case.py:177`, `co_stock_ledger.py:150/205-218` |
| 3 route batch chạy được | CONFIRMED | `co_case.py:1686` preview · `:1697` bulk-substitute · `:1783` bulk-lock |
| Nút batch **gate tắt** ("đang xây dựng"), JS + route còn nguyên | CONFIRMED | `co_case.html:913-920` (`834e1da`+`c42f17a`); handlers `runBulkLock:5938`/`initBulkLock:5964`/bulk-substitute `~5783-5877` không bind (thiếu `data-*`) |
| DC3a: propose-bom **lọt rác** (chỉ loại `deleted`+mã rỗng) | CONFIRMED | `co_case.py:2680` (loại deleted `:2695`, rỗng `:2721`); guard duy nhất = sheet phải `locked` `:2627` |
| DC3c: `declarable_unmatched` **bị loại khỏi export** nhưng **vẫn cộng 0 → thổi LVC** | CONFIRMED (chỉ guard mềm) | thổi `co_case_context.py:1913-1923`; `_EXPORT_EXCLUDE` `origin_material_filters.py:9`; guard mềm `lvc_missing_price:2604` |
| Mode "thay phần thiếu vs thay hết" | **KHÔNG có** | `bulk_substitute_route:1697` bắt caller liệt kê từng `{product,material,substitute}` (`:1723-1728`) |

## Modules & seams (codebase-design)

Đặt module **sâu**: nhiều hành vi sau **interface** nhỏ, tại **seam** sạch, test qua chính interface.

### M1 — `sheet_action_error` — deepen tại seam SẴN CÓ *(gate relax)*
- **Seam thật** (2 caller): action-check (route calculate/lock/reopen) + tính cờ nút (`:1304-1313`).
- **Interface giữ NGUYÊN:** `origin_sheet_action_error(case, product_code, action) -> error | None`.
  Callers, bulk-lock (`:1802`) không đổi. Chỉ **implementation** sâu thêm.
- **Depth mới:** thay so-sánh-index bằng **đồ thị giao NVL**. Chặn tính/chốt N chỉ khi có sheet
  **index thấp hơn & chung ≥1 mã NVL** với N còn chưa `locked` (giữ deterministic trong từng
  connected-component để claim ledger ổn định — xem Risk R1). Sheet **rời rạc** (không chung NVL)
  tính/chốt **độc lập**, kể cả song song.
- **Deletion test:** xoá module ⇒ mỗi caller tự suy "sheet nào phải chờ" → phình ra N chỗ. Nó
  earning-its-keep. Giữ 1 module, deepen.

### M2 — `plan_shortfall_substitution` — module SÂU MỚI *(thay phần thiếu vs thay hết)*
- **Vấn đề:** `bulk_substitute_route` interface **nông** — caller phải tự expand từng triple.
- **Interface nhỏ:** `plan(case, material_code, substitute_code, mode, scope) -> {triples[], summary}`
  với `mode ∈ {"only_short","everywhere"}`. Trả về đúng tập `{product,material,substitute}` + summary
  kiểu *"NVL A thiếu 2/10 SP → thay 2"* vs *"thay cả 10"*.
- **Seam:** nằm **trên** `bulk_substitute` (giữ nó làm primitive đã e2e-verified). Route mới gọi
  `plan()` rồi feed triples vào máy cũ. **Không** viết đường thay song song.
- **Testable:** thuần hàm (case-state → triples), không side-effect → test qua interface dễ.

### M3 — Sheet tổng hợp = **VIEW/read-model**, KHÔNG calc path *(hard rule 2026-06-25)*
- **Invariant** [[bangke-export-equals-web-invariant]]: mọi logic ở bước **Tính**; view chỉ **chiếu**.
- **Interface:** `case_shortfall_rollup(case) -> [{material, needed, available, short_by,
  affected_products[]}]` — projection trên state **đã tính** của từng sheet.
- Nhiều khả năng đã có sẵn qua `whole_case_stock_summary` / `case_missing_stock_summary` (muc6). Redesign
  = **wire** rollup ↔ M2, **không** đẻ calc mới. Thay đổi sync xuống sheet qua `material_overrides` cũ.

### M4 — Guards DC3a/DC3c = **hard-block seams** *(PREREQUISITE)*
- Nhỏ, localized, nhưng **phải trước** batch: batch-recalc **nhân lỗi ra cả lô**.
- DC3a: `build_bom_proposal_rows` thêm filter noise (nếu user muốn). DC3c: hard-block/force-recalc trên
  `declarable_unmatched` ở lock/export. **Cả hai cần user chốt** (xem Open Questions).

### M5 — Auto-flow orchestration — orchestration mỏng trên module sâu sẵn có
- `TKX → load SP+BOM (sẵn) → whole-case calc (sẵn) → shortfall rollup (M3)`. Chủ yếu **wiring**;
  rủi ro thật là M4 (nhân lỗi) + M1 (thứ tự). Không thêm calc mới.

## Scope theo slice (thứ tự = phụ thuộc)
- **Slice 0 — Guards M4 (chặn trước): ✅ DONE (uncommitted, working tree) 2026-07-06.** Test-first (`/tdd`).
  - DC3c: `enrich_origin_product` đánh cờ `lvc_declarable_unmatched` (mirror `lvc_missing_price`,
    `co_case_context.py:~2610`); `calculated_sheet_status` park sheet → `bom_loaded` (`co_case.py:~1965`)
    ⇒ lock (status≠calculated) + export (bom_loaded blocker) từ chối cho **cả** single & bulk-lock.
  - DC3a: `build_bom_proposal_rows` skip `is_bom_technical_noise(material)` khi row KHÔNG bị thay thế
    (đồng nhất bảng kê; giữ substitute chủ đích) (`co_case.py:~2700`, import `is_bom_technical_noise`).
  - Tests: `tests/test_declarable_unmatched_guard.py` (8) + 2 case DC3a trong `test_technical_noise_filter.py`.
  - **`/code-review` (2 trục, sub-agent song song) → đã vá 2 finding:**
    - *(Spec)* DC3c ban đầu chỉ chặn qua `calculated_sheet_status`; `co_case_origin_sheet_save`
      (`:2985`) + `bulk_substitute_route` (`:1772`) **hardcode** status `"calculated"` → lọt. Vá:
      **defense-in-depth** re-check `lvc_declarable_unmatched` ngay tại `origin_sheet_action_error`(lock)
      + `origin_sheet_export_blockers` (mirror guard `missing_bom`) → hard-block **route-agnostic**.
    - *(Standards)* docstring biện minh theo VNM (hàm ý lọc `non_origin`) trong khi code chặn MỌI
      unmatched → reword docstring (giữ code rộng, an toàn hơn; unmatched có thể chưa có origin_status).
    - Ghi chú: guard `lvc_missing_price` có **cùng điểm yếu single-point** (pre-existing) — OUT OF SCOPE
      slice này, note lại để cân nhắc defense-in-depth tương tự sau.
  - **Full suite 711 pass / 15 skip**; server `:8001` reload sạch (HTTP 200). Chưa commit (theo convention).
- **Slice 1 — Gate relax M1: ⚠️ ĐỔI HƯỚNG sau discovery (2026-07-06).** Overlap theo `material_code`
  **KHÔNG an toàn** — xem discovery dưới. Nếu làm gate-relax phải trên **tập LOT** (alias-expanded qua
  pool), + chỉ giữa sheet **đã tính**, + fallback conservative cho draft/bom_loaded. To + rủi ro; giá
  trị biên thấp vì whole-case calc đã đúng. **Đề xuất: bỏ gate-relax, đi thẳng batch UI (Slice 2/3).**
- **Slice 2 — M2 shortfall-plan + batch UI:**
  - **✅ BACKEND DONE (commit) 2026-07-07.** `app/substitution_plan.py` = `plan_shortfall_substitution`
    (pure; only_short/everywhere, loại locked, carry name/uom/hs/norm) — 6 tests. Route mỏng
    `POST .../origin/bulk-substitute-plan` trả `{substitutions, summary}` (UI xem "thay N vs thay M" rồi
    POST `/bulk-substitute` áp). Refactor behavior-preserving: tách `allocate_whole_case_preview`
    (whole_case_stock_summary delegate) để plan lấy allocated case. +2 smoke test. **Suite 719 pass.**
  - **✅ M3 rollup DONE 2026-07-07.** `case_shortfall_rollup` (`co_case_context.py`) pivot allocated case
    (product-centric) → **material-centric**: 1 dòng/NVL thiếu ≥1 sheet, tổng cần/tồn/**thiếu (đơn vị)** +
    `using[SP]` (thay hết) + per-SP short qty + LVC/status cho drill-down. Wired `preview-stock-all` +
    `bulk-substitute` (mỗi mutation trả `rollup` mới → server-authoritative). 3 tests. **Suite 722 pass.**
  - **✅ UI ĐÃ CHỐT HƯỚNG (judge panel 2026-07-07).** Prototype 3 biến thể
    (`.ai/prototypes/2026-07-07-sheet-tong-hop-prototype.html`) → panel 4 expert (UX/consistency/
    info-design/cost) **nhất trí Variant A** (bảng thiếu tồn tập trung): A 4.5/5/4.5/5 · B 3.5/3/2.5/3 ·
    C 3.0/2/3.0/2. **Giải pháp build:**
    1. **Spine = bảng material-centric** (1 dòng/NVL thiếu: cần/tồn/thiếu + "thiếu N/M SP" + Thay…).
       = M3 `case_shortfall_rollup` (pivot `case_missing_stock_summary` short-per-SP → per-NVL, + usedBy
       cho "thay hết"). **Lưu ý cost judge:** summary hiện product-centric, chỉ emit short-per-SP → cần
       rollup material-centric (usedBy chưa có) — chấp nhận vì đúng mental-model khách ("NVL A thiếu 2/10 SP").
    2. **Reuse rich modal** `.origin-substitute-modal` qua `openBulkSubstitutePicker` (muc6 đã có stage-mode:
       tabs Khuyến nghị/Tìm kiếm + filter + badge "↺ đã từng thay" + score + đủ/thiếu) — **thêm scope toggle**
       (thay phần thiếu `only_short` / thay hết `everywhere`) wired vào `bulk-substitute-plan` (đã build). Đây
       là interaction MỚI duy nhất.
    3. **Graft B →** phase ribbon mảnh (Tính→Xử lý→Review&Chốt) dùng idiom `owz` cũ, KHÔNG stepper mới
       (step-state = thứ làm hỏng UI cũ `834e1da`).
    4. **Graft C →** drill-down dot-strip per-SP (đủ/thiếu/không-dùng) + LVC + trạng thái locked/DC3c-blocked
       trong dòng mở rộng — KHÔNG full matrix (matrix chết ở 30 SP + cần endpoint material-centric mới).
    5. Re-enable nút gated `co_case.html:913-920` (+`data-*`/URL) → thừa hưởng run-stock/bulk-substitute/bulk-lock.
    - Verdict lưu ở `.ai/prototypes/2026-07-07-sheet-tong-hop-NOTES.md`. Sau khi build: xoá prototype + switcher.
- **Slice 3 — M3 sheet tổng hợp (VIEW):** wire rollup ↔ plan; sync xuống qua overrides.
- **Slice 4 — M5 auto-flow (TKX → auto tính tất cả):** orchestration, sau khi 0+1 chắc.

## Logic & đồng bộ batch (VERIFIED 2026-07-07 — 4 concern của user)
1. **Phân bổ NVL vào SP (L1) — "hợp lý" = tuần tự + FIFO ngày tờ khai, KHÔNG optimizer.** 1 pool chung
   per-material; SP tiêu thụ theo `origin_product_order` (SP trước ăn tồn trước), lot trong 1 mã sort
   `co_stock_allocation_sort_key` (`co_case_context.py:1825`): usable→có-remaining→có-value→**declaration_date ASC**.
   SP hết tồn ⇒ `allocation_status="shortage"`. **Lever duy nhất = "Đổi thứ tự sheet"** (`co_case.html:979`
   post `origin_product_order`). **Quyết định: GIỮ policy này** (deterministic, đúng tinh thần trừ-lùi);
   batch chỉ **phơi bày** thứ tự + cho reorder (KHÔNG viết optimizer mới — rủi ro parity cao). Drill-down
   đã hiện SP nào thiếu bao nhiêu → staff reorder nếu muốn SP khác chịu thiếu.
2. **Thay hết/thay phần thiếu phải TÍNH LẠI delta (L2) — server ĐÃ làm đúng.** `bulk_substitute_route`
   ghi override → `mark_origin_sheets_stale` từ index sớm nhất → `recalculate_origin_sheet_edits` từng sheet
   **theo thứ tự** (rebuild rows, đổi mã, phân bổ tồn cho **chính mã thay thế**, tính lại VNM/LVC) → re-run
   `whole_case_stock_summary`. **Quan trọng: mã thay thế cũng có thể THIẾU tồn** → aggregate phải hiện
   shortfall **tính lại**, KHÔNG mark "đã xong" mù quáng. Client LVC chỉ là "(live)" tạm tính (`co_case.html:3936`
   `computeFeasibility`), **số cuối theo server**.
3. **Sync sheet con (L3) — có GAP phải vá.** Override propagate server-side (`attach_origin_sheet_states`
   → `product.origin_sheet_material_overrides`; sheet con render `→ mã thay` `co_case.html:1610`). **GAP:**
   `applyBulkSubstitute` hiện chỉ update ô summary + revision (`:5811`), **KHÔNG swap `[data-co-case-shell]`**
   ⇒ tab sheet con giữ DOM cũ tới khi reload. **Vá: sau bulk-substitute, re-render case shell** (reuse
   `replaceCaseShellFromResponse:2179`) — bulk endpoint trả HTML (hoặc client re-fetch shell) như đường
   single-save đã làm.
4. **Client/server không bất nhất (L4) — theo đúng pattern có sẵn.** `origin_case_revision`
   (`co_case_context.py:53`, sha256 trên state user-editable, loại derived-snapshot để không 409 giả);
   mọi mutation gửi `expected_revision` → server 409 nếu lệch, trả `revision` mới → client ghi lại
   `workbook.dataset.originRevision`; **client state = chỉ override-delta**, reconcile bằng **re-render từ
   response** (`replaceCaseShellFromResponse`), KHÔNG giữ speculative state. Batch phải: gửi expected_revision,
   200 → **swap shell**, luôn update originRevision. Aggregate đủ/thiếu **luôn từ `whole_case_stock_summary`**
   (override-aware, tuần tự), KHÔNG từ client `allocateCandidate`.

**⇒ Batch = server-authoritative:** mỗi thao tác (thay/tính lại/chốt) = 1 mutation gửi expected_revision →
server tính lại tuần tự → trả shell + revision + summary → client swap shell (sheet con + aggregate đồng bộ).
Không có bảng tính "sống" riêng ở client. Đây là điểm **phải làm trong Slice 2 UI** (vá gap L3).

## Risks
- **R1 — VERIFIED 2026-07-06 (discovery agent) → gate-relax theo material_code UNSOUND.**
  - **D2 (critical):** lot đăng ký dưới **nhiều key** (`co_stock_key_candidates` = material_code +
    allocation_code + customs_item_code, `co_case_context.py:1664/1820`); lookup theo material_code của
    NVL (`stock_candidates_for_material:1876`). ⇒ 2 sheet **material_code rời rạc vẫn chung 1 lot** qua
    alias. Overlap theo material_code **under-block → over-claim**. Muốn đúng phải so **tập lot** đã
    resolve, không so mã.
  - **D3:** trước khi tính, lot của sheet **không biết được** (draft = `materials:[]` `:1044`;
    bom_loaded có mã nhưng **không** allocation_lines `:2033`). Gate **không nạp pool** ⇒ không tính
    overlap chính xác nếu không chạy trial-allocation.
  - **D1/D4:** per-sheet calc trừ **mọi** sheet index thấp hơn in-memory (`apply_existing_origin_product_consumption`
    `:1047`, KHÔNG lọc lock) **cộng** overlay ledger locked (`_calculate_stock_rows_from_snapshot:3373`)
    ⇒ invariant "unlocked prior không đóng góp" do **chính index-gate** giữ, không phải calc. (Phát hiện
    thêm: same-case locked lot bị **trừ 2 lần** — ledger + in-memory; `used_qty_by_lot` thiếu case filter
    `co_stock_ledger.py:491` — **conservative**, không over-claim; backlog nhỏ.)
  - **D5:** logic gate **nhân bản** ≥4 chỗ: `origin_sheet_action_error` (callers `co_case.py:1803/2081/2105/3144`),
    UI flags (`co_case_context.py:1301-1347`, comprehension trùng `1304-1313`), `origin_can_reopen:1344`,
    `origin_sheet_export_blockers:1384` — sửa gate phải đồng bộ hết.
  - **Kết luận:** whole-case calc (`prepare_case_origin_products`) **đã** phân bổ đúng per-material,
    index-order, deterministic — client "chỉ NVL chung tranh tồn" **đã đúng ở tầng calc**. Gate-relax chỉ
    thêm khả năng lock **lệch thứ tự** giữa sheet rời rạc = workflow thủ công hiếm, đổi lại rủi ro over-claim.
    **Giá trị tự động hoá của khách nằm ở BATCH (tính cả lô 1 lần + bulk-lock, backend đã có), KHÔNG ở gate-relax.**
- **R2 — Batch nhân lỗi DC3a/DC3c.** ⇒ Slice 0 bắt buộc trước. Không mở batch khi guard chưa xong.
- **R3 — Invariant "view không calc".** M3 dễ bị cám dỗ tính lại → phải chiếu thuần. Guard = so
  rollup vs từng sheet đã tính (parity như export==web).
- **R4 — Revision-token 409 khi batch đổi nhiều sheet** (`co_case_context.py:53-80`) — như muc6, refresh
  `origin_case_revision` đúng.
- **R5 — Preview↔commit drift** (cross-case ledger) — preview chỉ tư vấn; lock cuối re-check overclaim.

## Decisions (user CHỐT 2026-07-06)
1. **DC3a — propose-bom giữ PER-SP; batch propose để SAU.** Khi propose, chỉ lấy **đồng nhất với bảng
   kê**: dòng **đã xoá** phải bỏ + strip **rác kỹ thuật** như bảng kê strip (proposal == declared).
   ⇒ `build_bom_proposal_rows` áp cùng bộ lọc export/render (`is_bom_technical_noise`, drop `deleted`).
   **Không** xây batch propose-bom lúc này.
2. **DC3c — CHẶN CỨNG lock + xuất** khi còn `declarable_unmatched`. `origin_sheet_action_error`(lock)
   + lock route + export cùng raise. Hệ quả tốt: sheet locked ⇒ không còn unmatched ⇒ propose-bom
   (chỉ chạy trên sheet locked) tự sạch unmatched.
3. **Auto-flow: tự TÍNH, DỪNG chờ review — KHÔNG auto-lock.** User review sheet tổng hợp + LVC rồi mới
   "Chốt tất cả" thủ công. (Định hình M5 + gate: auto-calc-all, manual bulk-lock.)
4. **Slice 0 (guards) LÀM TRƯỚC.**

Lưu ý phối hợp: DC3c hard-block nghĩa là auto-flow phải **phơi bày unmatched rõ** ở sheet tổng hợp để
user dọn trước "Chốt tất cả" — nếu không bulk-lock sẽ skip-and-report các sheet đó (đúng thiết kế).

## Next step
**Slice 0** theo `/tdd` (guards M4): (a) DC3c hard-block lock+export trên `declarable_unmatched`;
(b) DC3a propose-bom == bảng kê (strip noise + drop deleted). Test-first. Sau đó Slice 1 (gate relax M1).

## Key file refs (verified 2026-07-06)
- Gate: `app/web/co_case_context.py:1396` (+ nút `:1304-1313`), overlap dùng key pool `:1652/1783`.
- Pool/calc: `co_case_context.py:1746/785/816/2318`.
- Ledger: `app/routers/co_case.py:177`, `app/co_stock_ledger.py:150/205-218`.
- Batch routes: `co_case.py:1686/1697/1783`; nút gated `app/templates/co_case.html:913-920`; JS `~5783-5877/5938/5964`.
- Guards: DC3a `co_case.py:2680/2695/2721/2627`; DC3c `co_case_context.py:1913-1923/2604`, `app/origin_material_filters.py:9`.
- Rollup sẵn có (muc6): `whole_case_stock_summary` / `case_missing_stock_summary` (`co_case_context.py`).
</content>
</invoke>
