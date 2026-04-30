# Feature: Data Hub MVP — M9 discovery brief

**Date:** 2026-04-30 (amended 2026-05-01)
**Author:** discovery sprint deliverable #1 (CO schema audit) + stubbed scope for #2–#6
**Status:** in-progress (audit done; v2 rewrite pending — see Amendments)

## Amendments

### 2026-05-01 — BCCT single writer for MVP (BCCT-scoped only)

CO no longer writes **BCCT** into `hub` for MVP scope. All `hub.bcct_rows` writes flow only from Data Hub (agency-staff Excel upload through Data Hub's UI). CO is a pure read consumer of hub *for BCCT and Danh Mục*. Time-scoped (phase-2 may revisit). Full rationale in `.ai/DECISIONS.md` "2026-05-01 BCCT single writer for MVP".

**Brief sections this collapses or simplifies (BCCT-scoped):**
- **Decision #6 (write conflict reconciliation) for BCCT** — *not needed in MVP*. Single write path, no precedence/race question for BCCT.
- **Risk: `client_id` rename as cross-app blocker** — narrower; still relevant for Data Hub's internal multi-DNCX model and at the BOM write boundary (see below), but no longer at the BCCT write seam.

### 2026-05-01 (evening) — BOM writes via auto-only proposal queue

CO does NOT directly write BOM versions. CO submits **proposals** to a write queue; Data Hub auto-evaluates and either approves (materializing a new immutable `bom_versions` row) or rejects (CO modifies + resubmits). MVP runs **auto-only**; manual + hybrid review modes deferred to phase 2. Per-deployment config (`bom_proposal_mode`).

Full design: `.ai/features/2026-05-01-data-hub-read-api.md` (v2). Decision rationale: `.ai/DECISIONS.md` "2026-05-01 (evening) BOM writes via auto-only proposal queue".

**Key model adjustments folded in (round-3 critic + user decisions):**
- **Provenance is two axes**, not a flat enum: `actor ∈ {agency_staff, co_system, erp_pipeline}` × `intent ∈ {asserted_technical, derived, modified_for_case, staff_edit}`.
- **No "current version" stored state.** `latest` is a query endpoint computed at read time (excludes `modified_for_case`). BCQT settlement uses **point-of-use binding** — each BCCT row stores `bom_version_id` at write time; settlement reads what was bound, not what's "latest."
- **Tracking-code mode** is per-DNCX, immutable, set at onboarding. URL grammar exposes mode-aware variants.
- **Idempotency canonicalization** spec'd: hash sort order + decimal scale + UTF-8 NFC; nullable `parent_version_id` handled via generated coalesce column (avoids Postgres `NULL ≠ NULL` UNIQUE footgun).
- **Tombstoning** replaces deletion: `tombstoned_at` + `tombstone_reason` columns; tombstoned versions stay readable for audit, excluded from default reads.

**M9 deliverable #5 (service-to-service auth):** CO needs `hub:propose:bom` (not `hub:write:bom`). Phase-2 manual mode adds `hub:approve:bom`. Internal direct-write flows (agency Excel upload, staff edit) bypass the proposal queue — same trust boundary as Data Hub itself.

**Round-3 verdict resolved:** "BOM model is thrashing" — answered by the proposal pattern + axis split + point-of-use binding. **Round-3 sticky points still on the docket** for the per-entity schema design pass: server-side joins for settlement (open Q #1), `resolved_customs_code` resolution path (open Q #4), service-discovery for the auto-rule's "active CO case" check (open Q #5).

Other round-2 conceded points (entity-shaped PKs, read-and-rewrite framing, API versioning, tech-stack debate) are now reflected in the read-API v2 doc; brief itself still pending a v2 body rewrite.

## Scope

**In:** Audit CO's existing Postgres schema (BCCT, Danh Mục, BOM) as the canonical seed for Data Hub's `hub` schema. Diff against BCQT's current per-project SQLite. Decide entity-by-entity which side is canonical. Stub remaining M9 deliverables (storage, SSO, service-to-service auth, deployment shape) for follow-up discovery passes.

**Explicitly out:** Implementation. SSO design beyond high-level stub. CO migration plan (deferred to a CO-side session — audit-only here). File-snapshot tier (phase 2). Multi-tenant SaaS shape (locked at 1 agency = 1 deployment).

## Tech stack — locked by audit

Both CO and BCQT-System converge on the same stack. Data Hub inherits this with no debate:

- **Python 3.12+**
- **FastAPI 0.115+** + **Jinja2** + HTMX
- **Postgres** via **psycopg 3** (binary) — *(BCQT uses sqlite3, but Data Hub is Postgres)*
- **No ORM.** Raw parameterized SQL.
- **Migrations:** numbered `.sql` files in `db/migrations/` + custom runner that tracks applied migrations in a `schema_migrations` table. No Alembic.
- **DB init:** `apply_migrations()` on app startup, env var `DATA_HUB_DATABASE_URL` (rename from CO's `BARRY_DATABASE_URL`).

The "ORM TBD / migration tool TBD" lines in CLAUDE.md / STATUS.md can be removed.

## CO schema — what exists today

Source: `~/workspace/client/barry-CO-main/db/migrations/{001..005}.sql` + stores in `app/`.

**BCCT (3 tables):** `bcct_rows` (PK = client_id + transaction_key, indexed by direction/declaration_no/item_code), `bcct_invoice_index` (M:N invoice ↔ transaction), `co_stock_rows` (per-shipment inventory + eligibility tracking).

**Danh Mục (3 tables, polymorphic):** `source_catalog_rows` (PK = client_id + module + row_key, `module ∈ {material_catalog, product_catalog}`); `source_index_metadata` (denormalized counters per client+module); `source_correction_candidates`. Backed by full versioning infra: `source_uploads`, `source_snapshots`, `source_snapshot_rows`, `source_versions`, `source_version_rows`, `source_audit_events`.

**BOM (8 tables, advanced versioning):** `bom_states`, `bom_uploads`, `bom_snapshots`, `bom_snapshot_rows`, `bom_product_versions` (per-product version_no), `bom_product_version_rows`, `bom_versions` (aggregate version composing all products), `bom_version_rows`, `bom_audit_events`. Composition tracked via `composition_hash` + `product_versions` JSONB array.

**Cross-cutting design choices in CO:**
- Every table has a `payload` JSONB column holding the full row; indexed columns are denormalized copies for fast lookup.
- No soft deletes — versions are immutable, history retained in version tables.
- Mostly no FK constraints (intentional — supports in-flight unpublished data).
- Audit events are dedicated tables, not row columns.
- Uploads carry `storage_backend` + `stored_path` — already an embryonic file-backend abstraction.

## BCQT schema — what exists today

Source: `~/workspace/client/BCQT-System/migrations/project/`.

**BCCT:** `customs_declarations` in per-project SQLite. Flat columns (no JSONB), INTEGER PK + `file_id` FK. UNIQUE(file_id, row_number). DNCX/year scoping is **implicit** — each project.db represents one (DNCX, year), with the (client_id, year) recorded in `app.db.projects`.

**Danh Mục:** Two-table polymorphic — `declared_materials` (`material_type ∈ {nvl, tp}`) for raw uploads; `material_registry` (`category ∈ {nvl, btp_sx, btp_nm, tp, ccdc}`) for canonical merged registry. Has `category_override`, `inherited_from_project_id` for carry-over, `status ∈ {active, discontinued}`.

**BOM:** Not implemented yet. Awaiting Data Hub.

## Decisions

1. **Tech stack: locked** (see above). Removes the `ORM TBD / migration tool TBD` placeholders.

2. **Canonical schema per entity:**
   - **BOM → adopt CO as-is.** CO's 8-table versioned model is the most mature artifact in either repo. Data Hub takes it verbatim. Naming sticks (`bom_versions`, `bom_product_versions`, etc.).
   - **Danh Mục → CO's *infrastructure*, BCQT's *domain model*.** Keep CO's `source_uploads`/`source_versions`/`source_snapshots` versioning skeleton, but expand the category enum from CO's 2 values (`material_catalog`, `product_catalog`) to BCQT's 5 values (`nvl`, `btp_sx`, `btp_nm`, `tp`, `ccdc`). CO's domain model is too coarse for BCQT's settlement rules; widening Data Hub to BCQT's vocabulary now is cheaper than narrowing later.
   - **BCCT → CO's table shape, BCQT's column richness.** CO's `bcct_rows` (composite PK, indexed denormalized columns + JSONB payload) is the right scaffold. BCQT's `customs_declarations` has more typed columns BCQT needs (quantity_2/unit_2, currency, registration_date, resolved_customs_code) — promote those out of payload into typed columns so consumers don't have to JSONB-extract on every read.

3. **Tenant scoping → DNCX is a first-class column, not a deployment partition.** This is the biggest divergence from CO. CO is single-DNCX-per-deployment (its `client_id` IS the agency-customer ≈ one DNCX). Data Hub is single-agency-per-deployment but **multi-DNCX inside the deployment** — one agency runs 10–20 DNCX. Every `hub.*` table needs a `dncx_id` (or `dncx_code`) column as part of the composite key. Year scoping per-row is also needed (BCCT/Danh Mục both vary year-over-year). Proposed PK pattern: `(dncx_id, year, <entity-key>)`.

4. **FK constraints → adopt for shared schema.** CO's "no FKs for in-flight flexibility" is a CO-internal call. Data Hub is read by BCQT and CO; consumers need referential integrity. Add FKs at table boundaries (e.g., `bcct_rows.dncx_id → dncxs.id`).

5. **File storage abstraction → extract from CO's `storage_backend`/`stored_path` pattern.** CO already records backend per upload. Data Hub formalizes a `FileBackend` interface (`put(key, bytes) -> stored_path`, `get(stored_path) -> bytes`, `delete(stored_path)`). LocalFS day 1; S3-compat in phase 2. (Detailed design = follow-up discovery pass.)

## Risks

1. **JSONB ↔ typed column drift.** CO's "everything in payload, indexed columns are denormalized copies" is fast to evolve but creates two sources of truth per field. If a consumer reads from indexed columns and the payload disagrees, who wins? Data Hub should pick one read path (typed columns) and treat payload as audit-only / debug.

2. **Schema rename pain.** CO uses `client_id` to mean "agency-customer of CO". In Data Hub, that semantic role splits into `agency_id` (always the deployment owner) and `dncx_id` (per-row scope). Cross-repo grep for `client_id` will hit hundreds of CO call sites — renaming is a CO-side migration, not a Data Hub-side concern, but it means CO's eventual write-via-API client must translate.

3. **BOM 8-table complexity for an MVP.** CO's BOM versioning (per-product + aggregate, snapshot/version separation, audit events) is impressive but is also ~30% of the table count and a lot of code. Adopting wholesale extends MVP timeline. Worth asking: does Data Hub MVP need full per-product versioning on day 1, or is aggregate-level versioning sufficient for the first cut?

4. **No CO migration files = no canonical schema doc.** Audit was reconstructed from `db/migrations/*.sql` in CO (which DO exist — earlier docs were wrong about this). 5 migrations, 001–005. Future Data Hub migrations should follow the same numbering scheme so a future BCQT/CO/Hub three-way compare stays sane.

5. **CO uses `BARRY_*` env var prefix.** Data Hub will use `DATA_HUB_*`. CO migration to consumer mode will need env var aliasing or a flag day. Not a Data Hub concern, but flag for cross-repo coordination.

## Open Questions

1. **DNCX identifier:** UUID, ULID, or a customer-meaningful code (tax code? client-facing slug)? Affects all PK design.

2. **Versioning depth for Danh Mục/BCCT:** CO's "every upload = a new version, full history retained" is heavy for BCCT (a year's worth of declarations is tens of thousands of rows × N uploads × full retention). Is row-level history needed or just upload-level?

3. **JSONB payload column — keep or drop in Data Hub?** Tradeoff: keeps CO codebase porting cheap (just rename + re-key) vs. forces typed-column-only purity.

4. **BCQT migration sequencing:** when Data Hub is up, BCQT still has `customs_declarations` and `material_registry` in per-project SQLite. Does BCQT keep those as a read-through cache, or fully delete them and read from Data Hub on every query? (Latency vs. simplicity.)

5. **CO's `co_stock_rows`:** is this Data Hub-owned (since it tracks BCCT-derived stock for CO eligibility) or CO-owned (CO-internal computed state)? My read: CO-internal. Stays in `co` schema, doesn't move to `hub`.

6. **Auth bootstrap:** seed admin user for the auth center — agency-side admin or Tinsu AI staff admin? (deferred to SSO discovery pass)

## Stubbed deliverables (follow-up discovery passes)

- **#3 Storage abstraction:** Skeleton outlined above (FileBackend interface, LocalFS day 1). Full design = own discovery doc.
- **#4 SSO:** Internal auth center hosted in Data Hub, not Keycloak/Authentik. Need to decide: shared cookie domain vs. JWT bearer; session table vs. stateless; role model (agency-admin / agency-staff / Tinsu-developer). Own discovery doc.
- **#5 Service-to-service auth:** CO → Data Hub write API for per-shipment BCCT. Token-based service account, scoped (e.g. `co.bcct.write`). Probably bearer token in Authorization header, signed JWT or opaque DB-backed token. Own discovery doc.
- **#6 Deployment shape:** 1 VPS, Postgres + 3 systemd units (hub/bcqt/co), shared file volume, Litestream (BCQT per-project SQLite) + pg_dump pipeline, reverse proxy in front. Own discovery doc.

## Done criteria for this brief

- [x] CO Postgres schema documented (every table, column, key, index)
- [x] BCQT current schema documented for these 3 entities
- [x] Tech stack locked (Python 3.12 + FastAPI + psycopg 3 + raw SQL migrations)
- [x] Per-entity canonical-source decision made (BOM/Danh Mục/BCCT)
- [x] Major risks surfaced
- [ ] User signs off on the 5 decisions above (especially #2 and #3)
- [ ] DNCX identifier choice resolved (open question #1)
- [ ] Stubbed deliverables #3–#6 expanded into their own briefs

## Manual test plan (when implementation starts)

Not applicable yet — this is a design audit. Next implementation phase will produce its own test plan.

## Next step

Get user sign-off on the 5 decisions and resolve open question #1 (DNCX identifier). Then either:
- Run a follow-up `/discover` pass for deliverable #3 (FileBackend), since it has lighter dependencies than SSO/auth, OR
- Start scaffolding the Data Hub Python project from the locked tech stack and write the first migration (`001_dncxs_and_agencies.sql`).
