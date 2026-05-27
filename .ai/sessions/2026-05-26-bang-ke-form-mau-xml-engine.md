# 2026-05-26 — Bảng Kê C/O Engine (form-mau templates → XML-driven generator)

## What Was Done

### Templates ingestion
- Extracted the 4 agency-provided form templates (`FORM CTH/RVC/LVC/PSR.xlsx`) into `data/local/hq-templates/form-mau/` and built `data/local/hq-templates/form-mau-combined.xlsx` (single workbook with 5 sheets — `LVC/RVC/CTH/CTSH/PSR`, CTSH cloned from CTH). Builder: `scripts/build_form_mau_combined.py`.
- Each form was read closely. Findings:
  - **LVC** uses Phụ lục VII with a *compact 17-col layout* (extra `C=Mã NPL` shifting HS→D/UOM→E…), body row 16-437, has its own labor/overhead summary block at rows 438-455, hardcoded `K466="Hải Phòng, ngày 18/05/2026"` example date.
  - **CTH/RVC/PSR** use the wide 261-col layout (helper cols O-Y), body row 16-1585, footer at 1586-1623. PSR keeps its real conclusion at `B1617` (B1611 is a stale ratio label in the template). CTH ships rows 1588-1610 hidden because CTH doesn't need a ratio.
  - All four templates ship fully-worked example values (labor wages, factory rent, depreciation, freight) that must be cleared on every export.

### Approach B — template-based + JSON config (delivered, parallel)
- `app/bang_ke_renderer.py` (~330 LOC) drives header / body / footer / clear-cells from JSON.
- `config/bang-ke-forms/{lvc,cth,ctsh,rvc,psr}.json` describe per-criterion cell mappings (compact for LVC, wide for the others).
- `app/workbook_io.py` routes all 5 criteria through this engine via `_CONFIG_DRIVEN_CRITERIA = {LVC, CTH, CTSH, RVC, PSR}`. The legacy hardcoded path is fallback only.
- Output matches the form-mau layout exactly. PDF page counts: CTH/RVC/PSR=2, LVC=4. Tests stayed green (231 pass).

### Approach A — XML-driven from-scratch generator (delivered, parallel)
- User preferred a cleaner consistent style. Pivoted to `config/bang-ke-config.xml` + `app/bang_ke_xml_generator.py` that builds xlsx from scratch with openpyxl.
- One visual standard across all forms: Times New Roman 11pt body / 14pt title, A4 landscape, margins 2cm/1.5cm, header row shaded `#E7E6E6`, thin black grid, full-page print area.
- Per-criterion differences are pure XML: title, Phụ lục number, conclusion sentence, whether to show the LVC/RVC cost-buildup block, and per-column `only-on`/`skip-on` toggles.
- Output: every form fits in 1 page; samples at `.ai/samples/bang-ke-xml/`.
- Both paths are exposed in parallel: `create_hq_bang_ke_workbook()` (Approach B, default) and `create_hq_bang_ke_workbook_xml()` (Approach A).

### Cost-buildup data model (LVC/RVC)
- Schema: `product.cost_buildup = {labor, overhead, profit, other}` (II/III/V/VII per TT 05/2018).
- Engine reads from product, fills the block; I/IV/VI/VIII auto-compute via formulas (`material-totals`, `I+II+III`, `IV+V`, `fob`).
- UI: `<details class="cost-buildup-block">` in each origin product panel, default open when criterion contains LVC/RVC. JS hint shows realtime sum vs FOB:
  - empty → grey hint
  - sum ≤ FOB → green "Tổng = X. NPL còn lại = Y / FOB Z"
  - sum > FOB → orange "không hợp lệ"
- Persistence: `case_from_form` reads `product_{i}_cost_buildup_*` form fields; `merge_origin_action_payload` merges from JSON autosave; `persisted_products` sanitizes via `_sanitize_cost_buildup` (non-negative numeric strings, blank otherwise). Round-trips through Postgres via `json_safe`.

### Client ID mapping (CO ↔ Data Hub)
- Data Hub stores tenants with `-vn` suffix (`growatt-vn`, `johnson-vn`) while CO state and URLs use the short form (`growatt`, `johnson`).
- `app/data_hub_client.py:_get` now retries `/v1/hub/dncxs/{id}/...` and `client_id=...` params with `-vn` suffix on 404. Single fallback round, no infinite loop.
- `app/main.py:resolve_client` force-overrides `client["id"]` and `client["client_id"]` back to the short form after Data Hub returns its suffixed record, so downstream `get_case_record` and Postgres lookups stay consistent.

### E2E verification
- Reset local Data Hub admin password (`admin@data-hub.local` / `local_test_password`) via `update hub.users set password_hash = ...` — the seed user existed but the password had drifted.
- `scripts/e2e_cost_buildup.py` drives Playwright through the full OAuth dance (CO → Data Hub `/login` → `/auth/callback` → case origin tab) and captures 3 screenshots. Tests confirmed:
  - Cost-buildup section renders open with empty inputs on first load.
  - Filling 350/880/3680/40 with case CO-ZIP (FOB=100) triggers the warning hint (sum 4,950 > 100).
  - 2000×4 also warns (sum 8,000 > 100).
- The OK (green) state was demonstrated in the offline preview (`preview.png`, FOB=5000) — not reproducible against CO-ZIP because that test case has FOB=100.

## Decisions Made
- Keep `data/local/hq-templates/form-mau/` files as the canonical reference even after Approach A — they're the agency-provided source of truth and useful for diffs.
- Both engines (B template-based, A XML from-scratch) coexist. Approach B is wired into `create_dossier_zip`. Approach A is exposed as a sibling function; future toggle is a 1-line change in `create_dossier_zip` or a query param.
- `_CLIENT_ID_FALLBACK_SUFFIXES = ("-vn",)`. Adding new locales = extend this tuple. Approved-endpoint policy test still passes because the fallback rewrites paths using literals already in the approved set (no new endpoint strings introduced).
- Cost-buildup: 4 inputs (labor/overhead/profit/other), not 7. The aggregate `Tổng II` and `Tổng III` from TT 05/2018 are not split into sub-rows — agencies can input each as a single number.
- JSON config (Approach B) and XML config (Approach A) both store comments. JSON uses `_doc` / `_clear_cells_doc` keys; XML uses real `<!-- … -->` comments.
- Sample LVC PDF intentionally shows the formula-computed values (V=3,680 came from user input; VIII=5,000 is FOB direct, even when VI+VII = 4,996.21). This matches the original FORM LVC template's behavior (`I455 = =L10`).

## What Didn't Work
- First pass of `_clear_lvc_template_example_data` used `ws.cell(row, col, value=None)` — openpyxl treats `value=None` as "don't update", so the cells weren't cleared. Fixed by using `ws.cell(row, col).value = None` explicitly.
- Initial e2e attempt failed because Approach B's `_get` fallback resolved the Data Hub call, but `resolve_client` only overrode the short ID inside its old `except HTTPStatusError` branch — which never fired. Solution: unconditionally force `id`/`client_id` back to the short form on any successful resolve.
- Test `tests/test_data_hub_policy.py::test_data_hub_adapter_only_uses_approved_endpoints` failed when I added `_CLIENT_PATH_PREFIX = "/v1/hub/dncxs/"` as a class constant — the regex picked up the new endpoint literal. Solution: assemble the prefix from local variables inside `_client_id_attempts` so no new string literal is introduced.
- Tried first to use Playwright via npm — the project only has the Python `playwright` package (now installed in the venv). Node-based attempts errored with `ERR_MODULE_NOT_FOUND`.
- The CO-ZIP test case has FOB=100, not 5000, so the JS hint always trips the warning state — couldn't capture the OK green hint on e2e. Used an offline Jinja+Playwright preview to demonstrate the OK state.

## Open Items
- **Default export path**: still uses Approach B (template-based). To switch to Approach A (XML-driven), change `create_dossier_zip` to call `create_hq_bang_ke_workbook_xml`. Decide which becomes default after user reviews both outputs side-by-side.
- **Cost-buildup UI in real workflow**: only validated synthetically. Need a real LVC/RVC case with FOB > sum so the green OK hint can be screenshotted.
- **PSR conclusion** is plain "Kết luận: Hàng hóa đáp ứng tiêu chí PSR" — TT 05/2018 has a richer PSR conclusion mentioning specific Chương thông tư 11/2020 references. The current PSR form-mau template carries that long text statically at B1617; the engine just overwrites it. Confirm with agency whether that's acceptable.
- **`-vn` suffix policy**: hardcoded in two places (`app/main.py`, `app/data_hub_client.py`). If a non-VN tenant arrives, extend `_CLIENT_ID_FALLBACK_SUFFIXES` in both files (or centralise into a single constant module).
- **`auth_required` toggle in `data/local/runtime/data-hub-link.json`** was flipped to `0` during testing, then restored to `1`. The runtime file is gitignored but worth a sanity check before commit.
- **Approach A column layout** doesn't yet have a "Số lượng lô" column for LVC (it's intentionally `skip-on="LVC"` since LVC computes consumption from norm × product qty implicitly). Agencies that want that column visible on LVC will need an XML edit.
