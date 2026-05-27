# Project Status

## Current State
- Active branch: `main` (8 modified files + new engine, configs, scripts, samples — all uncommitted).
- CO dev server is running at `http://127.0.0.1:8001`; latest health check returned `200`.
- Local Data Hub is running at `http://127.0.0.1:8754`; latest health check returned `200`.
- Local Data Hub admin login: `admin@data-hub.local` / `local_test_password` (password was re-seeded this session).
- CO dev is using Postgres for workflow/case state and stock ledger:
  - local ignored `.env`: `BARRY_DATABASE_URL=postgresql:///barry_co?host=/var/run/postgresql`, `BARRY_DATABASE_SCHEMA=co`
  - use `uv run --env-file .env ...` for DB-backed live-state checks
- Full Python suite passes: `uv run pytest` → `231 passed, 4 skipped`.
- `data/local/runtime/data-hub-link.json` has `CO_AUTH_REQUIRED=1` (restored after e2e test).
- `npm test` still has pre-existing legal lookup failures around missing `raw-binary` source links; outside CO bảng kê flow.

## Recent Changes
- **HQ bảng kê — two parallel engines now coexist**:
  - **Approach B (default)**: template-based renderer driven by JSON config — `app/bang_ke_renderer.py` + `config/bang-ke-forms/{lvc,cth,ctsh,rvc,psr}.json`. Uses `data/local/hq-templates/form-mau-combined.xlsx` (built from agency-provided form-mau files) as visual master. Exposed via `create_hq_bang_ke_workbook()`.
  - **Approach A (alternative)**: XML-driven from-scratch generator — `config/bang-ke-config.xml` + `app/bang_ke_xml_generator.py`. Generates xlsx with consistent style (Times New Roman 11pt, A4 landscape, full grid borders) without consulting the template xlsx. Exposed via `create_hq_bang_ke_workbook_xml()`.
- Form-mau files extracted to `data/local/hq-templates/form-mau/`; combined builder at `scripts/build_form_mau_combined.py`.
- Cost-buildup (LVC/RVC labor/overhead/profit/other) is now persisted on `product.cost_buildup` and rendered as a 4-input section in each origin product panel (`<details class="cost-buildup-block">`). JS hint shows realtime sum vs FOB. Sanitised non-negative on persist.
- Client ID mapping CO ↔ Data Hub: `growatt` resolves to `growatt-vn` etc. via fallback in `app/data_hub_client.py:_get` and `app/main.py:resolve_client`. Hardcoded `-vn` suffix; extend `_CLIENT_ID_FALLBACK_SUFFIXES` for new locales.
- E2E test via Playwright drives the OAuth login flow → CO case origin tab → fills cost-buildup → screenshots. Script: `scripts/e2e_cost_buildup.py`. Outputs: `.ai/screenshots/cost-buildup-ui/e2e-*.png`.
- Sample bảng kê outputs (both engines) at `.ai/samples/bang-ke/` (Approach B) and `.ai/samples/bang-ke-xml/` (Approach A); PDFs included for visual review.

## Next Steps
1. Decide which engine becomes default in `create_dossier_zip`. Approach A is more consistent but doesn't match the agency form-mau exactly; Approach B mirrors the form-mau but inherits its visual inconsistencies.
2. Run a real LVC/RVC case with FOB > sum-of-costs through the UI so the green OK hint on the cost-buildup section can be screenshotted end-to-end. Current CO-ZIP case has FOB=100, too small.
3. Verify agency is OK with the simplified PSR conclusion `"Kết luận: Hàng hóa đáp ứng tiêu chí PSR"` vs the longer TT 11/2020 reference text the original form-mau ships.
4. Consider committing the new files (engines, configs, samples). All 231 tests pass; `git diff --check` clean. Untracked tree summary:
   - `app/bang_ke_renderer.py`, `app/bang_ke_xml_generator.py`
   - `config/bang-ke-config.xml`, `config/bang-ke-forms/*.json`
   - `scripts/build_form_mau_combined.py`, `scripts/export_form_mau_samples.py`, `scripts/export_xml_samples.py`, `scripts/render_cost_buildup_preview.py`, `scripts/e2e_cost_buildup.py`
   - `.ai/samples/`, `.ai/screenshots/cost-buildup-ui/` are local artifacts, keep gitignored.
5. If non-VN tenants ever join, centralise `_CLIENT_ID_FALLBACK_SUFFIXES` (currently duplicated in `app/main.py` and `app/data_hub_client.py`).
6. Old open items from prior sessions still apply (TKX/TKN browser test, declaration endpoint verification, Node legal test cleanup) — see `.ai/sessions/2026-05-20-tkx-tkn-lazy-origin.md`.

## Blockers
- None blocking the bảng kê engine work. Prior infrastructure dependencies (Data Hub declaration routes, Form&PSR engine) carry over unchanged.

## Notes for Next AI Session
- User writes Vietnamese casually; respond in fully accented Vietnamese.
- User prefers concise, direct status and expects concrete verification evidence.
- User wants screenshot/PDF verification when UI or output changes — not just "tests pass".
- User is comfortable with both JSON and XML config formats. They picked XML for the from-scratch generator because it maps cleanly to nested form structure.
- User accepted that Approach A's output doesn't exactly match the agency form-mau pixel-for-pixel — "consistent and logical is enough, the templates are messy anyway".
- Current running CO server is a foreground `npm run co:serve` process (PID owned by this session); logs at `/tmp/barry-co-8001.log`.
- Local Data Hub server (started by user previously) logs at `/tmp/data-hub-8754.log`.
- For e2e tests against the live CO server, use `scripts/e2e_cost_buildup.py` — it handles the full OAuth dance. Credentials: `admin@data-hub.local` / `local_test_password`.
- `data/local/runtime/data-hub-link.json` is gitignored but must stay `CO_AUTH_REQUIRED=1`. The file was briefly flipped during testing and restored.
- `auth_required` cannot be toggled via the .env file alone — the runtime JSON overlay takes precedence (see `app/data_hub_settings.py:merged_data_hub_link_env`).
- Approach A xlsx generation is deterministic and fast (~7 KB per sheet); Approach B inherits template size (~110-130 KB per sheet).
- LibreOffice is now installed (`soffice --headless`) for converting xlsx → PDF previews when validating output visually. `pdfinfo`/`pdftoppm` also available.
- Playwright Python is now installed in the project venv (`uv pip install playwright`). Chromium browsers are at `/home/vp/.cache/ms-playwright/chromium-*`.
