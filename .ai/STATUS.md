# Project Status

**Date:** 2026-06-07 (PM) — **BOM summary block on `/source-summary`
(CO request) — implemented + tested, NOT yet committed.** Also closed
backlog F.1 (Growatt re-ingest) as already-shipped.

## Current State

**Branch:** `main`, HEAD `d16743c` (F.1 backlog-close commit, pushed).
**Tests:** 1390 passed, 16 skipped (`uv run pytest -q`). **Migrations:**
latest **076** (unchanged — no schema change this session).

**⚠️ Uncommitted working tree** — the `bom` summary block feature is
done + green but NOT committed. Staged-equivalent changes:
- `app/stores/bom.py` — new `company_bom_summary(client_id)` (2 queries:
  per-product summary + BCCT-export coverage).
- `app/routes/api.py` — `bom` block wired into `api_source_summary`.
- `tests/test_read_api_auth.py` — empty-case assertions + new seeded test
  `test_source_summary_bom_block_aggregates` (+1 test).
- `docs/API_CONTRACT.md` + `docs/API_CHANGELOG.md` — Additive entry +
  field semantics + caveats.
- `.ai/BACKLOG.md` — F.1 closed (committed) + **C.4 added (DEFERRED)** for
  the `/products` total+pagination fix.
- `.ai/sister-app-notes/2026-06-07-bom-summary-block-available.md` +
  `INDEX.md` — outbound coordination note for CO.

**Suggested commit:** `feat(api): bom summary block on /source-summary
(export-coverage headline)`.

**What the `bom` block does** — `GET /v1/hub/dncxs/{client_id}/source-summary`
now returns a `bom` block (additive, same call CO already makes):
```json
"bom": {
  "exported_with_bom": 20, "exported_without_bom": 43, "exported_total": 63,
  "product_count": 171, "stale_count": 168, "multi_version_count": 65,
  "last_published_at": "2026-05-29T01:12:10+00:00"
}
```
- **Headline = export trio** (over distinct BCCT export `customs_code`s —
  the products CO certifies; category-independent). `with + without ==
  total`. Real data: Growatt 20/63, Johnson 574/651.
- `product_count` is **secondary** (distinct codes with a BOM incl BTP
  sub-assemblies — Johnson 3605 = 574 TP + 3031 BTP). NOT a finished-
  product count; documented as such.

## Recent Changes
- 2026-06-07 PM: `bom` summary block (this session, uncommitted). Closed
  F.1 (`d16743c`). Session log:
  `.ai/sessions/2026-06-07-bom-summary-block.md`.
- 2026-06-07 AM: BOM ingest follow-ups (B.1.5/B.2.5/B.3/B.2.7) — shipped +
  deployed to prod (`f161f12`). Session log:
  `.ai/sessions/2026-06-07-bom-ingest-followups.md` (if present).
- 2026-06-06: declarations merged-PDF + CRITICAL auth-leak fix. Deployed.

## Next Steps
1. **Commit the `bom` block** (see suggested message above). Then push =
   prod deploy via CI. CO can't see the field until then.
2. **Hand the CO-side prompt to `barry-CO-main`.** A ready-to-paste prompt
   for the CO consumer was produced this session (in the conversation —
   regenerate from the sister-app note if lost). It wires
   `app/data_hub_client.py` + `app/web/client_context.py:_data_hub_overview_context`
   + `app/routers/bom.py:bom_context` to read `summary["bom"]`, headline
   `exported_with_bom / exported_total`, feature-detect fallback. **Do NOT
   write code into `barry-CO-main` from this repo** (audit-only rule) —
   coordinate via the sister-app note only.
3. **Backlog C.4 (DEFERRED):** `/v1/hub/products` real `total` + cursor
   pagination. Store layer already supports it (`list_products_with_bom`
   takes limit/offset; `count_products_with_bom` exists); route-wiring
   only, ~2-3h. Pull out when a consumer needs to page the full product
   list. Not needed now.
4. **Sister-app cutover — BCQT remainder** (carry-over). `bcqt-prod`
   service token minted but not wired; decide revoke vs keep.
5. **C.1.a soak test** — BCCT `by-codes` under real CO load. Awaiting CO
   consumer ship.
6. **Repo hygiene** — pre-existing untracked files not from any feature:
   `docs/training/`, `scripts/generate_training_input_scenarios.py`,
   `scripts/uom_drift_report.py`, older `.ai/sessions/2026-05-*` +
   `2026-06-06-declarations-*.md` logs. Commit when convenient.

## Notes for Next AI Session
- **The `bom` headline is the export trio, by deliberate design.** We
  rejected `product_count` and `tp_with_bom` as headlines after checking
  real data: `product_count` is inflated by BTP (Johnson 3605 vs 574 TP);
  strict `category='tp'` undercounts (Growatt catalog tags finished-ish
  codes `btp_sx` → only 7). The export trio (BCCT export codes ∩ BOM) is
  category-independent and matches what CO actually certifies. If asked to
  "show # thành phẩm có BOM", do NOT just count tp — re-read this.
- **Export trio caveat:** exact `customs_code` match → blind to NB codes
  inside `goods_name` parens (Growatt-shape, backlog A.5). It is an
  approximation, not an absolute count. Told CO not to render it as a hard
  compliance number.
- **`stale_count` Growatt = 168/171** is truthful state (no refresh run
  since upstream catalog edits), not a bug.
- **Backlog still lags HEAD.** F.1 was shipped 2026-05-28/29 (`ccbb3ad` +
  `03e9c4b`) but listed open until this session. Trust git + code +
  memory `project_reingest_pending.md`; ground-truth before claiming open.
- **CRITICAL prod config (NOT in git):** DB setting `api_auth_strict=true`
  is THE enforcement switch; prod `.env` has `DATA_HUB_API_AUTH_DISABLED=0`
  — NEVER set to 1 in prod. CO service token at
  `/var/lib/barry-co/runtime/data-hub-link.json`; minted tokens at
  `/home/tinsu/sister_tokens_2026-06-06.json` (chmod 600).
- **Box (`100.84.189.87`):** prod DH `:8754` + CO `:8755` = Docker. Edge =
  Cloudflare tunnel `ttdatahub.tinsu.ai`. CI deploy = self-hosted runner
  on the box. **Push to `main` = prod deploy.** `.env` gitignored.
- **Cloudflare caches `.pdf`/`.zip`** unless origin sends `no-store`
  (`_no_store_sensitive` in `app/main.py`).
- **Regression guard:** `tests/test_v1_hub_auth_coverage.py` fails if a new
  `/v1/hub` route lacks auth.
- Dev server was `--workers 1 --reload` on `:8754` this session.
