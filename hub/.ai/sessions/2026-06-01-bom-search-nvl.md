# Session 2026-06-01 — BOM search matches NVL/component codes

## What Was Done

Extended BOM product search so the single search box (`q`) matches **either**
the finished-product code **or** any component code inside the product's BOM —
"reverse lookup": which finished products use this NVL.

Changed `where_q` in both store functions in `app/stores/bom.py`
(`list_products_with_bom` + `count_products_with_bom`) from a plain
`product_code ilike %s` to:

```sql
and (ba.product_code ilike %s
     or exists (select 1 from hub.bom_artifact_rows r
                where r.artifact_id = ba.artifact_id and r.material_code ilike %s)
     or exists (select 1 from hub.bom_edges e
                where e.artifact_id = ba.artifact_id and e.child_code ilike %s))
```

- `bom_artifact_rows.material_code` → components in manual_flat / flattened shapes.
- `bom_edges.child_code` → components in technical_raw (graph) shape.
- Result shape unchanged: still a list of finished products (TP), just a wider set.
  `DISTINCT product_code` (already in the query) prevents duplicates when both the
  product code and a component match the same `q`.

Plumbing:
- `app/routes/api.py` — `api_list_products` (`GET /v1/hub/products`) now accepts and
  forwards `q` (previously dropped it entirely).
- `app/templates/clients/bom.html` — placeholder updated to
  "Tìm theo mã thành phẩm hoặc mã NVL trong BOM…".
- Cookie-UI route `app/routes/bom.py` needed **no change** — it already forwarded `q`
  to both store functions, so it inherits component search for free.

Tests: new `tests/test_bom_search_components.py` (7 tests) — match by product code,
by NVL in rows, by NVL in edges, exclude non-matching, no-duplicate when both match,
count==list, and an API test asserting `/v1/hub/products?q=` filters by component.
Built TDD (RED confirmed for the right reason before each GREEN).
**Full suite: 1303 passed, 15 skipped.**

UI proof: `.ai/features/2026-06-01-bom-search-nvl/` — `ui_smoke.py` + committed
`screenshots/bom_search_by_nvl.png`. Searching real NVL `001.0033100` on growatt-vn
returns the 8 finished products whose BOM contains it.

## Decisions Made

- **Scope chosen with the user** (AskUserQuestion): result = "TP that contains the NVL"
  (keep existing result shape, just filter wider), and match = "NVL code, exact
  substring (ILIKE)". Fuzzy / material-name search explicitly deferred.
- **No migration.** Existing indexes `idx_bom_artifact_rows_material` and
  `idx_bom_edges_child` already cover the EXISTS lookups; nothing to add.
- **Correlated EXISTS over JOIN.** Keeps the result one-row-per-product (no fan-out to
  dedup) and the existing CTE/aggregation untouched.

## What Didn't Work

- **Test fixture friction:** first artifact insert used `flatten_strategy='shallow'`,
  which violates `chk_flatten_strategy` (valid set: `manual_flat_as_provided`,
  `technical_exploded`, `purchased_btp_as_leaf`, `self_produced_btp_exploded`,
  `mixed_confirmed`, `no_strategy`). Switched to `manual_flat_as_provided`.
- **Dev server restart fought back:** old `--workers 4` left 4 child `python3` listeners
  holding `:8754` (cmdline is `python3`, not `uvicorn`, so `pkill -f uvicorn` missed
  them and the first restart hit "Address already in use" → served stale code). Fix:
  `lsof -ti:8754 | xargs kill -9`, confirm port down, then start fresh. Always verify
  the *new* code is actually serving before screenshotting.

## Open Items

- **Not committed yet.** Working tree has the 3 source edits + new test +
  `.ai/features/2026-06-01-bom-search-nvl/`. Awaiting user review before commit.
- Perf note: `ilike '%q%'` is a leading-wildcard so it can't use the trigram GIN; the
  EXISTS is correlated per-`artifact_id` so each only scans one artifact's rows — fine
  at current scale. If fuzzy/name search is wanted later, that's the migration (pg_trgm
  GIN on the BOM tables) that was deferred.
- CO consumes `/v1/hub/products` — the added `q` param is optional/back-compatible, no
  CO-side change required, but CO could now use it for component reverse-lookup.
