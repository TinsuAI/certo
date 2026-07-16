# Data Hub API Request: BOM-artifact coverage / readiness signal per product

**Date:** 2026-06-20 · **From:** CO (`barry-CO-main`) · **To:** Data Hub (BOM artifact owner)
**Related:** `2026-05-28-bom-artifacts-active-flat-filter.md`,
`2026-06-05-bom-picker-shallow-profile-filter.md` (depth=full), backlog M1, this session's
catalog-dependency review.

## Use Case
To produce a bảng kê for a product, CO needs a **fully-resolved flat** BOM artifact from DH (the
leaf-level material list that drives origin/LVC). When DH has **no full-flat artifact** for a product
(or only a shallow one), CO loads an empty/short material list → `lvc_status='missing_bom'` →
the operator is **blocked at lock/export** and must hand-build the BOM. Today CO only discovers this
**after** opening the case and clicking "Load BOM" — there is no way to know up front which products
are BOM-ready. CO needs a readiness signal so operators (and planning) can see coverage **before**
starting a dossier, and so we can quantify the DH coverage gap.

## Existing Endpoint Gap
- `GET /v1/hub/products?client_id=` (`app/data_hub_client.py:284`, `list_products`) returns the
  product list but says nothing about whether each product has a usable BOM artifact.
- `GET /v1/hub/products/{code}/bom/artifacts?...&shape=flat&depth=full` (the existing picker contract)
  answers "what flat artifacts exist for **this one** product" — but only per-product, on demand, and
  only **after** the operator opens it. There is no batch readiness view across a client's products.
- `list_bom_artifacts_batch` (`app/data_hub_client.py:339`) fetches artifacts for a set of product
  codes, but CO still has to derive readiness itself and only does so lazily.
- Net gap: no **coverage** projection (`which of my products are C/O-ready`) and no per-product
  **readiness flag** CO can surface before "Load BOM".

## Proposed Contract
Two additive pieces; (1) is the minimum, (2) is the nice-to-have rollup.

**(1) Per-product readiness flag on `list_products`** (additive fields):

```json
{
  "product_code": "PV00.0048500",
  "name": "...",
  "bom_readiness": {
    "status": "full_flat",        // full_flat | shallow_only | proposal_pending | none
    "best_artifact_id": "art_…",  // the artifact CO's picker would default to (depth=full), or null
    "flat_artifact_count": 1,
    "leaf_row_count": 312,        // null when status != full_flat
    "latest_proposal_status": null // mirrors any open CO proposal, see M1
  }
}
```

- `status` semantics align with the existing depth filter: `full_flat` = has a
  `flatten_strategy ∈ {technical_exploded, manual_flat_as_provided}` active artifact;
  `shallow_only` = only `purchased_btp_as_leaf` exists (CO must warn, not silently use);
  `none` = no flat artifact at all.

**(2) Client coverage rollup** — additive block on
`GET /v1/hub/dncxs/{client_id}/source-summary` (`app/data_hub_client.py:447`):

```json
"bom_coverage": {
  "products_total": 184,
  "full_flat": 121,
  "shallow_only": 18,
  "none": 45,
  "coverage_pct": 65.8
}
```

Query parameters: optional `include=bom_readiness` on `list_products` so the readiness join is
opt-in (avoids slowing callers that don't need it).
Request body: none.
Response body: additive only; existing fields unchanged.
Error cases: unchanged (`401`/`403`/`404`).

## Auth
Required scope: `hub:read` (same as `list_products` / `source-summary`).
Client scoping rule: unchanged — token must allow `client_id`.
Token type: user JWT or service token (unchanged). Read-only — **no mutation scope**.

## Data Semantics
Source of truth: DH `bom_artifacts` (the same table the picker filters). `bom_readiness.status` must
use the **same** depth/shape classification as `shape=flat&depth=full` so the readiness flag never
disagrees with what the picker actually offers.
Precision requirements: counts are integers; `coverage_pct` is informational (1 decimal fine).
Pagination: `bom_readiness` rides existing `list_products` pages; `bom_coverage` is a scalar block.
Idempotency: read-only.
Versioning or pinning: readiness reflects **active** artifacts only (`lifecycle=active`), consistent
with the picker.

Decision for DH to confirm: should `bom_readiness` count **manual/customs-declared** flats
(`manual_flat_as_provided`, intent `customs_declared` — the Mẫu-16 BOMs) as `full_flat`? CO treats
them as the preferred, leaf-complete pick, so they should count as `full_flat`. Please confirm the
authoritative readiness rule, since DH owns flatten semantics.

## Tests Required In Data Hub
Provider tests:
- Product with one `technical_exploded` flat → `status=full_flat`, `best_artifact_id` set,
  `leaf_row_count` matches the artifact's leaf count.
- Product with only `purchased_btp_as_leaf` → `status=shallow_only`, `leaf_row_count=null`.
- Product with no flat artifact → `status=none`.
- `bom_coverage` counts on `source-summary` equal the sum of per-product `status` values.
- `bom_readiness.status` agrees with `?shape=flat&depth=full` (no artifact counted `full_flat` that
  the picker would exclude as shallow).
Negative tests:
- `include` omitted → `list_products` response is byte-identical to today (no readiness join).
- Token without scope / wrong client → 403.
Edge cases:
- A product with both a shallow and a full artifact → `full_flat` (full wins).
- Manual/customs-declared flat → counted `full_flat` (per the decision above).

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`: pass `include=bom_readiness` through
`list_products`; read `bom_coverage` off `source_summary`.
Call sites that will consume:
- `app/bom_service.py` / the product list — render a "BOM: sẵn sàng / nông / chưa có" badge per
  product **before** the operator opens "Load BOM".
- Client / co-stock page — a "X/Y sản phẩm có BOM đầy đủ" coverage line so planning sees the gap.
- Pre-empts the `missing_bom` lock block (`app/routers/co_case.py:2011-2041`) by warning earlier.
Consumer tests: badge reflects `status`; coverage line reflects `bom_coverage`; a `none` product is
flagged before case open.

## Open Question for CO ↔ DH (process, not contract)
Even with this signal, products where `status=none/shallow_only` still cannot get an automatic C/O
BOM. The business decision (CO-side, raised in this session): for those products, is
"operator builds the BOM by hand / via workbook upload" the accepted workflow, or is missing
coverage a **blocker** that DH must close before CO files those products? This readiness signal makes
that decision **visible and measurable** either way.

## Approval
Data Hub contract owner:
Approval date:
Data Hub commit:
