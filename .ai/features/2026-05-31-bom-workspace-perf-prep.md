# Feature prep: BOM workspace perf — the next origin bottleneck

**Status:** IMPLEMENTED locally (Option A, parallel client-side fetch) — TDD +
reviewed, parity byte-identical on real Johnson products, full suite green. NOT yet
committed/deployed/prod-benchmarked (pending user go-ahead). Discovery question
resolved: no multi-product batch DH endpoint exists (all BOM paths key on a single
`{product_code}`), so a batch endpoint would require a DH contract change → A is the
correct self-contained move. See STATUS.md for the result summary.

## Problem

After the BCCT pull was eliminated (origin source-context ~60s → ~0.9s), the
**BOM workspace** is the dominant remaining cost of a cold origin load — ~22s on a
product-heavy case (discovery-era figure; it scales with the number of products in
the case, so it's variable, not constant).

## Where the cost is

`co_case_light_context` (app/main.py:1257-1265) builds the BOM workspace for the
origin step:

```python
bom_product_codes = co_case_bom_product_codes(case, invoice_matches)
bom_workspace = bom_service.workspace(client, product_codes=bom_product_codes, case_id=picker_case_id)
```

`BomService._build_workspace` (app/bom_service.py:87) loops over each product and
makes a **sequential** Data Hub round trip per product:

```python
for product in product_rows:                      # N products in the case
    artifact_payloads, _ = self.product_artifact_payloads(client_id, product_code, case_id=case_id)  # ~1 DH round-trip / product
    ...
    payload = self.data_hub.get_bom_latest(client_id, product_code)   # fallback path, also per-product
```

So cost ≈ N × (per-product DH latency). Johnson has many products + large BOMs
(`n_bom=10 275` client-wide). There is an in-process cache (TTL 60s, key =
`(base_url, client_id, token, sorted_product_codes, case_id)`,
app/bom_service.py:27-28) so a reload within 60s is fast; a cold load pays in full.

## Options (recommendation: A)

| Option | Effort | Risk | Gain | Verdict |
|---|---|---|---|---|
| **A. Parallel client-side fetch** | Low–Med | **Low** (same data, same output) | ~22s → ~3–4s, scales with N | **Recommended** |
| B. Warm full-client BOM in preload | Low | Low | Hides cost, doesn't remove it; may over-fetch | Band-aid — skip |
| C. Materialize BOM snapshot (like `co_stock`) | **High** | Med–High (new subsystem) | Best steady-state (local DB read) | Fallback only if A insufficient |

**Why A:** the loop fetches independent per-product artifacts and only assembles
them afterward — fetching them concurrently produces a byte-identical workspace, so
parity risk is near zero. Materialize (C) is the "right" long-term answer but means
rebuilding the whole `co_stock_materializer`-style machinery for BOM — premature for
something that may be "fast enough" after A.

## Key gotcha for A (do NOT skip)

`httpx.Client` here is **synchronous** → use a `ThreadPoolExecutor`, not asyncio.
The DH token lives in a **contextvar** `CURRENT_DATA_HUB_TOKEN`
(app/data_hub_client.py:~38). **Worker threads do NOT inherit contextvars
automatically** — capture the token in the calling thread and re-set it inside each
worker (or pass it explicitly), or every parallel BOM fetch will use the wrong/empty
token and 401. This is the single most likely source of a silent bug. Also confirm
thread-safety of the shared `httpx.Client` (it is, for concurrent requests) and keep
the per-product fallback paths intact (`get_bom_latest`, `DataHubBomVariantConflict`,
404 skip).

Pick a sane concurrency cap (e.g. 8–10); N (products per case) is small so this is
plenty and won't hammer DH.

## Open discovery question (resolve first)

Parallel client-side (A, no DH change) vs **asking Data Hub for a batch endpoint**
(fetch BOM for many product_codes in one round-trip). The batch endpoint would be
strictly better (1 round-trip) but **touches the DH contract** → per CLAUDE.md, that
needs an API-request artifact under `.ai/api-requests/` and DH-side approval. A is
self-contained and needs no DH change → do A now; consider proposing a batch
endpoint later if A isn't enough.

## Suggested flow next session

1. Short `/discover`: confirm A vs DH-batch; check whether
   `list_bom_artifacts_filtered` (app/bom_service.py:215) already offers any
   batching that helps.
2. `/tdd`:
   - Parity test FIRST: **parallel `_build_workspace` output == sequential output**
     on a real product-heavy Johnson case (product_versions list deep-equal,
     composition identical, ordering preserved — the function already sorts at
     bom_service.py:166-169, so ordering is deterministic regardless of fetch order).
   - Implement the ThreadPoolExecutor fetch with correct contextvar propagation.
   - Guard: token-in-thread (no 401), fallback paths, cache key unchanged.
3. Benchmark cold `/origin` on a product-heavy case (local + prod). Target ~22s →
   ~3–4s.

## Benchmark harness (reuse from this session)

- Local: `set -a; . ./.env; set +a` then drive
  `main.co_case_context('johnson-vn', '<case_id>', current_step='origin', force_source_refresh=True)`
  (force_refresh = cold path) and time it; or curl `/origin` on a fresh case
  (auth off locally).
- Prod: Bearer JWT via `POST https://ttdatahub.tinsu.ai/v1/auth/token`
  `{"email":"claude-check@local","password":"claude-temp-2026"}`, then curl
  `https://barry-co.tinsu.ai/clients/johnson-vn/co-case/<id>/origin`. Use a
  product-heavy case (the existing prod case `co-case-0605189d5eea`, invoice
  `VNG26050002`, has products). NOTE: prod delete needs a privileged role — to
  remove a throwaway case use `delete_case_record` in container `co-app-1` via SSH
  `tinsu` (the demo account gets 403 on `/delete`).
