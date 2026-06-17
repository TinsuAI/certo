# Session 2026-06-15 — Growatt readiness verify, full data purge (dev+prod), load_state fix, user guides + email

## What Was Done

### 1. Backlog triage (no code)
Reviewed BACKLOG.md + STATUS. Clarified for the user that the "parked/low" items (CS3 harmonize, growatt
prod re-calc, DC1/DC2, P1 residual, T1) are **not blocking** system use; the real risks are the correctness
items **B6 (currency), DC3 (junk/LVC on stale sheets), LK1 (lock-while-dirty), D1 (delta parity)**. Verified
via code that CS3-harmonize / P1-residual / T1 are genuinely still open (not done last session).

### 2. Verified Growatt data is CO-ready
- DB: growatt-vn stock = **38287 lô, all remaining > 0**; 632 HQ codes, 3217 allocation codes; refreshed
  today under config v2 (`description_regex`). 26 cases existed, only 1 (e44) fully locked.
- Drove the running app (`:8001`, auth off, DH up on `:8754`) via `…/origin/calculation-payload` (GET, JSON):
  e44 (`SD00.0010600`) = 122/122 covered, LVC 49.92% pass, locked, mã HQ.
- **Re-calc proof of the stale-sheet landmine:** probed all 26 cases — 3 calculated under OLD config showed
  0–12% match + inflated LVC (94feac & 9dceec at **0% / LVC 100% fake**, 9dceec had a sheet LOCKED at 0%).
  Re-calculated 94feac/BIENTAN.17 (curl POST JSON `{}`): **0% → 99.6% covered, LVC 100% → 19.67% partial_fail**.
  The 1 unmatched code (`047.0007100`) = one of ~5 codes genuinely absent from stock (<1% residual).
- DB-side proof: 94feac BOM codes ∩ live stock allocation_codes = **584/589 (99%)**.

### 3. Full data purge — dev + prod, all clients (user-requested reset)
Confirmed scope via AskUserQuestion (all clients; dev-first-then-prod). Backed up everything first.
- **Dev:** `co_stock_events` (claim_lock/release 3258) → `co_stock_claims` (949) → `co_supporting_files` (4)
  → `co_case_states` (68) → `co_cases` (170), all → 0 in one transaction (FK order: claims before cases).
  Emptied then **deleted** the 4 `cases.json` files; cleared uploads FS.
- **Prod** (`ssh tinsu` → `docker exec co-db-1 psql -U co -d barry_co`): same deletes (7 cases / 1215 claims /
  16 support / 2460 events → 0); cleared FS uploads/dossier-exports. Prod had **no cases.json** (DB-only).
- **Stock preserved** everywhere (dev 98462, prod 104232 rows; refresh_state intact). App healthy post-purge.
- Backups: `data/local/backups/full-purge-20260615-032608/` (dev `db_cases_claims.sql` + `claim_events.csv`
  + `cases-json/` + uploads) and `/prod` (pg_dump + csv + `co-cases-files.tar.gz`).

### 4. Code fix `d80863e` (committed + DEPLOYED)
`app/co_case_store.py::load_state` — when a DB store is configured it now reads the DB **only** (empty row →
empty list); removed the `cases.json` read + the re-seed-back-into-DB shim that resurrected deleted cases.
`cases.json` is now used **only in file-mode** (no `BARRY_DATABASE_URL`, the test suite). `save_state` was
already gated. Verified: file-mode suite **594 pass**; live DB-mode case list stays empty (no re-seed).
Pushed `origin main` → CI `27510005484` success → prod `/version` = `d80863e`.

### 5. User guides + announcement email
- Wrote `docs/training/huong-dan-su-dung-co-nhan-vien-dai-ly.md` — a **companion "Phần 2"** to the existing
  Data Hub guide (`data-hub/docs/training/huong-dan-su-dung-nhan-vien-dai-ly.md`), same style/tone, 14 sections
  (after removing the practice section per user). Only documents **shipped** features; host-free per repo hygiene.
  Committed `3443abf`, then `bf1efac` removed the practice-exercises section.
- Generated a matching PDF (weasyprint + teal CSS, `/tmp/gen_co_guide_pdf.py`) → `C:\temp\toss\huong-dan-su-dung-co-nhan-vien-dai-ly.pdf` (7 pp).
- Wrote announcement email to "anh Trọng Tín" → `C:\temp\toss\EMAIL_THONG_BAO_TRONG_TIN.txt`: week's concrete
  improvements (DH + CO), Growatt/Johnson readiness + converter parallel-run, onboard-next ask, 2 attached guides.
  Rewritten on request to remove hard line-wraps and make section 1 specific (not generic feature blurb).

## Decisions Made
- **Purge via direct SQL + FS, not the per-case app endpoint** — cleaner for a bulk wipe of 170+7 cases; backed
  up first; transaction with FK-safe delete order. Kept `co_stock_rows` (the correct/expensive data).
- **load_state: gate, don't rip out** the file store — it IS the file-mode (no-DB) store for 594 tests. Removing
  it entirely would break the suite. Scoped the fix to "DB present → never touch json", which fully kills the
  re-seed in any real deployment while keeping file-mode intact. (User had said "remove everywhere it's used"; I
  explained the test dependency and scoped accordingly.)
- **CO guide = companion, not merged** doc; markdown in CO repo + PDF in toss (user choice). Documented only
  shipped features (deliberately excluded backlog XX1 origin-input and the B6 currency quirk).
- **Email:** matched the existing `EMAIL_*.txt` house style ("Tiêu đề / Kính gửi / bên em / Em cảm ơn"); single-
  line paragraphs (no hard wrap) so it pastes cleanly into a mail client.

## What Didn't Work
- **Re-calculating the rest of 94feac via curl** — sheets 2–7 returned 409 "Cần chốt các bước trước" (the LK1
  sequence rule requires locking each predecessor before calculating the next). Proof on sheet 1 was enough; did
  not push the lock-chain (would consume claims + the sheet fails LVC anyway).
- **Overwriting the toss PDF while it was open** — `PermissionError`/`cp: Permission denied` (Windows file lock
  from the open viewer). Generated to `/tmp` first; the lock cleared on retry and the copy succeeded.
- Minor: a `$BK` shell-var expansion glitch dropped one backup file to repo root; moved it back into the backup dir.

## Open Items
- **Correctness backlog unworked** (next priority): B6, DC3, LK1, D1 — see STATUS Next Steps + BACKLOG.md.
- **Demo/nightly not purged** — still have old cases; purge if desired (same recipe, `nightly-co-db-1`).
- **Email needs user edits** before sending: confirm "anh Trọng Tín" salutation, fill the signature; optionally
  add the real prod URL to the published guide PDFs (committed markdown intentionally host-free).
- **Growatt prod re-derive** still deferred (prod = test data; happens at next real ingest).
- `/tmp/gen_co_guide_pdf.py` is the PDF generator (not committed) — re-run after editing the guide markdown.
