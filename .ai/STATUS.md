# Project Status

## Current State
- **`main` = `origin/main` = `bf1efac`.** Prod **deployed at `d80863e`** (`barry-co.tinsu.ai/version`
  = `0.14.0` / `d80863e` / source `build`). The 3 docs commits after `d80863e` are `[skip ci]` so prod
  intentionally stays at `d80863e`. Tree clean.
- **DATA IS PURGED CLEAN (dev + prod, all clients).** `co_cases` / `co_case_states` / `co_stock_claims`
  / `co_supporting_files` = **0** everywhere. **This is intentional** (user-requested reset of stale test
  data) — next session WILL see empty case lists; that is NOT a bug. **Stock preserved** (`co_stock_rows`:
  dev 98462, prod 104232; `co_stock_refresh_state` intact) → fresh cases calculate correctly immediately.
  - Dev `cases.json` files **deleted outright**. Prod never had any (DB-only). FS uploads/dossier-exports cleared.
  - Backups: `data/local/backups/full-purge-20260615-032608/` (dev) + `/prod`.
  - **Demo/nightly NOT purged** (separate stacks, `nightly-co-db-1`) — still hold old cases if that matters.
- **Growatt data VERIFIED CO-ready** (stock 38287 lô all >0, config `description_regex` v2, BOM↔tồn match
  **99%**, e44 end-to-end locked LVC 49.92%). Johnson also has stock (60173 lô). Both ready for pilot.
- **Dev server:** may need restart (`npm run co:serve`, --reload → `:8001`). Serves `bf1efac` content.

## Recent Changes (this session 2026-06-15, latest first)
- **`bf1efac`** docs(training): remove practice-exercises section (mục 15) from C/O guide `[skip ci]`.
- **`3443abf`** docs(training): add C/O user guide `docs/training/huong-dan-su-dung-co-nhan-vien-dai-ly.md`
  (companion "Phần 2" to the DH guide; matching style) `[skip ci]`.
- **`e3bafcb`** docs(status) `[skip ci]`.
- **`d80863e`** fix(co-case): `load_state` no longer reads/re-seeds `cases.json` when a DB is configured
  (killed the "zombie cases" re-seed). json only used in file-mode (test). **DEPLOYED.** File-mode suite 594 pass.
- **Off-git ops:** full data purge dev+prod (above); 2 user-guide PDFs + announcement email written to
  `C:\temp\toss` (`/mnt/c/temp/toss`).

## Next Steps (priority order)
1. **Correctness backlog (the real risks — see BACKLOG.md):**
   - **B6** — "nguyên tệ" always renders VND; if a client has USD/CNY/EUR invoices the bảng kê values are
     wrong. Highest-risk unknown, cheap to verify. `/discover` the FX/display path.
   - **DC3** — stale sheets keep junk + inflate LVC; consider hard-blocking issuance when `declarable_unmatched`.
   - **LK1** — "Chốt" allowed while sheet dirty / with unmatched rows; confirm endpoint truly rejects.
   - **D1** — delta-vs-full refresh has no parity test; silent snapshot-wipe fingerprint seen earlier.
2. **XX1** — input NVL có xuất xứ (phụ lục X) → LVC/RVC; touches DH origin-per-lot field. `/discover`.
3. **Parked:** CS3 full-harmonize (nới `is_workbook_sourced` for DH new-lot opening); P1 residual (index N+1);
   T1 (test-DB isolation); M1 (propose-BOM status sync); DC1/DC2.
4. **Optional:** purge demo/nightly too (if the old cases there bother anyone); growatt prod re-derive happens
   naturally at next real ingest (deferred — [[prod-test-data-recalc-deferred]]).
5. **Deliverable follow-up:** email salutation ("anh Trọng Tín") + blank signature need user's edit before sending;
   optionally add real prod URL to the published guides (kept host-free in committed markdown).

## Notes for Next AI Session
- **LANDMINE (verified this session):** a stale origin sheet (calculated under old config / before tồn refresh)
  can show **LVC 100% "Đạt" that is FAKE** — 0 NVL matched → 0 VNM → (FOB−VNM)/FOB = 100%. Re-calc reveals the
  real (often failing) LVC (proof: growatt 94feac/BIENTAN.17 0%→99.6% match, LVC 100%→19.67% partial_fail). Never
  trust any pre-2026-06-14 calc; re-calc first. Now moot on existing data (purged) but the rule stands.
- **Re-calc a sheet via curl:** POST `…/origin/sheet/{code}/calculate` with `Content-Type: application/json`
  body `{}` bypasses the revision-token 409. Sequence rule (LK1): must **Chốt** predecessor sheets before
  calculating the next (409 "Cần chốt các bước trước").
- **Test env** [[test-env-filemode-vs-datahub]]: full suite file-mode (NO `.env`) = **594 pass**. DON'T source
  `.env` then run full suite → ~52 false fails. DB-backed co_stock/origin tests NEED `.env`, run separately.
- **Bảng kê has 2 export render paths** [[bangke-export-two-render-paths]]: config-driven `render_into_sheet`
  (ACTIVE) vs `write_hq_sheet_materials` (fallback). Fix both + verify on the real exported file.
- **Mã HQ vs nội bộ:** bảng kê = `customs_item_code` (HQ); `allocation_code` (dotted) only for lookup/matching.
- **Deploy:** push `origin main` (TinsuAI/co) → auto-deploy prod+demo+nightly ~1-2min; `[skip ci]` HEAD tip skips.
- **Prod DB access:** `ssh tinsu` → `docker exec co-db-1 psql -U co -d barry_co` (schema `co`). co-app-1 = prod app.
- **User guides:** DH guide source `data-hub/docs/training/huong-dan-su-dung-nhan-vien-dai-ly.md` (9-pg PDF);
  CO guide `docs/training/huong-dan-su-dung-co-nhan-vien-dai-ly.md`. PDF gen = weasyprint + teal CSS (`/tmp/gen_co_guide_pdf.py`).
