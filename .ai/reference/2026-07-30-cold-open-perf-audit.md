# Cold-open performance audit — case-open / origin cold-load path

Date: 2026-07-30. Scope: the path from "Tạo hồ sơ" through the first "Bảng kê C/O"
(origin) open for a brand-new case, and the substitute-modal pull that hangs off it.
Analysis only — no app-code change in this doc.

Grounding: numbers cited as measured come from `.ai/STATUS.md` (2026-07-27 CO-524 work,
in-container prod johnson-vn) and the P1 brief `.ai/features/2026-06-08-origin-cold-load-perf.md`
(local johnson-vn = 65,846 BCCT rows). Anything I could not tie to a recorded measurement is
marked `[estimate]`. File:line references are against HEAD of this worktree
(`main` = `520b720`, code = `8556ee1`).

---

## 1. Step-by-step timeline of a new case's first origin open

Client used for the concrete numbers: johnson-vn (the day-one large client; ~65k–73k BCCT
rows, ~13k materials). All routes below are `async def` that call **synchronous** Data Hub
HTTP inside the request coroutine — see the H2 note in §2.

### Stage A — POST create → 303 redirect
- `create_co_case` — `app/routers/co_case.py:972`. Resolves the shipment reference
  (`resolve_shipment_reference`, in-memory), `create_case_record`, returns a 303 to
  `/co-case/{case_id}`.
- Cost: **0.13s** measured (P1 brief). No Data Hub catalog pull here.

### Stage B — GET `/co-case/{case_id}` (shipment landing tab) + background preload fire
- `co_case_detail` — `app/routers/co_case.py:1075`. Two things happen:
  1. `asyncio.get_event_loop().run_in_executor(None, preload_co_case_origin_context, ...)`
     (`co_case.py:1083`) — fires the origin preload in a thread pool, non-blocking.
  2. Renders the shipment tab: `co_case_context(client_id, case_id, "shipment")`
     (`co_case.py:1089`).
- Shipment render path: `co_case_context` (`co_case_context.py:3489`) →
  `co_case_light_context` (`:154`) → non-origin branch →
  `co_case_source_context(skip_heavy_context=True)` (`:170`) →
  `DataHubPortfolioService.co_case_source_context` (`data_hub_client.py:872`), skip-heavy
  branch (`:903`).
  - Export-declaration case: `origin_invoice_matches` (`data_hub_client.py:956`) — narrow
    per-declaration `list_bcct(declaration_no=)` (`:980`) + `match_case_bcct_exports`. This
    is the **544840e fix**: before it, export-declaration cases fell through to the full
    `list_bcct` catalog pull on this default landing tab.
  - Invoice-only case: indexed `invoice_matches` endpoint (`:907`).
  - Plus `declaration_file_counts` (`:910`, narrow `list_declarations`).
- Cost: **~0.3s** measured landing-tab (P1 brief). The 524 that this fix removed was
  **124.88s → 0.31s** on prod johnson-vn (STATUS 2026-07-27), because the pre-fix skip-heavy
  branch pulled the full ~65k-BCCT corpus synchronously on the event loop.

### Stage B' — the background preload (concurrent with B, best-effort)
- `preload_co_case_origin_context` — `app/routers/co_case.py:289`. Skips if the record
  already has `source_snapshot` + `products` (`:295`). Otherwise runs
  `co_case_context(..., current_step="origin", force_source_refresh=True)` and persists the
  result via `update_case_record` (`:307`).
- With `force_source_refresh=True`, `co_case_light_context` takes the origin cold branch
  `origin_source_context` (`co_case_context.py:162→404`), NOT the old full pull:
  `source_summary` + narrow `origin_invoice_matches` + `declaration_file_counts`;
  `material_rows=[]`, `stock_rows=[]` (`:441-448`).
- Cost: **~0.1–0.3s** `[estimate]` — same narrow fetches as Stage B, run once, then a case
  record write. This is the mechanism that made "F5 worked" before the fix: the preload
  persisted `source_snapshot`, so the next origin click hit the warm path.

### Stage C — user clicks "Bảng kê C/O" → GET `/co-case/{case_id}/origin`
- `co_case_step` — `app/routers/co_case.py:1094` →
  `co_case_context(client_id, case_id, "origin", requested_sheet=...)` (`:1098`).
- In `co_case_context`, because `not force_source_refresh and case.get("source_snapshot")`
  is truthy once the preload persisted, it sets `cached_case_context=True`
  (`co_case_context.py:3523`). Then in `co_case_light_context`:
  - **Warm (preload finished):** `use_cached_context=True` (`:159`) →
    `cached_origin_source_context` (`:161→543`) — reuses `case["source_invoice_matches"]`,
    `stock_rows=[]`, `material_rows=[]`, plus one narrow `declaration_file_counts` call.
    Cost: **~0.3–1.1s** measured (P1 brief "origin lần 2"). Dominated by the render funnel
    (`bom_service.workspace`, `attach_case_bom_snapshot`, `attach_origin_readiness`,
    `attach_results`, `attach_origin_sheet_states`, `attach_bom_version_picks`,
    `build_case_criteria_rows` — `co_case_context.py:196-245`), not by Data Hub.
  - **Cold (user beat the preload):** `use_cached_context=False`, origin branch →
    `origin_source_context` (`:162→404`) — the same narrow fetches as Stage B'. Cost:
    **local 3.5s → ~0.1s after the P1 fix**; the residual is the narrow Data Hub round trips
    + render funnel. The key change: the origin tab no longer reads the full ~60k co_stock
    snapshot (that was 2.6s cold + 540ms/load for data the shell render never consumed) and
    no longer runs the full `list_bcct` (~21–40s for big clients, per the pre-fix code
    comments the brief quotes).

### Stage D — (only if the operator opens the substitute modal) substitute-candidates
- `co_case_origin_sheet_substitute_candidates` — `app/routers/co_case.py:2314`. For a
  `material_code`, it first calls `list_material_substitutes` (indexed DH endpoint, ~300ms).
  On an empty result it falls back to the HS-prefix heuristic, which needs the materials
  catalog: `co_case_material_catalog_cached(client, case)` (`co_case.py:2385`) →
  `co_case_context.py:373` → `svc.material_catalog(client)` (`data_hub_client.py:858`) — a
  materials-only `list_materials` pagination.
- Cost: **~15.69s cold** measured on prod johnson-vn (14 calls, **0 bcct**, 12,943 rows;
  STATUS 2026-07-27), then served from the 300s TTL cache (`co_case_context.py:372`) for the
  rest of the session. This is the **c104615 fix**: before it, the modal called
  `co_case_source_context_cached` (the full ~125s BCCT + materials pull) but read only
  `material_rows` → a cold modal open was ~125s → Cloudflare 524.
- The `search` branch (`co_case.py:2407`) additionally reads
  `read_co_stock_rows_cached` (`:2422`) + `co_case_material_catalog_cached` (`:2423`) for
  stock-first discovery — both cached, no live BCCT pull.

### Stage E — (later) first "Tính" on a sheet → /calculate
- Not part of tab-open, but it is the next cold cost the operator hits, and it drives the P2
  opportunity. Fast `/calculate` builds stock from `_calculate_stock_rows_from_snapshot`
  (`co_case_context.py:3873`) → `read_co_stock_rows_cached` (`co_stock_materializer.py:423`):
  **2.6s cold JSONB deserialize, ~0 warm** (invalidated by a `(max(indexed_at), row_count)`
  snapshot marker, `:400`; cache holds max 4 clients, `:397`). A stale snapshot
  (`> CALCULATE_SNAPSHOT_FRESHNESS_SECONDS = 30`, `co_case_context.py:3830`) triggers a
  **non-blocking** background refresh (`:3897`), not a synchronous re-pull.
- The names/`customs_relevance` for the bảng kê come from a separate catalog pull:
  `_material_catalog_rows` (`co_case.py:530`, `_MATERIAL_CATALOG_CACHE` TTL **90s**, `:527`)
  via `_ensure_origin_material_rows` (`:562`). ~13k rows for johnson `[estimate ~a few s cold]`.

### Timeline summary (johnson-vn, cold)

| Stage | Route / function | Cost | Source |
|---|---|---|---|
| A create | `create_co_case` (`co_case.py:972`) | 0.13s | measured (P1) |
| B shipment landing | `co_case_detail` → skip-heavy narrow (`co_case.py:1075`) | ~0.3s (was 124.88s → 0.31s pre/post 544840e) | measured (P1 + STATUS) |
| B' preload | `preload_co_case_origin_context` (`co_case.py:289`) | ~0.1–0.3s | estimate |
| C origin warm | `co_case_step` → `cached_origin_source_context` (`co_case.py:1094`) | ~0.3–1.1s | measured (P1) |
| C origin cold | `co_case_step` → `origin_source_context` (`co_case_context.py:404`) | 3.5s → ~0.1s (post P1) | measured (P1) |
| D substitute modal | `..._substitute_candidates` → `material_catalog` (`co_case.py:2314`) | ~15.69s cold, then 300s cache (was ~125s → 524 pre c104615) | measured (STATUS) |
| E first /calculate | `read_co_stock_rows_cached` + catalog (`co_case_context.py:3873`) | 2.6s snapshot + ~13k-row catalog | measured (P1) + estimate |
| — index (case list) | `co_case_context` index (`co_case_context.py:3489`) | 4.27s johnson (3 dossiers); 0.85s growatt | measured (P1) |

---

## 2. Already fixed vs residual

### Fixed and deployed
- **Origin cold-load full BCCT + 60k snapshot removed (P1, `a1ac2ed`).** Origin tab reads
  `origin_source_context` (narrow invoice_matches, `stock_rows=[]`, `material_rows=[]`)
  instead of the full pull + 60k co_stock read. Local **3.5s → ~0.1s**. Parity test:
  `/calculate` + lock produce identical tồn.
- **Shipment-tab 524 (`544840e`).** Skip-heavy branch for export-declaration cases now uses
  the narrow `origin_invoice_matches` (`data_hub_client.py:956`) instead of the full
  `list_bcct`. Prod johnson-vn **124.88s → 0.31s**, same 2 matches.
- **Substitute-modal 524 (`c104615` + `8556ee1`).** New `material_catalog` (materials-only,
  `data_hub_client.py:858`) behind `co_case_material_catalog_cached` (300s TTL,
  `co_case_context.py:373`); the modal no longer pays for the BCCT corpus. Prod **~125s →
  15.69s** (0 bcct calls). Parity test locks `material_catalog == heavy material_rows`
  byte-for-byte.

### Residual (open)

- **Substitute-modal cold catalog pull ~15.69s.** Still a full `list_materials` pagination
  the first time the heuristic fires per client per 300s window (`co_case.py:2385`). No
  longer a 524 (15s < 100s), but a visible stall. This is the direct target of opportunity
  #1 below (materialize into the snapshot) and #3 (per-client warm cache).

- **Index N+1 `claims_summary_for_case` — 4.27s johnson-vn.** `co_case_context` index loops
  per dossier calling `co_stock_ledger.claims_summary_for_case` (`co_case_context.py:3530`),
  one `co_stock_claims` query per case. **In-flight fix: branch `agent/p1-index-n1-claims`
  (commit `a5436ce`, not merged).** It adds `claims_summary_for_cases` (a single grouped
  `case_id = any(%s)` query, `co_stock_ledger.py` +33 lines) and replaces the loop with one
  batched call in `co_case_context` (+ `tests/test_co_stock_claims_summary_batch.py`, 229
  lines). Collapses N queries → 1. Same-shape defaults preserved for cases with no claims.
  Recommend merging.

- **H2 — sync Data Hub pulls block the event loop.** `co_case_detail`, `co_case_step`, and
  `co_case_origin_sheet_substitute_candidates` are `async def` but call the synchronous
  `co_case_context` / `material_catalog` inside the request coroutine. The residual cold
  stall (~15s substitute; the narrow origin fetches) still blocks the loop, so one slow
  request stalls concurrent requests on the same worker. **In-flight: branch
  `agent/co524-async-offload` (commit `6a6affa`, not merged)** offloads the sync pulls off
  the loop. Not a 524 risk on its own, but a throughput/tail-latency fix.

- **Narrow-fetch material identity gap.** `origin_invoice_matches` omits
  `include_material_identity` on its per-declaration `list_bcct` (`data_hub_client.py:980`),
  so item_code shows the raw vs display code on a non-origin cold window (display-only).
  **In-flight: branch `agent/co524-material-identity` (commit `f1484b1`, not merged)** — the
  narrow export by-codes fetch already supports the flag (`data_hub_client.py:116`,
  `include_material_identity`); needs its own test because it is shared with the origin tab.

---

## 3. Ranked remaining opportunities

Ranked by impact/effort. Impact framed against the johnson-vn cold numbers above.

### R1 — Materialize `customs_relevance` + name into the co_stock snapshot (P2). HIGH impact, MEDIUM risk.
- Removes the ~13k-row `list_materials` catalog pull from the fast `/calculate` and export
  paths (`_material_catalog_rows`, `co_case.py:530`), and shrinks the substitute-modal
  heuristic dependency. Today `/calculate` reads the snapshot (`read_co_stock_rows_cached`)
  but must ALSO pull the catalog just for names + `customs_relevance` — the fields that make
  the bảng kê non-blank and let junk fold out. If those two fields ride on each `co_stock_row`
  payload at materialize time, the fast path becomes snapshot-only.
- Impact: cuts the catalog round trip (~13k rows) off every first `/calculate` and export in
  a session; also reduces the substitute-modal cold path since the same catalog data is then
  local.
- Risk: MEDIUM. Requires a snapshot-shape addition + invalidation discipline — the snapshot
  is trừ-lùi-folded and delta-refreshed, so a new field must be backfilled by a forced full
  re-derivation (same pattern as migration 020 `DERIVATION_SCHEMA_VERSION` and #14's
  `co_config_fingerprint` refresh guard). Getting invalidation wrong leaves stale names /
  `customs_relevance` on the bảng kê. Ship behind a fingerprint bump.
  Cross-referenced: BACKLOG P1 "P2", STATUS Next Steps 0b(a).

### R2 — Lot-scoped `/calculate`. MEDIUM impact, LOW–MEDIUM risk.
- Scope the stock read to the product's lots instead of loading the whole client snapshot per
  calculate (`_calculate_stock_rows_from_snapshot` currently reads all of
  `read_co_stock_rows_cached`, `co_case_context.py:3891`). Saves ~540ms/calc `[estimate,
  from the P1 "540ms/load" figure]` on big clients; larger on cold snapshot reads (2.6s).
- Risk: LOW–MEDIUM. The allocation pool and the sheet-lock overclaim guard net claims across
  ALL cases (`case_allocation_pool` `co_case_context.py:2159`; `record_sheet_lock`
  `co_stock_ledger.py`), so lot-scoping must not drop cross-case claim rows for lots the
  product touches — scope by the product's candidate lots, keep the ledger overlay whole.
  Needs a calculate-vs-lock parity test. Cross-referenced: BACKLOG P1 "(Optional) /calculate
  lot-scoping".

### R3 — Per-client warm cache (nightly / first-access). MEDIUM impact, LOW risk.
- Warm `material_catalog` (and optionally the co_stock snapshot) per client on a schedule or
  on the first access of the day, so the first origin open / substitute modal of every new
  case reuses a hot cache instead of paying the ~15.69s cold `list_materials`. The caches
  already exist (`_CO_MATERIAL_CATALOG_CACHE` 300s `co_case_context.py:372`;
  `_MATERIAL_CATALOG_CACHE` 90s `co_case.py:527`; `_CO_STOCK_ROWS_CACHE` `co_stock_materializer.py:396`)
  — this is a warmer, not new plumbing.
- Impact: turns the substitute-modal / catalog cold stall into a warm hit for the operator's
  first case of the session. Bounded by TTL — a nightly warm only helps the first request
  inside each TTL window, so pair with a longer TTL or a keep-alive ping.
- Risk: LOW. Read-only pulls; worst case a wasted background fetch. Do NOT warm by calling
  `preload_co_case_origin_context` (it WRITES the case record — see STATUS harness note).
  Cross-referenced: BACKLOG P1 option 4.

### R4 — Preload-with-progress. LOW–MEDIUM impact, LOW risk.
- Today the preload is best-effort in a thread (`co_case_detail`, `co_case.py:1083`); if the
  operator clicks origin before it persists, the origin request runs the cold narrow fetch
  synchronously (Stage C cold). Fire the preload at POST-create time too (not only on the
  shipment GET), and show a "đang nạp dữ liệu nguồn…" state + poll on the origin tab (the
  background-export pattern) instead of a request that blocks on the fetch.
- Impact: post-P1 the cold origin fetch is already ~0.1s narrow, so the win is mostly on the
  substitute modal and on removing the "click origin too fast → synchronous stall" tail.
  Smaller now than pre-P1, hence lower rank. Best combined with H2 async-offload
  (`agent/co524-async-offload`) so the fallback fetch never blocks the loop.
- Risk: LOW. UI + scheduling only; no change to derivation or claims.

Ordering rationale: R1 removes a whole class of catalog pulls from the two hot paths and is
the standing P2 item; R2 is a bounded per-calculate win with a clear parity test; R3 is cheap
(warmer over existing caches) but TTL-bounded; R4 is now a tail-latency polish because P1
already made the cold origin fetch narrow. The two in-flight branches (`agent/p1-index-n1-claims`,
`agent/co524-async-offload`) are lower-effort than any of R1–R4 and should merge first.

---

## 4. Reusable in-container measurement harness pattern

From STATUS "Notes for Next AI Session" (2026-07-27), proven on the 524 root-cause and fix
verification. Reuse this to measure any cold Data Hub path against real prod data:

- Access: `ssh tinsu` → `docker exec -i co-app-1 python -` and pipe a harness on stdin
  (`scripts/` is NOT in the Docker image, so pipe the code, don't reference a repo file).
- Build the real client: `data_hub_client_from_env()` picks up the prod service token from
  the container's config file — no manual token minting.
- Count + time HTTP calls: wrap `client._get` (`data_hub_client.py:509`) to increment a
  per-path counter and record elapsed time per call. This is how the 524 was pinned at
  124.88s / 74 bcct pages and the fix verified at 0.31s (shipment) and 15.69s / 0 bcct
  (substitute modal).
- Safe read-only entry points on prod: `co_case_source_context`, `origin_invoice_matches`,
  `material_catalog`. **Do NOT** call `preload_co_case_origin_context` on prod — it writes
  the case record. Use nightly (`nightly-co-app-1` / `demo-co`) for anything that could
  mutate; prod has live agency data.
- Do not trust the access log for slow-request timing: it carries no request duration, and a
  Cloudflare 524 still logs `200 OK` once the origin finally finishes. Time inside the
  harness.
- Engineering lesson baked into this audit: when a narrow replacement for a heavy DH call is
  introduced, audit EVERY call site of the heavy call. The origin tab got
  `origin_invoice_matches` in 2026-05; the shipment light path and the substitute modal kept
  the full pull for over a year → two separate 524s (`544840e`, `c104615`).
