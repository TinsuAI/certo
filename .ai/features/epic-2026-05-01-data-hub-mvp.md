# Epic: Data Hub MVP — first shippable build

**Date:** 2026-05-01 (autopilot session)
**Status:** in-progress
**Scope:** Replicate the agency-master-records subset of barry-CO-main as a standalone Data Hub product, plus SSO, plus the BOM proposal-queue pattern designed earlier today.

## In scope (MVP)

- **Auth & SSO**: simple session-based login, agency-staff role, seed admin. No multi-agency federation in MVP (1 agency = 1 deployment).
- **DNCX management**: list, create, configure (`code_resolution_mode`, `bom_proposal_mode` settings).
- **Materials** (Danh Mục NVL/SP/BTP): list, view, Excel upload, version history. Five-value `category` enum.
- **Code mappings**: list per DNCX, manual entry/edit, Excel upload of BQD-style sheets, N-N support.
- **BCCT** (customs declarations): list, view, Excel upload. Goods-name parser pluggable per DNCX (Growatt regex inherited).
- **BOM**: 8-table model from CO (versions, snapshots, uploads, audit events) with the two-axis (`actor`, `intent`) provenance + tombstoning. Multi-source upload (technical / agency_upload variants of CO's `manual_flat`, `growatt_multi_workbook`, `johnson_sap_exploded` profiles).
- **BOM proposal queue**: auto-rule pipeline gated on the 5-condition gate. CO acts as the proposing client (mocked in MVP — no real CO integration yet).
- **File storage**: `FileBackend` interface, LocalFS implementation. S3-compat scaffold deferred but interface ready.
- **Read API**: 13-15 endpoints per the read-API design doc.

## Out of scope (deferred / future)

- CO-System dossier workflow (origin certificate authoring).
- Actual cross-app SSO (this is in-app auth only — federated SSO when CO/BCQT come online).
- Manual BOM proposal review queue (auto-only per today's decision).
- Service-discovery to CO for case validation (auto-rule criterion #2 dropped).
- Mẫu 15/15a/16 generation (BCQT's job).
- Per-shipment CO certificate state.
- Full barry-CO-main UX parity for niche flows (CO cases, evidence workbook generation, etc.).

## Tech stack

Inherited from barry-CO-main (per round-2 lock):
- Python 3.12+, FastAPI, Jinja2 + HTMX, openpyxl, psycopg 3, uv, raw-SQL migrations.
- Postgres `data_hub` database. App schema `hub`. Role-per-app deferred (single-role MVP).
- LocalFS for file storage. S3-compat interface designed but not implemented.

## Sequencing (waves)

Each wave is commit-able; if budget runs out mid-wave, prior waves are intact.

**Wave 1 — Foundation** (highest priority)
- Project scaffold (pyproject.toml, app/, db/migrations/, tests/, static/, templates/).
- Database setup (`data_hub` PG database, `hub` schema, migrations runner ported from CO).
- Migrations 001–004: dncxs, materials, code_mappings, code_mapping_resolutions.
- Base FastAPI app: lifespan that runs migrations, /healthz endpoint.
- Base template + CSS (port from CO with rebrand).
- Commit.

**Wave 2 — Auth + DNCX**
- Migration 005: users, sessions.
- Auth helpers: password hash (argon2 or bcrypt), session cookie issuer, login form, logout.
- Seed admin user (env-var-driven password).
- DNCX list page + create form + edit form.
- Commit.

**Wave 3 — Materials + Code Mappings**
- Migrations 006–008: source_uploads, source_versions, source_snapshots, source_snapshot_rows, source_module_state.
- Materials Excel upload (port `parse_input_workbook` from CO's `workbook_io.py`, adapt).
- Materials list + filter UI.
- Code mappings list/create/upload UI.
- Commit.

**Wave 4 — BCCT**
- Migration 009: bcct_rows + bcct_invoice_index.
- BCCT Excel upload + Growatt parser (port `_parse_ma_nb` regex from `bcqt-growatt/settlement/load.py`).
- BCCT list + filter UI.
- Code mapping resolutions table + Growatt batch resolver.
- Commit.

**Wave 5 — BOM (largest)**
- Migrations 010–012: bom_versions, bom_uploads, bom_snapshots, bom_snapshot_rows, bom_product_versions, bom_product_version_rows, bom_audit_events, bom_change_requests.
- BOM upload + parser (port from `bom_store.py` + handlers for the 3 profiles).
- BOM versions list + version detail view.
- BOM upload UI.
- Proposal queue: POST /v1/hub/products/{p}/bom/proposals with the 5-condition auto-rule.
- Commit.

**Wave 6 — Read API + polish**
- Read API endpoints (covering all entities, JSON responses).
- Tests: parser TDD, API contract tests, basic UI smoke tests.
- Playwright smoke tests + screenshots if budget permits.
- /healthz, /readyz, /metrics stub.
- Commit.

**Wave 7 — Storage + S3 scaffold + final polish**
- `FileBackend` interface + `LocalFSBackend` implementation.
- Wire BOM/Materials/BCCT uploads to use it.
- S3-compat backend stub (interface implemented but not configured).
- Final UI pass.
- Commit.

## Done criteria

- `uv run python -m app` starts the dev server on a free port.
- Visiting `/` redirects to `/login`; admin can sign in with seeded creds.
- Logged-in admin can:
  - Create a DNCX, set `code_resolution_mode`.
  - Upload Materials Excel for that DNCX, see them in the list.
  - Upload Code Mappings Excel for that DNCX.
  - Upload BCCT Excel for that DNCX, see internal codes parsed.
  - Upload a Technical BOM Excel for a product, see version published.
  - Submit a BOM proposal via API (curl), see auto-rule decision.
- All read-API endpoints respond with documented JSON shapes.
- pytest passes locally.

## Reference files in barry-CO-main

- `app/main.py` (924 lines) — route patterns
- `app/database.py` — migration runner (port verbatim, rename env var)
- `app/workbook_io.py` (319 lines) — Excel parse/build helpers
- `app/source_index_store.py` (1332 lines) — source upload + versioning
- `app/source_postgres_store.py` (228 lines) — Postgres-specific store
- `app/bom_store.py` (~1500 lines) — BOM upload + versioning + diff
- `app/templates/base.html`, `bcct.html`, `bom.html`, `catalog.html`, `clients.html` — UI mockup
- `app/static/css/app.css` — design system

## Reference files in bcqt-growatt

- `settlement/code_map.py` — N-N mapping engine, BCCT-aggregate resolution
- `settlement/load.py` — `_parse_ma_nb` regex for goods-name internal-code extraction
