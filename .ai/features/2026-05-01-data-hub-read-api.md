# Feature: Data Hub API contract (M9 deliverable companion)

**Date:** 2026-05-01 (v2 — incorporates round-3 critic + auto-only proposal pattern)
**Status:** design draft, schema-design pass pending
**Companion to:** `.ai/features/2026-04-30-data-hub-mvp.md`

## Why this exists

Round-2 critic's #1 ask: design schema *back from* consumer endpoints, not *forward from* CO's tables. This doc enumerates what BCQT and CO actually need from `hub`, then audits whether the brief's schema decisions match.

After the 2026-05-01 BCCT-amendment, BCCT writes flow only from Data Hub's UI. **BOM is the exception:** CO submits BOM modifications as **proposals** (request-to-write, not direct write); Data Hub auto-evaluates and either approves (materializing a new immutable version) or rejects (CO modifies and resubmits). MVP runs auto-only; manual review is deferred to phase 2.

## Consumer scenarios

### BCQT — annual settlement (Mẫu 15 / 15a / 16)

For a single `(DNCX, year)` settlement run, BCQT needs:
- All BCCT rows for that DNCX in that year (10k–100k rows typical) — drives Mẫu 15/15a aggregation.
- Material registry for the DNCX (full snapshot — typically 100s of rows) — drives code resolution + category-based aggregation.
- BOM **per-transaction**, not "current": each BCCT row references the BOM version that was active at the time the transaction was processed (point-of-use binding, per round-3 critic). Settlement reads what was bound, not "what's current today."
- Optional: prior-year closing inventory state for opening-inventory carryover.

Cadence: annual, batch. Latency tolerance: seconds–minutes per query. Once a year is closed, data is immutable — strong caching possible.

### CO — per-shipment certificate

For each shipment, CO needs:
- Material registry lookup by the DNCX's tracking code (see "Tracking-code mode" below).
- BOM for the product, **pinned to a specific version** (legal audit requirement — CO must re-fetch the exact BOM that backed a certificate years later).
- BCCT lookup over a window — to check prior import declarations for materials being claimed.
- Sometimes: submit a modified BOM proposal (e.g., to swap NVL composition for RVC-threshold compliance) and consume the resulting `version_id` in the certificate dossier.

Cadence: real-time, per-shipment. Latency tolerance: sub-second per query. Proposal latency in auto mode is also sub-second (synchronous evaluation).

## Tracking-code mode (per-DNCX, immutable)

Some DNCXs use `customs_code` as the canonical join key; others use `product_code`. Mode is set at DNCX onboarding via `hub.dncxs.tracking_code_mode ∈ {customs_code, product_code}` and is **immutable** thereafter — rows stored under the original mode stay under that mode forever; switching modes mid-life requires re-onboarding under a new `dncx_id`.

This affects URL grammar: instead of hard-coding one column in the path, the API exposes mode-aware variants:
- `GET /v1/hub/materials/by-customs-code/{code}?dncx_id=X` (always available)
- `GET /v1/hub/materials/by-product-code/{code}?dncx_id=X` (always available)
- `GET /v1/hub/materials/by-key/{code}?dncx_id=X` — resolves via the DNCX's tracking_code_mode (consumer-friendly default)

Same pattern applies to BCCT and BOM where the join key matters.

## Endpoint catalog (MVP)

All endpoints versioned `/v1/...`, bearer-token-auth, JSON-only, cursor-paginated for lists.

### BCCT (3 endpoints)

| Method + path | Purpose | Notable params |
|---|---|---|
| `GET /v1/hub/bcct` | List BCCT for a DNCX/year | `dncx_id`, `year`, `direction?`, `declaration_no?`, `date_from?`, `date_to?`, `cursor?`, `limit?` |
| `GET /v1/hub/bcct/{transaction_key}` | Single BCCT row | `dncx_id` |
| `GET /v1/hub/bcct/by-invoice/{invoice_ref}` | All BCCT rows joined to an invoice | `dncx_id`, `year` |

### Danh Mục — material registry (5 endpoints)

| Method + path | Purpose |
|---|---|
| `GET /v1/hub/materials` | List materials, filterable by `category`, `status`, `cursor`, `limit` |
| `GET /v1/hub/materials/by-customs-code/{code}` | Lookup by customs_code |
| `GET /v1/hub/materials/by-product-code/{code}` | Lookup by product_code |
| `GET /v1/hub/materials/by-key/{code}` | Lookup using DNCX's tracking_code_mode |
| `GET /v1/hub/materials/by-key/{code}/history` | Per-material change history |

### BOM (4 read + 2 proposal endpoints)

| Method + path | Purpose |
|---|---|
| `GET /v1/hub/products/{product_code}/bom` | BOM for product, optionally pinned via `?version_id=V` |
| `GET /v1/hub/products/{product_code}/bom/latest` | Latest version with `intent ∈ {asserted_technical, staff_edit, derived}` (excludes `modified_for_case`) |
| `GET /v1/hub/products/{product_code}/bom/versions` | Version list, filterable by `actor`, `intent`, `cursor`, `limit` |
| `GET /v1/hub/bom/aggregate` | Full aggregate snapshot (`?aggregate_version_no=N` to pin) |
| `POST /v1/hub/products/{product_code}/bom/proposals` | CO submits a BOM-write proposal; auto-evaluated synchronously |
| `GET /v1/hub/proposals/{proposal_id}` | Fetch a specific proposal record (audit/debug) |

### DNCX directory (1 endpoint)

| Method + path | Purpose |
|---|---|
| `GET /v1/hub/dncxs` | List DNCXs visible to caller; response includes `tracking_code_mode` per entry |

**Total: 15 endpoints in MVP** (3 BCCT + 5 Materials + 6 BOM + 1 DNCX directory).

## BOM proposal workflow (auto-only mode, MVP)

CO submits proposal → Data Hub auto-evaluates → response is synchronous: either `{status: approved, version_id, version_no}` or `{status: rejected, decision_reason, failed_conditions: [...]}`.

**Auto-rule criteria** (proposal auto-approves *only if all hold*):
1. `parent_version_id` resolves to an existing version for the same `(dncx_id, product_code)`.
2. `context.case_id` references an active CO case in `co.co_cases` (Data Hub queries CO via API for this — defer to SSO/service-discovery pass).
3. Row-delta vs parent is within tolerance: only NVL substitutions allowed; per-row `qty_per_unit` may change by ≤ `bom_proposal_qty_tolerance_pct` (default 5.0, configurable in deployment settings).
4. All referenced material codes exist in `hub.materials` for this DNCX with `status='active'`.
5. The modification does not increase the number of distinct NVLs by more than 1 (anti-bloat).

If any condition fails → proposal is rejected synchronously with `failed_conditions` listing which. CO modifies and resubmits as a new proposal. Original rejected proposal stays in record.

**Configuration** (per-deployment, set by Tinsu AI at onboarding, toggleable by agency admin):
- `bom_proposal_mode`: `auto` (MVP only) | `manual` (phase 2) | `hybrid` (phase 2)
- `bom_proposal_qty_tolerance_pct`: numeric, default 5.0
- (Phase 2 will add notification settings, latency SLO, manual-mode-specific knobs.)

**Direct-write bypass for internal flows:** Agency staff Excel upload + agency staff manual edits go through Data Hub's internal Python API (in-process), not the proposal endpoint. They write `bom_versions` rows directly with `actor=agency_staff` and skip the proposal queue. Audit is captured in `bom_audit_events`. Rationale: agency staff acting in Data Hub UI *is* the hub — proposing to itself adds friction without value.

**Idempotency:** if a proposal with the same idempotency key already exists, return the existing record (whether approved or rejected) rather than creating a duplicate. See "Idempotency canonicalization" below.

## Response shapes

**List response:**
```json
{ "items": [ ... ], "next_cursor": "opaque-or-null", "total_estimate": 12345 }
```

**Single BCCT row:**
```json
{
  "dncx_id": "DNCX-001", "year": 2025, "transaction_key": "...",
  "direction": "import", "declaration_no": "...", "line_no": "...",
  "declaration_type": "...", "item_code": "...", "hs_code": "...",
  "quantity": 100.0, "unit": "kg", "currency": "USD", "total_value": 1500.0,
  "registration_date": "2025-03-15", "resolved_customs_code": "...",
  "bom_version_id": "...",
  "indexed_at": "2026-04-01T...Z"
}
```

`bom_version_id` is the point-of-use binding — the BOM version that backed this BCCT row at write time. BCQT settlement reads this; does not call `/bom/latest`.

**Material registry row:**
```json
{
  "dncx_id": "DNCX-001", "customs_code": "...", "product_code": "...",
  "name": "...", "category": "btp_sx", "category_override": null,
  "status": "active", "unit": "kg", "hs_code": "...",
  "version_no": 4, "updated_at": "..."
}
```

Both `customs_code` and `product_code` are returned when both exist — consumers pick which to display per their own logic.

**BOM (pinned):**
```json
{
  "dncx_id": "DNCX-001", "product_code": "...",
  "version_id": "...", "version_no": 7, "aggregate_version_no": 23,
  "actor": "co_system", "intent": "modified_for_case",
  "parent_version_id": "...",
  "context": { "case_id": "CO-2025-0142", "trigger": "rvc_threshold_pass", "channel": "co_api" },
  "status": "published",
  "tombstoned_at": null, "tombstone_reason": null,
  "published_at": "...", "composition_hash": "...",
  "rows": [ { "row_index": 0, "material_code": "...", "uom": "kg", "qty_per_unit": 0.5, "bom_code": "...", "bom_variant_id": null } ]
}
```

**Provenance is two axes** (per round-3 critic):
- `actor ∈ {agency_staff, co_system, erp_pipeline}` — *who wrote it*
- `intent ∈ {asserted_technical, derived, modified_for_case, staff_edit}` — *what kind of artifact it is*

`channel` (file vs form vs api) goes into `context` jsonb, not the type system. `parent_version_id IS NOT NULL` indicates a fork; null for root versions.

**Tombstoning** (round-3 fix): wrong versions get `tombstoned_at` + `tombstone_reason` set, are excluded from default reads (e.g., `/bom/latest` and `/bom/versions` filter them out by default; explicit `?include_tombstoned=true` to surface). No deletion; audit preserves the record.

**Proposal record:**
```json
{
  "proposal_id": "...", "dncx_id": "DNCX-001", "product_code": "...",
  "actor": "co_system", "intent": "modified_for_case",
  "parent_version_id": "...", "context": { "case_id": "CO-2025-0142", ... },
  "rows": [ ... ],
  "status": "approved",
  "decided_at": "...", "decided_by": "auto-rule",
  "decision_reason": "auto-approved",
  "failed_conditions": [],
  "materialized_version_id": "..."
}
```

## Cross-cutting concerns

- **Auth scopes** (entity-grained):
  - Reads: `hub:read:bcct`, `hub:read:materials`, `hub:read:bom`, `hub:read:dncxs`
  - Writes (proposal flow only): `hub:propose:bom` for CO. No `hub:write:*` scopes in MVP — direct-write internal flows are in-process and use no public scope.
  - Phase 2: `hub:approve:bom` (manual reviewer scope).
  - DNCX scoping is a separate token claim (`dncx=*` for trusted intra-deployment apps).
- **API versioning:** `/v1/...` from day 1; breaking changes go to `/v2/...`; N+1 deprecation rule.
- **Pagination:** cursor-based, opaque cursor, default limit 200, max 1000.
- **Freshness / caching:**
  - Versioned resources (specific `version_id`): immutable, `Cache-Control: public, max-age=31536000, immutable`.
  - "Latest" / "current" resources: `ETag` + `Cache-Control: public, max-age=60, must-revalidate`.
  - BCCT past-year lists: immutable after year-close (e.g., 2025 immutable from 2026-Q2 onwards).
  - BCCT current-year lists: short max-age (60s), ETag.
- **Errors:** RFC 7807 problem-details JSON. `type` URI dispatchable.
- **Idempotency canonicalization** for `POST /bom/proposals`:
  - Idempotency key = `(dncx_id, product_code, actor, intent, parent_version_id, normalized_hash)`.
  - **`parent_version_id` NULL handling:** use a generated stored column `parent_version_id_norm = COALESCE(parent_version_id, '00000000-0000-0000-0000-000000000000')` and put the UNIQUE on the normalized column (Postgres treats NULLs as distinct in standard UNIQUE — this fix avoids that footgun without depending on PG15+ `NULLS NOT DISTINCT`).
  - **`normalized_hash` canonicalization rule:** sort rows by `(material_code, bom_variant_id NULLS FIRST)`; round `qty_per_unit` to `DECIMAL(18,9)`; trim + UTF-8 NFC normalize all text fields; exclude `row_index` and any client-side metadata; SHA-256 over the canonical JSON byte string. Spec lives in code as `bom_canonicalize.py`.
  - **`composition_hash` vs `normalized_hash`:** consolidate. Drop CO's `composition_hash`; use `normalized_hash` everywhere (`bom_versions`, `bom_change_requests`, etc.).
- **FK invariants** (DDL, not application-level): `bom_versions.parent_version_id` REFERENCES `bom_versions.version_id` AND constraint that parent shares the same `(dncx_id, product_code)` (CHECK or trigger). `bom_change_requests.parent_version_id` same.

## Schema implications (round-trip with brief decisions)

| Brief decision | Read-API verdict | Action |
|---|---|---|
| 8-table BOM | **Keep + extend.** Version-pinning, `latest` query, proposal audit all rely on per-product version model. | Add `actor`, `intent`, `parent_version_id`, `context`, `tombstoned_at`, `tombstone_reason` to `bom_versions`. New table `bom_change_requests`. |
| 5-value Danh Mục enum (BCQT vocabulary) | **Adopt.** `?category=btp_sx` filter requires it. Layering line: BCQT's *settlement rules* stay in BCQT; *category vocabulary* is shared. | Schema design pass |
| `resolved_customs_code` + mapping ownership | **Mapping tables move to hub** *if* resolution is pure lookup. Open question still — verify before locking. | Open Q for next pass |
| Entity-shaped PKs | **Confirmed by URL design.** Mode-aware URL variants (`by-customs-code`, `by-product-code`, `by-key`) require both columns indexed; PKs `(dncx_id, customs_code)` and `(dncx_id, product_code)` separately. | Schema design pass |
| Read-and-rewrite framing | **Reinforced.** API JSON shape ≠ CO's payload-blob storage. Translation layer is mandatory. | Schema design pass |
| Tech stack lock | **Holds.** Response-shape-driven API + raw SQL row→dict mapping is FastAPI + Pydantic + psycopg's sweet spot. | n/a |
| Tracking-code-mode | **Per-DNCX, immutable, set at onboarding.** URL grammar exposes both code types + a `by-key` resolver. | Add `hub.dncxs.tracking_code_mode` column |
| Source provenance | **Two axes (`actor`, `intent`), not flat enum.** Channel goes to `context`. | Schema design pass |
| BCCT ↔ BOM linking | **Point-of-use binding.** BCCT row stores `bom_version_id` at write time. Settlement uses that, not "current." | Add `bcct_rows.bom_version_id` (nullable for rows where no product/BOM applies) |

## Open questions for next discovery pass

1. **Server-side joins for settlement?** Provide `GET /v1/hub/settlement-pull?dncx_id=X&year=Y` (BCCT joined with materials + BOM) or default to client-side join in BCQT? Default client-side; revisit if slow.
2. **Cross-year inventory carryover surface?** Separate endpoint vs. query param on `/bcct`?
3. **`co_stock_rows` future move:** named-trigger deferred (round-2 conceded).
4. **`resolved_customs_code` resolution path:** pure lookup or procedural? Determines whether mapping tables can move to hub cleanly.
5. **Auto-rule criterion #2 implementation:** "context.case_id references an active CO case" requires Data Hub to call CO. Direct DB query (CO has read role on its own data, hub has none) doesn't work; needs a CO API endpoint exposed back to hub. Defer to service-discovery design pass.
6. **`hub:propose:bom` token scope granularity:** per-deployment (one token writes for any DNCX) vs. per-DNCX (compromised CO only writes its own scope). MVP-acceptable as per-deployment; revisit phase 2.
7. **BCCT `bom_version_id` resolution rule:** for BCCT rows from Excel upload (no per-shipment context), how is `bom_version_id` chosen? Latest at upload time? Or null until a CO certificate references it?

## Next step

Per-entity schema design pass — turns this contract into SQL-ready DDL for `hub.bcct_rows`, `hub.materials_*`, `hub.bom_*`, `hub.bom_change_requests`, `hub.dncxs`. Resolves open questions #4 and #7 first; the rest can lag.

## Files referenced

- `.ai/features/2026-04-30-data-hub-mvp.md` — discovery brief (with two Amendments sub-sections)
- `.ai/DECISIONS.md` — local decisions log
- `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM — Data Hub 3-app architecture" (with 2026-05-01 amendment block)
