# Project Status

## Current State
- **CO stock model reworked — `remaining_qty` is now the true folded tồn, not opening.**
  The trừ-lùi adjustment layer is folded into the materialized snapshot; only the live
  cross-case ledger is overlaid at read time. This closed an **overclaim guard gap** (cases
  could lock past real tồn). Deployed + prod backfilled. Detail:
  `.ai/sessions/2026-06-04-co-stock-fold-overclaim-and-vgm-bom.md`.
- **BOM picker now hides SHALLOW flats.** `shape=flat` let a 2-row shallow BOM
  (`purchased_btp_as_leaf`) leak into the per-TP picker next to the full one → picking it
  gave a wrong CO. CO now sends `depth=full` and drops shallow client-side (fallback proven
  live on prod — the demo DH instance doesn't echo `depth`/`is_shallow` yet). Picker-only;
  does NOT fix the VGM shortfall.
- **Git/deploy:** `main` = `tinsu/main` = **`72cc10d`** (in sync). Demo (tinsu) deployed at
  `72cc10d`, CI green. This session added 3 commits: `66fe311` (fold core) + `3e9f508` (UI) +
  `72cc10d` (BOM picker depth=full).
- **Prod johnson-vn is clean:** 1047 over-claimed claims released, **0 locked claims / 0
  overclaim** client-wide. Snapshot refolded (25,714 lots). Lock guard re-verified to block.
- **2 cases reset & stale (unlocked), awaiting decision:** `co-case-e015fad11e4a` (SCI,
  EU/EVFTA) and `co-case-ede4d913bafa` (VNG, Chile/Form B). Claims cleared; neither locked.
- **Prior session still live:** CO export + dossier flow (FORM MAU template, TKX/TKN files).
  See `.ai/sessions/2026-06-04-co-export-bangke-dossier-fixes.md`.
- **Client feedback batch 1 — #1/#3/#5/#6 DONE+live; #2/#4 need client input** (untouched).
  Tracker: `.ai/features/2026-06-01-client-feedback-batch1/brief.md`.

## Recent Changes (this session)
| Commit | Topic | Deployed |
|---|---|---|
| `66fe311` | fold trừ-lùi into snapshot `remaining_qty`; close overclaim guard gap; new `fold_baseline` / `refold_*`; `apply_used_qty` rewrite; `test_co_stock_fold.py` | tinsu |
| `3e9f508` | readable "Xem" button (teal-on-teal fix) + signed running-balance ("Tồn sau") history modal + overclaim badge | tinsu |
| `72cc10d` | BOM picker `depth=full` — drop shallow flats (`purchased_btp_as_leaf`); `is_shallow`/strategy fallback; shallow-only empty state; 13 tests | tinsu |
- Prod ops (not code): `refold_all_adjustments("johnson-vn")`; released 1047 claims on the
  2 cases; reopened the completed VNG case; marked both cases' sheets stale.

## Next Steps (priority order)
1. **VGM/MPL need Mẫu-16 BOMs (Data Hub / agency).** SCI's 94%-short VGM products have ONLY
   technical SAP-flattened BOMs (mã `1000xxx` stub, not in BCCT); no `m16_2025`
   (customs_declared) BOM exists for them. This is the blocker to building the SCI (EVFTA)
   C/O. `m16_2025` currently exists only for the 6 MFW products.
2. **Decide the 2 reset cases:** VNG (~6% short) is re-runnable in the UI now; SCI should
   stay stale until its VGM BOMs are fixed. Lock VNG if the client wants it issued.
3. **Close batch 1 — needs client input:** #2 confirm "mở" speed; #4 collect 3-5
   wrong-substitute examples → `.ai/api-requests/2026-06-01-substitute-ranking-quality.md`.
4. **(optional CO)** Make the calc snapshot path load the material catalog (`material_rows`
   is `[]` there today). Harmless now (catalog SAP entries are stubs), but needed once Data
   Hub completes SAP→HQ mapping so material enrichment runs at calculate time.
5. **(optional, DH-side)** Deploy DH commit `a8a3816` (the `depth`/`is_shallow` echo) to the
   demo DH instance so the shallow filter runs server-side. CO's client-side fallback already
   covers it; no CO change needed when it lands.
5. **Older deferred (unstarted):** origin lock TTL cleanup; customs FX backfill; seed
   missing CO forms; HS↔form coherence; claim-identity DB unique constraint.

## Blockers
- **SCI (EVFTA) C/O** blocked on VGM/MPL Mẫu-16 BOMs being ingested into Data Hub.
- **Batch 1 #4** blocked on client supplying concrete bad-example material codes.

## Notes for Next AI Session
- **CO stock effective tồn = `opening_qty − baseline_used_qty − ledger_used`.** opening +
  trừ-lùi baseline are FOLDED into `co_stock_rows` (refresh + import/void re-fold); only the
  live ledger is overlaid via `co_stock_ledger.apply_used_qty`. NEVER re-add
  `apply_adjustments` to read paths. On any deploy that changes the fold, run
  `co_stock_materializer.refold_all_adjustments(<client>)` per client. Memory
  `co-stock-folded-remaining-model`.
- **VGM shortfall is NOT a CO bug.** It's an upstream data gap: SAP-coded BOM materials are
  stubs in the catalog (no HQ mapping) and aren't in BCCT. Disproven dead-ends (don't
  retry): trừ-lùi exhaustion (0.2%), empty catalog (it has 12,482 rows), calc-not-loading-
  catalog (A/B test = identical shortfall), internal version override (use the UI dropdown).
- **Test env:** run `test_co_demo` and page/demo suites WITHOUT sourcing `.env` (file-mode);
  sourcing it enables Data Hub mode → ~56 spurious failures. DB-backed co_stock tests
  (materializer/ledger/adjustments) DO need `.env`. Never run two pytest suites concurrently
  against the local Postgres. Memory `test-env-filemode-vs-datahub`.
- **Prod debugging recipe (very effective):** `ssh tinsu 'docker exec -i co-app-1 python' <
  /tmp/probe.py`; DB `docker exec -i co-db-1 psql -U co -d barry_co` (db=`barry_co`, user `co`).
  Cases live in Postgres `co.co_cases`/`co_case_states`. Build a case for scripting via
  `R.case_from_record(R.default_client_case(client), client, R.get_case_record(client,cid))`.
- **Push semantics:** push to `tinsu/main` redeploys the demo; watch with
  `gh run watch <id> -R TinsuAI/co --exit-status`. Don't re-add forced Docker Hub pulls /
  `# syntax=` to the Dockerfile (memory `deploy-docker-hub-frontend-gotcha`).
- **BOM provenance:** `bom_variant_id=m16_2025` + `intent=customs_declared` = the Mẫu-16
  (customs-coded) BOM; `agency_2026-05-07` + `technical_flattened` + `sap_indented_raw` =
  the SAP technical BOM (stub codes). Per-product version picker in `co_case.html` is
  `select[data-bom-version-select]`; calculate submits the chosen artifact_id.
- **BOM flatten DEPTH ≠ flatten SHAPE.** `flatten_status='flattened'` only means "flat list",
  not "fully exploded". A SHALLOW flatten (`flatten_strategy='purchased_btp_as_leaf'`) keeps
  purchased BTP as a leaf → 2-row stub. CO drops shallow from the picker via `depth=full` +
  `bom_service._version_is_shallow` (mirror set: `{purchased_btp_as_leaf, mixed_confirmed,
  no_strategy}`, never `not_applicable`). Data Hub owns the authoritative classification.
- **Screenshots** must go under `.ai/screenshots/YYYY-MM-DD-<slug>/` (date prefix required;
  AGENTS.md updated, change uncommitted). Memory `screenshot-folder-date-prefix`.
- **Shell quirks:** use `command grep`/`command ls`; quote `--include="*.py"` (zsh no-match);
  `.pyc` are git-tracked.
- **Dev server:** `CO_AUTH_REQUIRED=0 nohup npm run co:serve > /tmp/co-serve.log 2>&1 &` on
  `:8001`, Postgres mode (snapshot paths live).
- **Memories this session:** `co-stock-folded-remaining-model`, `test-env-filemode-vs-datahub`,
  `screenshot-folder-date-prefix`.
