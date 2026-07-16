# Data Hub API Request: stable material names for `bom_observed` codes (DC2)

**Date:** 2026-06-20 · **From:** CO (`barry-CO-main`) · **To:** Data Hub (BOM artifact / catalog owner)
**Related:** DH leaf-declarability brief (Finding 2), backlog DC2, this session's catalog-dependency
review.

## Use Case
CO renders material **names** on the bảng kê C/O and in the substitute picker. For materials that
appear only in the technical BOM source (DH group `bom_observed`), the name CO shows today
("Tube;Round;45#;…", "Rendering;Semi-Assy") must come from a **stable, contract-guaranteed field**.
If that source disappears or moves, every `bom_observed` line on the bảng kê goes **nameless** — a
C/O with blank material descriptions is not emittable.

## Existing Endpoint Gap
The DH leaf-declarability brief (Finding 2) states: `hub.bom_artifact_rows.payload = {}` for **every**
`bom_observed` material; the real name lives only in `hub.catalog_candidates.sample_text`. So:
- CO consumes BOM rows via `bom_service` (`get_bom_artifact` / `get_bom_latest`,
  `app/bom_service.py:354/441`) and material rows via `list_materials`
  (`normalize_material_row` reads `row["name"]`, `app/data_hub_client.py:1095-1110`).
- For `bom_observed` codes, `payload={}` means the BOM-row path carries **no name**. CO currently
  still shows names (verified in case records' `material_description`), which means CO is reading
  them from **some** field — but the brief warns this is **not** the flat-row payload. We need DH to
  confirm and **guarantee** the source.
- Render-time precedence in CO (`app/web/co_case_context.py:1978`):
  `override name → material_description on the row → DH material.name`. If all three are empty CO sets
  `material_name_missing=true` (`co_case_context.py:2002`) — a visible warning, but the operator then
  has to type every name by hand.

## Proposed Contract
Make a non-empty `name` (or `material_description`) a **contract guarantee** on the rows CO already
fetches — DH populates it from `catalog_candidates.sample_text` when the flat-row payload is empty.

Method and path: extend the existing `GET /v1/hub/products/{product_code}/bom/artifacts` /
`.../bom/latest` row schema **and** `GET /v1/hub/materials` (no new endpoint).

Query parameters: none new.
Request body: none.
Response body (additive guarantee on each material/BOM row):

```json
{
  "material_code": "1000478517",
  "name": "Tube;Round;45#;φ75.6x□40.5x40.5x2200",
  "name_source": "catalog_candidate",   // "bom_payload" | "catalog_candidate" | "none"
  "customs_relevance": "declarable_unmatched"
}
```

- `name`: MUST be non-empty whenever DH has any text for the code (today `{}` payload → empty).
  DH fills it from `catalog_candidates.sample_text` when the flat-row payload has none.
- `name_source` (new, optional but preferred): lets CO show provenance and lets us both detect
  regressions ("X% of names are `none`").

Error cases: unchanged.

## Auth
Required scope: `hub:read` (same as existing material/BOM reads).
Client scoping rule: unchanged.
Token type: user JWT or service token (unchanged).

## Data Semantics
Source of truth: `catalog_candidates.sample_text` (DH owns it) when `bom_artifact_rows.payload` has
no name. CO must **not** reach into `catalog_candidates` directly — names must arrive on the rows CO
already consumes, via the adapter.
Precision requirements: exact string passthrough (Vietnamese/技术 text intact, no truncation).
Pagination: unchanged (names ride existing artifact/material pages).
Idempotency: read-only; same code → same name.
Versioning or pinning: name follows the artifact CO pinned; a re-ingested name change should not
silently alter a **locked** sheet (CO snapshots the name onto the case at load — see Consumer Plan).

Decision for DH to confirm: is `catalog_candidates.sample_text` the authoritative display name for
`bom_observed`, or is there a cleaner canonical name field DH would rather expose? CO defers to DH on
the source — the only hard requirement is that **a name arrives on the BOM/material row**.

## Tests Required In Data Hub
Provider tests:
- A `bom_observed` code with `payload={}` returns a non-empty `name` (from `catalog_candidate`) and
  `name_source="catalog_candidate"` on both `/bom/latest` rows and `/materials`.
- A code whose flat payload already has a name returns `name_source="bom_payload"` (no regression for
  the well-formed path).
Negative tests:
- A code with no text anywhere returns `name_source="none"` and an empty `name` (CO falls back to its
  `material_name_missing` flag — explicit, not a silent blank).
Edge cases:
- Multi-byte / special characters in `sample_text` round-trip unchanged.
- A code present in `catalog_candidates` but absent from the artifact still resolves a name via
  `/materials`.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`: none new — `normalize_material_row` and the BOM
row normalizers already pass `name` through; assert non-empty once DH guarantees it. Optionally read
`name_source` for a provenance badge / regression metric.
Call sites that will consume: `app/web/co_case_context.py:1978` (render precedence — DH name becomes
a reliable tier-3 instead of frequently-empty); substitute picker (`app/routers/co_case.py:2150+`).
**Snapshot-on-load (CO-side hardening, ship regardless of DH):** copy the resolved name onto the case
material row at "Load BOM" so a later DH name change cannot blank a sheet that's already in progress —
this is what makes the dependency *soft* once a case is loaded.
Consumer tests: name renders for a `bom_observed` line; `material_name_missing` only when DH returns
`name_source="none"` AND no override.

## Approval
Data Hub contract owner:
Approval date:
Data Hub commit:
