# Project Status

## Current State
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
000. **`/implement` #15, #16, #17** (GitHub, `ready-for-agent`, độc lập — fresh context mỗi vé,
   `gh issue view <n>`): #15 NCC tên dài → horizontal scroll (wrap/truncate cột tên);
   #16 search box màn NCC (match theo supplier_key normalize, không dấu); #17 client-tabs
   bị ẩn ở case view (`active == "co-case"` trong `_client_nav.html`) → cho hiện cùng step nav.
000b. **User actions:** flag 2 NCC prod (xem Current State) + quyết #14 (đề xuất: option 2
   CO-side allocation override trên client overlay, precedent `bang_ke_overrides`; hỏi agency
   trước liệu growatt-vn có upload BOM mã HQ không — option 3 thì khỏi cần override).
   2 standing action items cũ (audit locked SHORTAGE sheets; `missing_price` hole) **ĐÃ XONG 2026-07-11**.
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
