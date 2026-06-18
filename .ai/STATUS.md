# Project Status

## Current State
- **`main` = `origin/main` = prod = `30c50f3`** (`barry-co.tinsu.ai/version` git_sha `30c50f3`,
  v0.14.0). Tree clean. Everything from this session (2026-06-18) is **deployed + verified live**.
- **DATA STILL PURGED (dev + prod, all clients)** from 2026-06-15 — `co_cases`/`co_case_states`/
  `co_stock_claims`/`co_supporting_files` = 0. Intentional; empty case lists are NOT a bug. **Stock
  preserved** (`co_stock_rows`). Backups: `barry-CO-bom-data/local/backups/full-purge-20260615-032608/`.
- **Data Hub shipped the merged-PDF efficiency endpoint** (render cache, `quality=print|compact`,
  `max_part_bytes` split) — params are LIVE on the configured DH. CO now consumes them (see below).

## Recent Changes (this session 2026-06-18 — 7 feature commits, all live)
- **`30c50f3`** feat(export): **split merged TKN PDF for Ecosys** (mục 5). Adapter
  `download_declarations_pdf` gains `quality` (default `print`/lossless) + `max_part_bytes`; handles
  `application/zip` (split → `parts[]`) vs `application/pdf`. Export embeds each part as
  `03-to-khai/…-to-khai-nhap-part-NNN.pdf`. New **per-client config UI "Xuất hồ sơ"** (cap in MB,
  default 2) stored as a **CO-side client overlay `client.export_overrides.tkn_pdf_max_part_mb`**
  (NOT client_config — see source-mode note). 8 tests; verified vs live DH + full dossier zip.
- **`afea9db`** fix(bang-ke): blank bảng kê **cột M-N** (origin-doc column) until XX1. Backlog XX1 + EX1.
- **`cb3504b`** feat(origin): **redesign criterion config** — segmented primary picker + "hoặc Y" alts
  over a hidden criteria input (B7). Threshold + cost-buildup reveal only for RVC/LVC.
- **`cf0c192`** fix(origin): full NVL name + substitute modal floats in-stock candidates first (mục 1).
- **`f4c145a`** fix(bang-ke): **`hq_sheet_codes_for_product` first-listed criterion** — the keystone
  (compound "CTH hoặc RVC…" → CTH not RVC). +9 tests. Resolves mục 3 + most of mục 4.
- **`54bbd1f`** docs: DH PDF-efficiency prompt (mục 2 & 5) — DH has since shipped it.

## Next Steps (priority order)
1. **Remaining client-feedback items:**
   - **Mục 6** — BOM mặc định **per-client** + "Chốt tất cả" + "chạy tồn 1 lần". Per-product override
     infra exists (`bom_product_artifact_overrides`); missing = client default store + seed-on-create.
   - **Mục 4a** — auto phân bổ chi phí trực tiếp theo tỷ lệ cố định per-client vào bảng kê RVC.
   - **`compact` PDF profile** — adapter supports `quality=compact` (lossy, ~smaller) but there's NO UI
     toggle yet. Opt-in pending **user confirming Ecosys legibility** (gs /ebook 150 DPI). Lossless
     `print` + 2 MB split already solves the Ecosys size problem without it.
2. **EX1** — make column-K declaration ref configurable (số vs số/dòng). Form A:N has no visible line
   column ("dòng hàng" = hidden helper O, outside print_area); kept số-only per template for now.
3. **XX1** — input NVL CÓ xuất xứ → LVC/RVC. **Cột M-N reserved/blanked**; column **L (Ngày) already
   auto-fills** from the lot's `registration_date`.
4. **(Tech-debt, pre-existing)** Config-page POST returns **409 in DH source-mode** for the source
   fields (lot_policy/allocation) — affects `min_days` + the new PDF cap identically; the CO-side
   overrides persist BEFORE the guard, but the response is a 409. Clean save UX in source-mode is a
   separate fix if the user cares.
5. **Correctness backlog (unchanged):** B6 (currency native→VND), DC3, LK1, D1 — see BACKLOG.md.

## Notes for Next AI Session
- **DH source-mode is ON** in dev/prod (`.env DATA_HUB_ENABLED=1` + a data_hub config override). This
  means `require_local_source_writes()` 409s `client_config` saves. **CO-side per-client settings
  (min_days, the new PDF cap) MUST live on the client overlay** (`app_state_store.upsert_client`,
  handled before the guard in `pages.save_client_config_route`), NOT in `client_config`. Reads at
  export time use `client.get("export_overrides")`. `get_app_state_store()` is **Postgres-only** →
  returns None (no persist) in file-mode; persists in DB-mode.
- **Adapter contract (verified vs live DH 2026-06-18):** `download_declarations_pdf(...,
  quality="print"|"compact", max_part_bytes=int|None)` → `{content (None when zip), parts:[{name,
  content}], content_type, parts_count, oversize_nos, pdf_bytes, quality, render_ms, requested,
  included, missing, missing_nos}`. Split returns `application/zip`; CO unzips into parts. DH render
  cache already exists; this only parallelizes cold misses (perf win modest on warm exports).
- **NEVER write the literal CI-skip token in a commit message** (even negated) — it skips the whole
  pipeline, prod won't deploy. Recover with an `--allow-empty` re-trigger commit. Memory
  [[ci-skip-token-in-commit-msg]].
- **Local UI/export e2e recipe** → memory [[co-local-ui-e2e-verify]] (seed demo case into TEMP store
  `CO_CASE_STORE_ROOT`/`CLIENT_CONFIG_ROOT=/tmp/…`, never the live `data/` symlink; `CO_AUTH_REQUIRED=0`;
  puppeteer via `NODE_PATH=$(pwd)/node_modules`). Shell: foreground `sleep` BLOCKED (exit 144);
  `pkill -f "<port>"` self-kills the shell → use `fuser -k <port>/tcp`; servers via `setsid … & disown`.
- **Bảng kê column truth** (`form-mau-combined.xlsx`): print_area = **A:N**. K=Số TK, L=Ngày
  (auto from lot registration_date), M-N=C/O ưu đãi (origin, blanked), O+ helper cols HIDDEN.
- **Test env** [[test-env-filemode-vs-datahub]]: full file-mode (NO `.env`) = **610 pass**. Don't source
  `.env` then run full suite. DB-backed tests need `.env`, run separately.
- **Deploy:** push `origin main` (TinsuAI/co) → auto-deploy ~1-2min; verify `…/version` git_sha.
  `gh run list` to watch CI; CI-skip token in HEAD msg skips deploy.
- **Open question parked for user:** add 2 cross-project lessons (shell sleep/pkill gotchas + CI-skip
  token) to `~/dotfiles/ai/knowledge/` — offered, not yet done.
