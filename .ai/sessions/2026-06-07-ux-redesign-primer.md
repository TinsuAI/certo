# Session 2026-06-07 — UX/UI redesign (GitHub Primer)

## Goal
User: "thiết kế lại hết đi" — the company list looked poor, the per-company landing was
confusing, data pages only linked to Data Hub, config was scattered. Make CO the primary
flow; reorganize data + config; give data pages real overview info.

## What was done
Branch `feat/ux-redesign-primer` (8 commits) → fast-forward merged to `main` → **deployed to
prod + demo** (`a33eaae`). Commits `3090f76`(design system) `b7e5b4d`(dashboard+cards+nav)
`88a905b`(data dashboards + bom consumer) `adfa5f1`(config) `791c5af`(tests) `367d08c`(API
request) `f433af6`(prior handoffs) `cec7934`(STATUS+summary) `a33eaae`(post-push CI test fix).

- **Design system (Primer "operations console").** Rejected 4 bolder palettes (indigo/blue/
  ink/teal) after user feedback; landed on neutral slate + single blue accent + semantic status
  colors, solid 1px borders, small radius, near-zero shadows, flat background, both themes,
  WCAG AA verified. Implemented by swapping token VALUES (names unchanged) so `co_case.html`
  (5049 lines) inherits the look untouched — verified via before/after screenshots of the
  origin workspace (no geometry break). Swept hardcoded color literals onto tokens.
- **Company list (`/clients`).** Portfolio summary header (companies / open C/O / attention) +
  rich cards (monogram, open-CO count, done/total, data-readiness dots, attention accent).
- **Company dashboard (`/clients/{id}`).** Replaced the redundant overview with a CO-centric
  dashboard: recent C/O cases (derived status) + data-readiness panel; empty state as primary.
  Cheap context only (reuses the `_co_stock_lean_client_context` pattern — no full pagination).
- **Nav/IA.** Grouped per-client nav with `Dữ liệu`/`Cấu hình` dropdowns (`<details>`, no JS;
  fixed `.tabs{overflow}` clipping). Topnav decluttered (dropped Tỷ giá HQ + Portfolio).
- **Per-data-page dashboards.** Metric-card band on Catalog/BCCT/BOM/Tồn CO. Numbers only from
  cheap sources: source_summary counts/versions; materializer SQL for Tồn CO value/qty/codes/
  lots. BCCT NOT scanned (65k). "Open on Data Hub" demoted to secondary.
- **Config grouping.** System Settings split (account vs shared config; FX moved here from
  topnav); company config clarified as per-company + cross-links allocation coefficients.
- **Data Hub `bom` consumer.** Filed `.ai/api-requests/2026-06-07-products-total-count.md`; DH
  shipped the lighter `bom` block on `/source-summary`; CO consumes it for the BOM dashboard —
  headline = export trio (`exported_with_bom / exported_total`, gap `exported_without_bom`),
  `product_count` kept only as a BTP-inclusive detail. Feature-detected with a qualitative
  fallback.

## Decisions
- Aesthetic: restraint over boldness — this is a daily data tool, not a marketing dashboard.
  Reference: GitHub Primer/Stripe/Linear. Memory `ui-design-direction-primer`.
- Never fabricate dashboard numbers: `/v1/hub/products` is hard-capped at 50 (no cursor/total),
  so BOM count is unobtainable from CO — fixed via DH `bom` block, not a CO workaround. Memory
  `dh-products-endpoint-50-cap`.

## What didn't work / corrected mid-session
- First palette attempts (indigo, then blue/ink/teal) all rejected by the user — pivoted to
  Primer after explaining the "tool not toy" rationale and rendering real comparison shots.
- Initial BOM dashboard showed "50" (the `/products` page cap) as if a real total — user caught
  it ("sao lừa vậy"). Root-caused to the 50-cap; replaced with the DH `bom` block (real,
  client-specific: johnson 574/651, growatt 20/63).

## Verification
- Tests: full suite **477 passed, 8 skipped** locally (matching CI). DH-policy guardrail green.
- CI/CD on tinsu runner (run 27087848485): tests ✓ → docker build ✓ → deploy-on-tinsu ✓ →
  nightly refresh ✓.
- Live: prod `barry-co.tinsu.ai` + demo `demo-co.tinsu.ai` both serve `--primary:#1f6feb`
  (Primer), healthz 200.
- Browser screenshots (light+dark) under `.ai/screenshots/2026-06-07-ux-redesign/` (gitignored):
  clients, dashboard, co-case before/after gate, data-page dashboards, nav dropdown.
- Local dev `127.0.0.1:8001` (file/DH mode); growatt-vn + johnson-vn DH-backed via local DH.

## Deploy notes (learned)
- Push to `main` = prod+demo auto-deploy via the tinsu runner; deploy is GATED on the test job
  (a test failure → deploy skipped, prod untouched). This saved us: the first push failed CI on
  a stale `test_data_hub_integration` assertion not in the local file-mode subset, so nothing
  bad shipped. **Run the FULL `uv run pytest` (not a hand-picked subset) before pushing to
  main** — the file-mode subset misses `test_data_hub_integration` etc.

## Open items
- ✅ Merged + deployed to prod + demo (`a33eaae`). Also shipped the pending `dc1b582`
  background-dossier-export.
- BOM dashboard real numbers depend on Data Hub deploying the `bom` block to prod/demo; until
  then CO shows the qualitative fallback (safe). **Confirm DH deployed it**, then fill the exact
  DH commit hash in the API-request artifact's Approval section.
- (optional) Authed live UI smoke on prod (`claude-check@local`) — only the public CSS was
  verified on prod, not the logged-in pages.
- Pre-existing open items unchanged (feedback #13/#14/#4).
