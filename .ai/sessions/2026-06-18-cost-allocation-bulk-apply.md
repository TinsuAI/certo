# Session 2026-06-18 (part 3) — Mục 4a: bulk áp hệ số chi phí + deployed-stack e2e

Picked up after the TKN-PDF-split session to tackle client-feedback **Mục 4a** ("auto phân bổ chi phí
trực tiếp theo tỷ lệ cố định per-client vào bảng kê RVC"). 2 commits, both deployed + verified:
`fc2cf1e` (feature) and `f30eccc` (e2e tooling). Prod = `f30eccc`.

## What Was Done

**Discovery (`/discover`):** Found the cost-allocation engine **already existed** (shipped 2026-05-27,
`.ai/features/2026-05-27-cost-allocation-ratios/`): admin page, Excel import (Growatt 24 mã SP), Mode A
(per Mã SP) → Mode B fallback, `apply_to_fob` (hệ số × FOB → 6 chi tiết → II/III/VII; lợi nhuận V =
residual), per-product "Áp hệ số" button. The 2026-05-27 brief explicitly deferred "auto/bulk" to *Out*.
→ **Mục 4a = the deferred bulk/auto layer + UI clarity**, not a new build. Wrote brief
`.ai/features/2026-06-18-cost-allocation-bulk-apply/brief.md`.

**Visual demo first** (user was unsure of the existing UX): seeded a Growatt demo case + sample ratios
into a temp file-mode store, auth-off server on `:8014`, puppeteer screenshots
(`.ai/screenshots/2026-06-18-cost-allocation-demo/`, gitignored) showing Mode A / Mode B / "chưa có hệ
số" per-product, the admin page, and the new bulk flow. Confirmed the per-product modal already surfaces
mode + applied amount; the real gap was a **case-level one-click + coverage overview**.

**TDD (`/tdd`) — `fc2cf1e`:**
- Pure fn `cost_allocation_importer.bulk_apply_to_products(products, resolve_ratio, *, overwrite=False)`.
  Gate = `origin_sheet_effective_criteria_text or documented_result` contains RVC/LVC (mirrors template
  line 1052). Mode A→B × `product.fob`; fills empty SP only (overwrite to replace); returns
  `{applied:[{code,mode}], skipped_no_ratio, skipped_no_fob, skipped_filled, updates}`. 7 tests incl.
  **regression parity** with the per-product `apply_to_fob`.
- Route `POST /clients/{id}/co-case/{case_id}/origin/bulk-apply-cost` — reads ratios once (`list_ratios`
  + `get_mode_b_default`), persists via `update_case_record` (→ `_sanitize_cost_buildup`). 2 tests
  (apply+persist, skip-filled/overwrite).
- UI in `co_case.html`: review-toolbar button "Áp hệ số CP (tất cả SP)" (shown only when a product is
  RVC/LVC, via a `namespace` loop), `fillProductCostBuildup` updates inputs live, `renderBulkCostSummary`
  banner (Mode A/B counts, missing-ratio/FOB lists w/ link to `/clients/{id}/cost-allocation`, "Áp lại &
  ghi đè" button). CSS `.bulk-cost-summary` + `.btn-link`.
- Full file-mode suite **619 pass** (+9). e2e on `:8014` (`6-bulk-modeA-only.png`,
  `7-bulk-with-modeB-and-filled.png`).

**Review (`/rev`) + fixes (in `fc2cf1e`):** Important — XSS via `innerHTML` with product codes (codes can
come from client-uploaded BOM/Excel) → added `esc()` HTML-escape for the dynamic code/URL values. Minor —
route resolved ratios per-product (N store reads) → read once into a dict. (#3 FOB-parse note: my
`_parse_fob` strips commas like `co_case_store.decimal_value`, which is correct; the `/resolve` endpoint's
`.replace(",",".")` differs but both agree on plain numeric `product.fob`.)

**Deploy:** branch `feat/cost-allocation-bulk-apply` → ff-merge `main` → push → CI deploy → verified prod
`fc2cf1e`.

**Deployed-stack e2e (user asked to seed+test prod then delete) — `f30eccc`:**
- Recon (`ssh tinsu`): **prod is no longer empty** (co-db-1: 4 johnson-vn cases + 24 Growatt ratios) and
  there's a **nightly/demo stack** (nightly-co-*, demo-co.tinsu.ai, same image). User chose nightly.
- Both prod+nightly are `CO_AUTH_REQUIRED=1` → no headless HTTP e2e. Ran the route logic **in-container**
  against nightly Postgres (DB-mode) via `cat script | ssh tinsu 'docker exec -i … python -'`.
- Result: **E2E_PASS** — Mode A applied + persisted to Postgres (wages 3000.00 … = coef×100k, profit
  blank), no-ratio SP skipped; **CLEANUP_OK** + independent SQL confirms 0 leftover, real data intact.
- Saved reusable script `.ai/scripts/e2e_cost_alloc_bulk_incontainer.py` (committed `f30eccc`) + memory
  [[co-deployed-e2e-incontainer]]. ff-merge to main → deployed → verified prod `f30eccc`.

## Decisions Made
- **Trigger = explicit bulk button, not silent auto** (user-approved). Keeps the audit-friendly model.
  Fallback A→B→none unchanged; FOB = `product.fob` native. SP with no ratio / no FOB → **skip + report**,
  never fill 0. Default fills empty SP only; overwrite is opt-in via the banner button.
- **No preview-before-commit step** — the always-visible toolbar + post-apply summary is enough (user pick).
- **Test the deployed DB-mode path in-container** because local tests are file-mode and SSO blocks HTTP.
  Stub `client={"id":...}` (route persistence only needs the id) to skip `resolve_client`'s DH lookup.
- **Isolate on `johnson-vn`** (0 ratios) for the e2e, never seed a Mode-B default for a real client.

## What Didn't Work
- **`resolve_client()` in a bare in-container script → DH `/v1/hub/dncxs/...` 401** (no request auth
  context). Fixed by stubbing the client dict — `resolve_client` isn't part of the bulk feature.
- Local demo puppeteer first failed to find the apply button (`offsetParent === null`): the cost-buildup
  block + "Áp hệ số" live **inside the ⚙ "Cấu hình bảng kê" settings modal** (display:none until opened).
  Had to click the visible `[data-origin-settings-open]` first (matches the local-e2e memory).
- First demo seed showed the block only after forcing `origin_sheet_states[code].criteria_override =
  "RVC 35%"` — demo products' `documented_result` ("…+ CTSH") doesn't contain RVC/LVC, so the block
  (and bulk gate) is hidden without an RVC criterion.

## Open Items
- Mục 6 (BOM default per-client + batch lock/stock) — cheap, infra exists; not started.
- `compact` PDF UI toggle — blocked on user confirming Ecosys legibility.
- EX1 (configurable column-K ref) / XX1 (origin NVL → M-N) — backlog.
- Demo server `:8014` may still be running (file-mode, seeded). Default dev = `:8001`.
- Local merged branches (`feat/cost-allocation-bulk-apply`, `chore/cost-alloc-bulk-e2e-tooling`) can be deleted.
