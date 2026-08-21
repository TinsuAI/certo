# BOM summary — `bom` block added to `/source-summary`

**To:** CO repo (`barry-CO-main`)
**From:** Data Hub
**Date:** 2026-06-07
**Request:** `barry-CO-main/.ai/api-requests/2026-06-07-products-total-count.md`

## Status

Shipped (the lighter "alternative" path from the request). Live on dev
(`http://127.0.0.1:8754`) and demo after the next CI deploy. Provider
tests + API contract + API changelog updated.

The companion ask — real `total` + cursor pagination on
`GET /v1/hub/products` — is **deferred** (Data Hub backlog C.4): CO does
not need product enumeration yet, and the BOM dashboard headline is now
served by this `bom` block instead, with no extra round-trip. Pull C.4
out when a consumer actually needs to page the full product list.

## What's available

`GET /v1/hub/dncxs/{client_id}/source-summary` now returns a `bom` block
alongside the existing `material_catalog` / `product_catalog` / `bcct`
blocks. No new call — it's in the request CO already makes.

```json
"bom": {
  "exported_with_bom": 20,
  "exported_without_bom": 43,
  "exported_total": 63,
  "product_count": 171,
  "stale_count": 168,
  "multi_version_count": 65,
  "last_published_at": "2026-05-29T01:12:10+00:00"
}
```

## How to read it (read this before wiring the dashboard)

The original request asked for "# thành phẩm có BOM". We deliberately
did **not** answer that with a single catalog-category count — it is
misleading on real data:

- A naive "products with a BOM" count (`product_count`) is **inflated by
  BTP sub-assemblies**: Johnson derives a BOM per intermediate BTP, so
  `product_count=3605` is 574 TP + 3031 BTP. Growatt `product_count=171`
  is 7 TP + 128 BTP + 36 with no catalog row.
- A strict `category='tp'` count **undercounts**: Growatt's catalog tags
  most finished-ish codes `btp_sx` or leaves them uncategorized → only 7
  would show as "tp".

So the **headline is the export trio**, scoped to the products CO
actually issues C/O for and independent of catalog category:

- `exported_total` — distinct `customs_code`s declared as export in BCCT.
- `exported_with_bom` — of those, how many have a BOM (ready to certify).
- `exported_without_bom` — of those, how many have **no** BOM (the C/O
  readiness gap). `with + without == total`.

Real values today: Growatt 20/63 export codes have a BOM (gap 43);
Johnson 574/651 (gap 77).

**Caveat (important):** the export trio matches on exact `customs_code`
only. It is **blind to NB codes living inside `goods_name` parens**
(Growatt-shape — see Data Hub backlog A.5). Treat the numbers as a close
approximation, not an absolute count. Do **not** present
`exported_without_bom` as a hard "X products are non-compliant" figure.

Secondary fields:
- `product_count` — internal BOM coverage (TP + BTP). NOT a
  finished-product count; don't render it as "# thành phẩm có BOM".
- `stale_count` — products with an `is_stale` BOM (Track D). Growatt is
  168/171 today because no refresh has been run since upstream catalog
  edits — truthful state, not a bug.
- `multi_version_count` — products with >1 logical BOM version (pick the
  version effective at the shipment date when certifying).
- `last_published_at` — most recent BOM publish across the company
  (freshness), or `null`.

## Consumer plan (per the request)

- `app/web/client_context.py:_data_hub_overview_context` can read
  `summary["bom"]` directly — no extra round-trip.
- Recommended dashboard headline: `exported_with_bom / exported_total`
  ("X/Y mã xuất khẩu đã có BOM") + `exported_without_bom` as the gap to
  chase. Avoid `product_count` as the headline.
- Feature-detect: when `summary["bom"]` is absent (older Data Hub), keep
  the qualitative card. Never display a count you can't trust.

## Backward compatibility

Additive only. Existing callers that ignore unknown keys are unaffected.
Changelog entry: `2026-06-07 — Additive: bom block on /source-summary`.
