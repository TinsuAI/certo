# Project Status

## Current State
- Branch `main` is at `f83bfa1`, 4 commits ahead of the snapshot in the prior STATUS.md. All pushed to `tinsu/main`; CI green (1m08s); deployed to `https://barry-co.tinsu.ai` and verified live via puppeteer.
- Latest commits (newest first):
  - `f83bfa1` — Fix GET `/export-bang-ke` returning 404 (route-order fix; FastAPI catch-all `{step}` was eating it before the dedicated route).
  - `4cf31f2` — Simplify Origin override controls: datalist criteria, single LVC/RVC threshold input, Reset-to-recommendation button.
  - `dfda66f` — Stock ledger: drop silent `except Exception → return 0` swallow; add `StockOverclaimError` pre-check inside same transaction; reverse release order in `reopen_co_case_origin_sheet`.
  - `36891e0` — Dark theme: route 142 hardcoded colour literals in `app/static/css/app.css` through existing CSS vars; 5 modal `rgba(15, 23, 42, …)` backdrops kept (theme-neutral).
- Local CO dev server at `http://127.0.0.1:8001` (`npm run co:serve` with `--reload`), Data Hub at `:8754`. Both `/healthz` OK.
- CO Postgres: `BARRY_DATABASE_URL=postgresql:///barry_co?host=/var/run/postgresql`, schema `co`. Migration 012 applied.
- **Local Áp hệ số end-to-end** still working on case `co-case-b1e2602f0d8d` (CO-ZIP). Mode-A fixture intact.
- **Prod verified post-deploy** with `claude-check@local`. Override UX renders correctly (single threshold, Reset button, datalist of 18 criteria). GET + POST `/export-bang-ke` both return 200 + xlsx.
- Pre-existing test failures unchanged: ~7 in the `export | step | co_case_workflow` slice; ~30 total local-only environmental drift on `main`. CI runs all 264 tests green.

## Recent Changes (2026-05-28 evening session)
- **Stock ledger safety**: replaced silent-failure pattern with raise-on-DB-error + `StockOverclaimError` pre-check (queries `co_stock_rows` snapshot + cross-case `co_stock_claims`, excludes self). Lock route returns 409 with violating-lot detail; reopen route now release-first so DB failure leaves sheet locked instead of leaking the claim.
- **Origin override UX**: criteria is now a datalist (18 common patterns + custom text); LVC + RVC thresholds collapsed into one input that writes to both server slots; new "Reset về khuyến nghị" button posts empty values to revert to engine recommendation.
- **Bug fix**: GET `/export-bang-ke` was 404 because the catch-all `{step}` GET route at `main.py:5465` ate it before the dedicated route at line 5616. Reordered (delegating wrapper above the catch-all). Tried `Path(..., pattern=...)` first — discovered FastAPI returns 422 on mismatch rather than skipping the route.
- **Dark theme**: comprehensive audit + fix of 142 hardcoded light-palette literals concentrated in late-added features (workflow steps, callouts, document checklist, substitute/co-stock modals, BOM diff, cost-buildup). WCAG contrast scan (3.0 threshold) on 20 pages: 0 findings post-fix.
- **Audit work** (no code, just understanding): mapped the form/criteria/threshold flow end-to-end across engine layer (`co_forms.py`, `co_form_psr_index.py`), config layer (`co_form_config_store.py`), UI layer (`co_case.html`), and persistence (`origin_sheet_states` in case JSON). Verified Explore-agent claims against real code — ~5/15 findings were false positives (e.g., agent claimed re-lock spams audit log; in fact `co_stock_ledger.py:144-177` already dedupes).
- New helpers in `scripts/`: `dark_theme_audit.mjs`, `verify_export_route.mjs`, `verify_prod_deploy.mjs` committed (only `verify_export_route.mjs` is in a commit; `dark_theme_audit.mjs` was in `36891e0` commit). The 4 `full_workflow_audit*.mjs` files remain untracked.

## Local Test Fixture
- Case `co-case-b1e2602f0d8d` (case_code `CO-ZIP`) on growatt is still the **Mode-A Áp hệ số smoke fixture** — see prior STATUS for details. Unchanged this session.

## Next Steps
1. **Per-client default form / criteria / threshold overrides** in `client_config_store.py` — flagged HIGH in this session's form/criteria flexibility audit. Operators currently re-override per-sheet for every case; a per-client default would remove that friction.
2. **Seed missing CO forms** (D / E / AK / AANZ / AJ / RCEP / UKVFTA / VK / VC / VJ) into `default_co_form_config()` + minimal "Tra theo Phụ lục" PSR fallback per form. Built-in config currently has only B / CPTPP / EUR.1 / AI — major content gap for ASEAN+ markets.
3. **Concurrent edit race** on `co_case_states` (last-writer-wins, no `revision` field) — flagged HIGH; add optimistic-concurrency check in `update_case_record`.
4. **HS↔form coherence + criteria token validation** — flagged MED in audit, soft (warning, not block) implementation.
5. **Export gate too lenient**: `origin_sheet_export_blockers` only rejects `{draft, stale, calculating}` — accepts `calculated` (not yet `locked`), meaning user can export bảng kê HQ before stock claim is recorded in ledger. Confirm with business: is `calculated` enough, or should it require `locked`?
6. **Investigate the 30 pre-existing local test failures** (carry-over from prior STATUS).
7. **GitHub Actions Node 20 deprecation** before 2026-06-02 (carry-over).
8. **Short→long client_id URL fallback in `can_view_client`** (carry-over).
9. Old open items still apply: PSR conclusion confirmation, Approach A/B engine default, `-vn` suffix centralisation.

## Blockers
- None.

## Notes for Next AI Session
- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/` has 5 entries: demo URLs, SSH access, test account, deploy hygiene, test-local-by-default preference. Read MEMORY.md first.
- **Test on local by default.** Only touch prod when explicitly told ("trên prod" / "lên demo" / etc.).
- **Public demo URLs** (in memory, not in repo): `barry-co.tinsu.ai`, `ttdatahub.tinsu.ai`.
- **Prod test account**: `claude-check@local` / `claude-temp-2026`. URLs MUST use `-vn` long form on prod until `can_view_client` is fixed.
- **Don't commit hostnames** or server paths.
- **Stock ledger now propagates DB errors** — if you wrap a call to `co_stock_ledger.record_sheet_lock` / `record_sheet_release`, handle `Exception` explicitly. `StockOverclaimError` is the new domain exception for over-claim attempts.
- **Override semantics**: per-sheet `form_override` / `criteria_override` / `*_threshold_override` in `origin_sheet_states[product_code]` are persisted across market changes by design (user choice, not bug). The "Reset về khuyến nghị" button is the escape hatch.
- **FastAPI route ordering matters**: catch-all path params (e.g. `{step}`) eat ALL single-segment paths. Define specific routes BEFORE catch-alls. `Path(..., pattern=...)` does NOT make the router skip — it returns 422 on mismatch.
- **The Explore agent has ~30% false-positive rate** on code-flow audits. Always read the cited file:line before acting on a finding. Two agent reports in this session both required correction (e.g., "no cascading unlock" claim was wrong; agent missed the silent-exception swallow which turned out to be the most serious issue).
- **`libreoffice --headless --convert-to pdf` + Read tool's PDF page rendering** is a reliable end-to-end xlsx verification path (no Excel install needed).
- Authoritative case state lives in `co.co_case_states` (jsonb-per-client). Never UPDATE `co.co_cases` directly — use `update_case_record()` from `app/co_case_store.py`.
- User writes Vietnamese casually; respond in **fully accented Vietnamese** (or English). Never unaccented Vietnamese.
- User wants concise direct status, evidence-based "done" claims. No fluff.
- Pre-existing 30 test failures on `main` are local environmental drift; CI is green. Don't chase them as regressions.

