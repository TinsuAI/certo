# Project Status

## Current State
- **`main` tip = `afea9db`** (+ this handoff commit). **5 code/doc commits ahead of the old
  `origin/main` `bf1efac`** this session — being pushed now → **auto-deploy prod+demo+nightly** (these
  commits carry NO `[skip ci]`, so prod moves OFF `d80863e` to this version on push). Verify after deploy:
  `barry-co.tinsu.ai/version`.
- **DATA STILL PURGED (dev + prod, all clients)** from the 2026-06-15 session — `co_cases`/`co_case_states`/
  `co_stock_claims`/`co_supporting_files` = 0. Intentional. **Stock preserved** (`co_stock_rows`). Empty case
  lists are NOT a bug. Backups: `barry-CO-bom-data/local/backups/full-purge-20260615-032608/`.
- **This session = client-feedback batch (PDF `Barry CO - Trang tính1.pdf`, 6 items) + criterion-config UI
  redesign.** All shipped changes verified (602 file-mode tests pass; end-to-end export + UI screenshots).

## Recent Changes (this session 2026-06-18, latest first)
- **`afea9db`** fix(bang-ke): blank bảng kê **cột M-N** ("C/O ưu đãi nhập khẩu / bản khai NCC") in both export
  paths (config `bang_ke_renderer` co_doc_no/co_doc_date + legacy `workbook_io` co_no/co_date) until XX1.
  Backlog XX1 note + new **EX1** (make column-K declaration ref configurable: số vs số/dòng).
- **`cb3504b`** feat(origin): **redesign criterion config** — datalist (B7 black dropdown) → **segmented
  primary-criterion picker** (WO/PE/CC/CTH/CTSH/RVC/LVC/PSR + Khác) + "hoặc Y" alts over a hidden criteria
  input; threshold + cost-buildup reveal only for RVC/LVC; inline read-only summary chip opens the ⚙ panel.
  `co_case.html` + `app.css`. Verified end-to-end in real app (screenshots, 0 JS errors).
- **`54bbd1f`** docs: DH prompt `.ai/api-requests/2026-06-18-declarations-pdf-efficiency-dh-prompt.md` (make
  merged tờ-khai PDF faster+smaller: render cache, `quality=compact`, `max_part_bytes` split — for mục 2 & 5).
- **`cf0c192`** fix(origin): full NVL name (drop 2-line clamp) + substitute modal **floats in-stock candidates
  first** (`hasEnoughStock` prefers usable_lot_count). `co_case.html` + `app.css` (mục 1a/1b).
- **`f4c145a`** fix(bang-ke): **`hq_sheet_codes_for_product` picks FIRST-listed criterion** (compound
  "CTH hoặc RVC…" → CTH, not RVC). +9 tests. **The keystone fix** — resolves mục 3 + most of mục 4 (wrong
  RVC sheet for a CTH/CPTPP dossier). `workbook_io.py`.

## Next Steps (priority order)
1. **Remaining client-feedback items (not yet built):**
   - **Mục 6** — BOM mặc định **per-client** + "Chốt tất cả" + "chạy tồn 1 lần". CHEAPER than first thought:
     per-product override infra exists (`bom_product_artifact_overrides`, case-scoped); only missing = client-config
     default store + seed-on-create. ~1-1.5 ngày cho phần default.
   - **Mục 4a** — auto phân bổ chi phí trực tiếp theo **tỷ lệ cố định per-client** vào bảng kê RVC (cost_allocation
     module exists but not wired into export). Chỉ cho client RVC.
   - **Mục 5 / 2** — PDF tờ-khai split (configurable limit, **default 2MB**) + render perf — **needs Data Hub**
     (prompt artifact ready, awaiting DH build/approval). CO holds the configurable limit, passes `max_part_bytes`.
   - **Mục 4b** — đã phân tích = symptom của mục 3 (RVC sheet sai cho CTH); fixed via keystone. No separate work.
2. **EX1** — configurable column-K declaration ref (số vs số/dòng). Form A:N has no visible line column
   ("dòng hàng" = hidden helper O, outside print_area); kept số-only per template for now.
3. **XX1** — input NVL CÓ xuất xứ → LVC/RVC. **Note added:** bảng kê **cột M-N** is the origin-doc column
   (currently blanked); column **L (Ngày) already auto-fills** from the lot's `registration_date`.
4. **Correctness backlog (unchanged):** B6 (currency native always VND), DC3, LK1, D1 — see BACKLOG.md.

## Notes for Next AI Session
- **Local UI/export e2e verify recipe → memory `co-local-ui-e2e-verify.md`** (seed demo case into TEMP store
  `CO_CASE_STORE_ROOT=/tmp/...` — NEVER the live `data/` symlink; `CO_AUTH_REQUIRED=0`; puppeteer via
  `NODE_PATH=$(pwd)/node_modules`). Shell gotchas: foreground `sleep` is BLOCKED (exit 144); `pkill -f "<port>"`
  self-kills the shell (cmdline matches) → use `fuser -k <port>/tcp`; detach servers with `setsid … & disown`.
- **CSS vars live on `body[data-theme="light"]`, NOT `:root`** (`app.css`). A standalone harness needs the body
  attr or every `var(--x)` is empty. **`[hidden]` attr is overridden** by equal-specificity author display rules
  (`.origin-config-row{display:flex}`) → toggle via inline `el.style.display` (`setShown` in co_case.html).
- **Bảng kê column truth (verified vs `form-mau-combined.xlsx`):** print_area = **A:N** (form chính thức).
  K=Số TK, L=Ngày (auto from lot registration_date), M-N=C/O ưu đãi (origin, blanked), O+="dòng hàng"/helper
  cols are HIDDEN & outside A:N. Active export path = config-driven `bang_ke_renderer` (cth/rvc/lvc/ctsh/psr.json).
- **Criterion → sheet:** `hq_sheet_codes_for_product` now first-listed-wins; the segmented UI writes the primary
  FIRST into the hidden `criteria_override` so save (unchanged endpoint) → server picks the right HQ template.
- **Test env** [[test-env-filemode-vs-datahub]]: full file-mode (NO `.env`) = **602 pass**. Don't source `.env`
  then run full suite. DB-backed tests need `.env`, run separately.
- **Deploy:** push `origin main` (TinsuAI/co) → auto-deploy ~1-2min; `[skip ci]` HEAD tip skips. **This push
  deploys** (no [skip ci]).
- **Dev server:** `npm run co:serve` (DB-mode, `:8001`) — was 503 on `/clients` (DB/data state); file-mode (no
  `.env`) gives demo client `growatt` + demo case `growatt-gin01425l031` (needs seeding to persist).
- Deliverable copies for the user: `/mnt/c/temp/toss/barry-co-export-tieuchi-KLO.xlsx` (sample export, K/L/O).
