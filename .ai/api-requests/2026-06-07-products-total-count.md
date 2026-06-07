# Data Hub API Request: reliable `total` (and real pagination) for `/v1/hub/products`

## Use Case
The CO redesign gives every per-company data page (Catalog, BCCT, Tồn CO, BOM) a small
overview dashboard with the key aggregate numbers. Catalog/BCCT pull their counts from
`source-summary.published_row_count` (real totals) and Tồn CO from CO's own materialized SQL —
all correct.

The **BOM** page has no trustworthy count to show. The natural BOM headline metric is "how
many finished products have a published BOM", but CO cannot obtain it today, so the BOM
dashboard currently shows a qualitative card ("BOM theo từng thành phẩm — xem Data Hub")
instead of a number. We want to show the real count.

## Existing Endpoint Gap
- `GET /v1/hub/products?client_id=X` (consumed via `data_hub_client.list_bom_products` →
  `bom_service.list_products`) is **hard-capped at 50 items** with no way to get the rest or
  the total. Observed against the current Data Hub:
  - Envelope is `{"items": [...], "total_estimate": null}`.
  - `total_estimate` is `null`.
  - `next_cursor` is **absent** → `_get_all` terminates after the first page (50 items).
  - Passing `limit=5000` still returns exactly 50 (the `limit` param is ignored).
  - Both `johnson-vn` and `growatt-vn` return exactly 50 — i.e. 50 is a page cap, not a count.
    (Item payloads are real and client-specific: johnson product codes like `1000553612`,
    growatt like `B700.0154100`.)
- `source-summary` (`GET /v1/hub/dncxs/{client_id}/source-summary`) returns
  `material_catalog` / `product_catalog` / `bcct` blocks with `published_row_count`, plus
  `co_stock_row_count` — but has **no `bom` block** at all. So there is no count of BOM
  finished-products or BOM lines anywhere CO can read cheaply.

Net: CO has no reliable BOM count, and `/v1/hub/products` cannot even enumerate beyond 50.

## Proposed Contract
Primary ask is a reliable **total**; secondary ask is real pagination so the 50-cap stops
silently truncating callers.

Method and path:
`GET /v1/hub/products`

Query parameters (existing + new/fixed):
- `client_id`: required (existing).
- `cursor`: opaque pagination cursor (please honor it — see below).
- `limit`: page size (please honor it, with a sane server max e.g. 1000).

Response body:
```json
{
  "items": [
    { "product_code": "1000553612", "...": "existing product fields" }
  ],
  "total": 318,
  "next_cursor": "eyJvZmZzZXQiOjUwfQ==",
  "server_time": "2026-06-07T03:21:00Z"
}
```
Notes on the shape:
- `total` = exact count of products for `client_id` across all pages (not an estimate). This
  is the field CO needs for the dashboard; it must be present on every page (or at least the
  first).
- `next_cursor` = non-null when more pages exist, null on the last page. Today it is absent,
  so callers silently stop at 50.
- Replacing the always-null `total_estimate` with a real `total` is preferred; if `total_estimate`
  must stay for back-compat, please ADD a populated `total` alongside it.
- Existing item payload unchanged; existing callers that read `items` keep working.

Definition of `total`: number of distinct finished products that have **at least one published
BOM artifact** for the client (i.e. the same population `/v1/hub/products` already enumerates).
If `/v1/hub/products` actually enumerates the full product catalog rather than only
BOM-bearing products, please clarify — CO specifically wants "# thành phẩm có BOM"; if that is
a different population, expose it as `bom_product_count` (see alternative below).

Error cases:
- `400 invalid_cursor` when `cursor` is malformed.
- `400 invalid_limit` when `limit` is non-numeric or exceeds the server max.
- `401 bearer token required`.
- `403 forbidden` when the token cannot view `client_id` (do not leak existence).

### Alternative (lighter, also acceptable)
Instead of (or in addition to) fixing `/v1/hub/products`, add a `bom` block to
`source-summary` so CO gets the count in the call it already makes:
```json
"bom": { "product_count": 318, "line_count": 9421, "latest_version": { "version_no": 7 } }
```
This is the cheapest path for CO (no extra round-trip; mirrors the existing
`material_catalog` / `bcct` blocks). The `/products` `total` + pagination fix is still
valuable for any consumer that needs to enumerate all BOM products.

## Auth
Required scope:
`hub:read` (same as current `/v1/hub/products` and `/source-summary`).

Client scoping rule:
Service-token `client_ids` whitelist must include `client_id`; user JWT must carry a claim
allowing this client. `total` must be scoped to the authorized client only.

Token type:
User JWT or service token (matches current endpoints; CO calls with the operator JWT via
contextvar in normal request flow).

## Data Semantics
Source of truth:
The Data Hub published-BOM store (same source that backs `/v1/hub/products` and the
per-product `/v1/hub/.../bom` artifacts). `total` and `bom.product_count` count the same
population the endpoint enumerates.

Precision requirements:
`total` / `product_count` / `line_count` are **exact** non-negative integers, not estimates.
Consistent with the page set (sum of `len(items)` across all pages == `total` for a stable
snapshot).

Pagination:
Standard `cursor` + `limit`. The cap must not silently truncate: either return a working
`next_cursor`, or document a hard maximum and signal truncation. CO needs at minimum a correct
`total`; full enumeration is secondary.

Idempotency:
Read-only, naturally idempotent. Same `(client_id)` returns the same `total` for a stable
snapshot.

Versioning or pinning:
Adding `total` / `next_cursor` / a `bom` summary block is backward-compatible (CO already
ignores unknown response keys via `_get_all`). CO will feature-detect: use `total` when
present, otherwise keep showing the qualitative card (never display the 50-cap as a count).

## Tests Required In Data Hub
Provider tests:
- `/v1/hub/products?client_id=X` returns `total` equal to the true product count, even when it
  exceeds one page.
- `next_cursor` is non-null while more pages remain and null on the final page; paging through
  yields `sum(len(items)) == total` with no duplicates.
- `limit` is honored (e.g. `limit=10` returns ≤10 items) up to the server max.
- `source-summary` includes a `bom` block with exact `product_count` (if the alternative is
  implemented).

Negative tests:
- Malformed `cursor` → 400 `invalid_cursor`.
- `limit` over max / non-numeric → 400 `invalid_limit`.
- Token without scope → 403; wrong `client_id` → 403 (no existence leak).

Edge cases:
- Client with 0 BOM products → `items: []`, `total: 0`, `next_cursor: null`.
- Client with exactly the page-size number of products → `total` correct, `next_cursor: null`
  (distinguishes "exactly 50" from "capped at 50" — the bug that triggered this request).
- Client with > page-size products → enumeration via cursor returns all, `total` matches.

## CO Consumer Plan
Adapter method to update in `app/data_hub_client.py`:
```python
def products_summary(self, client_id: str) -> dict:
    """Returns {items(first page), total, next_cursor}. Use `total` for counts;
    do NOT infer a count from len(items) (it is page-capped)."""
    return self._get("/v1/hub/products", {"client_id": client_id})
```
(`list_bom_products` stays for enumeration but must only be trusted once real pagination ships;
until then CO treats its length as a lower bound, not a total.)

Call sites that will consume it:
- `app/bom_service.py` — add `product_count(client)` returning `total` (DH) / local count (file).
- `app/routers/bom.py:bom_context` — replace the qualitative BOM card with
  `source_stats("bom", bom_products=<total>)` once `total` is available; keep the qualitative
  fallback when it is absent.
- If the `source-summary` alternative ships: `app/web/client_context.py:_data_hub_overview_context`
  reads `summary["bom"]["product_count"]` directly — no extra round-trip.

Consumer tests:
- Adapter surfaces `total`; bom_context renders the real count when `total` present.
- Fallback: when `total`/`bom` absent, the BOM dashboard shows the qualitative card (no number),
  never the 50-cap (guards against the regression this request fixes).

## Resolution (2026-06-07)
Data Hub shipped the **lighter alternative**: an additive `bom` block on
`GET /v1/hub/dncxs/{client_id}/source-summary` (no extra round-trip). The richer
`/v1/hub/products` `total` + real pagination change was **deferred** — that endpoint stays
50-capped on the Data Hub side; CO does not need product enumeration yet, so this is fine.

Shipped `bom` block (observed on johnson-vn / growatt-vn):
```json
"bom": { "exported_with_bom": 574, "exported_without_bom": 77, "exported_total": 651,
         "product_count": 3605, "stale_count": 10, "multi_version_count": 49,
         "last_published_at": "2026-05-25T12:34:52+08:00" }
```
Headline used by CO = export trio (`exported_with_bom / exported_total`, gap
`exported_without_bom`), NOT `product_count` (which includes BTP sub-assemblies). The trio is
an approximation (exact `customs_code` match, blind to NB codes in `goods_name`) — surfaced as
"mã XK chưa có BOM", never as a compliance/non-compliant verdict.

CO consumer landed (2026-06-07):
- `app/data_hub_client.py` — `source_summary` already passes the `bom` block through (raw
  `_get`); no change needed. No `/products` enumeration call added (still 50-capped, deferred).
- `app/web/client_context.py:source_stats` — reads `summary["bom"]`, renders the export trio +
  `product_count` detail + freshness/stale note; feature-detects (qualitative card when the
  `bom` block is absent on older Data Hub).
- `app/routers/bom.py:bom_context` — DH (lean) path renders the real metric; file mode uses
  local workspace counts.
- Tests: `tests/test_source_stats.py` (bom-block present → trio; absent → qualitative; gap
  warn-tone only when nonzero; file-mode counts).

## Approval
Data Hub contract owner:
Data Hub team — shipped the `source-summary.bom` block (additive, backward-compatible). The
`/v1/hub/products` `total`+pagination ask is acknowledged but deferred (not blocking CO).

Approval date:
2026-06-07

Data Hub commit:
Data Hub changelog `2026-06-07 — Additive: bom block on /source-summary`; coordination note
`.ai/sister-app-notes/2026-06-07-bom-summary-block-available.md` (data-hub repo). Exact commit
hash: TBD (fill from data-hub repo).
