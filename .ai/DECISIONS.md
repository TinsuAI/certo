# Architecture Decisions

<!-- Format:
## [Date] Decision Title
**Context:** Why this decision was needed
**Decision:** What was decided
**Alternatives:** What else was considered
**Consequences:** What this means going forward
-->

## Canonical decision pointer

Until Data Hub has its own discovery sprint output, the architectural decisions for this product live in the sister repo:

**`~/workspace/client/BCQT-System/.ai/DECISIONS.md` → "2026-04-30 PM — Data Hub 3-app architecture"**

That entry covers:
- Three Tinsu AI products (Data Hub + BCQT + CO).
- 3-app architecture, hybrid Postgres + per-project SQLite, strict app-data ownership.
- SSO via internal auth center in Data Hub.
- Code seed from CO (`barry-CO-main`).
- BCQT reframed as Data Hub consumer.
- Three deployment shapes per agency.
- M9 umbrella milestone covering 3-app extraction + hybrid engine migration + deployment + SSO.
- Naming caveat: "Data Hub" is provisional.

## 2026-05-07 BOM vocab rename — version → artifact, profile → preset

**Context:** GLOSSARY locked the canonical 4-tier ontology
(phiên bản logical / bản lưu storage / preset / shape × strategy)
on 2026-05-07. DB schema + 464 code refs across 52 files lagged the
vocab — `bom_versions`, `version_id`, `bom_resolution_profiles`,
`profile_id` everywhere. Phase 3 was about to land a resolver +
preset CRUD on top of the impoverished names; cheaper to rename
before, when sister apps are not yet wired.

**Decision:** Atomic rename pass landed before Phase 3a, scoped per
brief `.ai/features/2026-05-07-bom-vocab-rename/brief.md`.

- Migration 031 renames 3 tables + 9 column-renames spanning 7
  tables. PostgreSQL ALTER TABLE/COLUMN RENAME is metadata-only;
  carries FK constraints + generated-column expressions over.
- Code grep-replace pass on 44 .py + .html files. Function names
  (`list_versions_for_product` → `list_artifacts_for_product`,
  `get_lineage_for_version` → `get_lineage_for_artifact`, etc.)
  + URL paths (`/bom/version/` → `/bom/artifact/`,
  `/bom/.../versions` → `/bom/.../artifacts`) + template files
  (`bom_versions.html` → `bom_artifacts.html`).
- ID prefix forward-only: `bv_*` rows survive untouched, new rows
  minted with `ba_*` prefix. CO's stored references to `bv_*` IDs
  remain valid.
- One-release alias grace: old URLs return `308 Permanent Redirect`
  (preserves POST method) to new URLs. Removal milestone tracked in
  BACKLOG.md "Drop BOM vocab v1 aliases".

**Alternatives:**
- Squash migrations 005-030 into a single "phase-2 baseline" using
  new vocab from the start. Rejected — rewrites history, loses
  schema-decision provenance for one-time mental-translation cost.
- Backfill all `bv_*` IDs to `ba_*`. Rejected — breaks persisted
  external references in CO + BCQT, no semantic gain.
- Implicit "default preset" to mask alias removal. Rejected per
  Phase 3 brief R1 — masks the explicit choice consumers must make.

**Consequences:**
- All future BOM/preset code uses canonical vocab. Phase 3a starts
  with clean vocabulary in store, route, template, test layers.
- Sister-app coordination: CO needs migration before alias removal
  (see `~/workspace/client/barry-CO-main/.ai/sister-app-notes/2026-05-07-bom-rename.md`).
  BCQT has 0 refs but note posted for awareness.
- Past migrations 005-030 use old names — readers translate
  mentally. Mig 031 header explains. New devs spinning up against
  fresh DB get final renamed schema; mig replay is forward-correct.

---

## 2026-04-30 Project scaffold

**Context:** New product spun out from architectural decision in sister repo BCQT-System, made same day. Need a home for code + AI context before M9 discovery sprint.

**Decision:** Initial scaffold via `git init` + `ai-init --type app` + custom AGENTS.md preserving cross-repo context.

**Alternatives:** Could have folded into BCQT-System or barry-CO-main as a sub-package, but the architecture decision (3 separate apps, strict ownership) requires distinct repo.

**Consequences:**
- Sister repo references will appear in commits + AGENTS.md + STATUS.md until Data Hub develops its own decision base.
- Tech stack picks deferred to M9 discovery sprint (audit CO first, match its stack).

---

## 2026-05-01 BCCT single writer for MVP

**Context:** The 2026-04-30 PM canonical architecture decision has CO writing per-shipment BCCT into `hub` schema via Data Hub's API. That introduces concurrent-write reconciliation between CO's per-shipment writes and the agency's annual BCCT Excel upload (surfaced as Decision #6 gap in the discovery brief and the round-2 critic exchange). Questioning the value of the CO write-back path in MVP: BCQT settlement runs annually after the year-end VNACCS Excel export, so in-year CO writes wouldn't be consumed by BCQT; the annual Excel is canonical and would supersede CO writes anyway.

**Decision:** *Trước mắt* (for the time being / MVP scope), **BCCT is written into `hub.bcct_rows` only from Data Hub** — i.e., only via agency-staff Excel upload through Data Hub's UI. CO does not write BCCT to hub. CO continues to maintain its own per-shipment BCCT-equivalent state in the `co` schema for its own working purposes; CO reads from `hub.bcct_rows` for cross-shipment / cross-year queries.

This is **time-scoped, not permanent**. Phase 2 may revisit if a real driver appears: BCQT in-year preview settlements, CO producing richer-than-VNACCS fields worth preserving, or VNACCS export proving unreliable.

**Alternatives considered:**
- Keep CO write-back path (canonical 2026-04-30 PM design): rejected for MVP — pays Decision #6 reconciliation cost, service-to-service auth complexity, write-API contract churn, all for a consumer (BCQT) that doesn't read in-year data.
- Drop CO write path permanently: rejected — over-commits. The above triggers may legitimately bring it back later.

**Consequences:**
- BCCT now has **one** canonical write path: agency Excel upload → Data Hub UI → `hub.bcct_rows`. Single writer for BCCT, no reconciliation question.
- Decision #6 (write conflict / source-of-truth precedence) **for BCCT** evaporates from MVP scope.
- M9 deliverable #5 (service-to-service auth) narrows but does not evaporate. **BOM remains CO-writable in MVP** — CO modifies BOM versions for origin-certificate dossiers (e.g., swapping NVL composition to meet RVC thresholds) and writes them back as `source=co_modified` immutable versions with `parent_artifact_id` lineage. Auth scopes needed: `hub:read:bcct`, `hub:read:materials`, `hub:read:bom` for BCQT and CO; plus `hub:write:bom` for CO. No `hub:write:bcct` for CO in MVP.
- CO migration becomes "add hub read-client (BCCT, Danh Mục, BOM) + add BOM write-client (modified-version submission)" — narrower than the original full write-API rewrite, but not pure read-only.
- The `client_id` → `agency_id`/`dncx_id` semantic split still matters for Data Hub's internal multi-DNCX model **and** at the BOM write boundary (CO submitting a modified version must identify the DNCX correctly).
- Cross-repo coordination: amendment block added to `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM" entry on 2026-05-01.

**Clarification (2026-05-01 evening):** This amendment is **BCCT-scoped only**. CO is a pure read consumer of hub *for BCCT and Danh Mục*; for **BOM**, CO reads versions and writes new modified versions back. The original 2026-04-30 PM ownership rule "CO has no write access to hub schema" still holds at the **schema/DB level** (CO has no Postgres role on `hub`), but the API surface includes a BOM POST endpoint for CO. BOM versions are append-only and tagged with `source ∈ {technical, co_modified, erp_derived, staff_edit, agency_upload}` for provenance. See `.ai/features/2026-05-01-data-hub-read-api.md` for the read-API + BOM-write-back design.

---

## 2026-05-01 (evening) BOM writes via auto-only proposal queue

**Context:** The 2026-05-01 BCCT-amendment narrowed CO from a "writes BCCT to hub" model to "reads BCCT, but still writes BOM modifications back." That left an open question: how does CO write BOM? The naive answer (direct `POST /v1/hub/products/{p}/bom`) makes CO an authoritative writer of canonical hub data, which violates the "Data Hub owns canonical data, consumers cannot directly write" stance. Round-3 critic flagged the BOM provenance model as conflated and the canonicalization story as incoherent.

**Decision:** **CO submits BOM modifications as proposals** (not direct writes). Data Hub gates every external BOM write through an auto-evaluator. MVP runs **auto-only**:

- New endpoint: `POST /v1/hub/products/{product_code}/bom/proposals`. Synchronous response: `{status: approved, artifact_id, artifact_no}` or `{status: rejected, decision_reason, failed_conditions}`.
- New schema table: `hub.bom_change_requests` — durable record of every proposal (approved or rejected), with full audit lineage.
- **Auto-rule** (proposal approves only if all hold):
  1. `parent_artifact_id` resolves to an existing version for same `(dncx_id, product_code)`.
  2. `context.case_id` references an active CO case.
  3. Row-delta vs parent within tolerance (NVL substitutions only; per-row `qty_per_unit` change ≤ `bom_proposal_qty_tolerance_pct`, default 5.0).
  4. All material codes referenced exist in `hub.materials` for this DNCX with `status='active'`.
  5. NVL count growth ≤ 1 (anti-bloat).
- **Reject-and-resubmit** model: failed proposals stay in record; CO modifies and submits a new proposal. No reviewer-amendment, no counter-proposal-supersedes.
- **Configuration:** per-deployment (one setting for the whole agency); `bom_proposal_mode ∈ {auto, manual, hybrid}` with only `auto` implemented in MVP. Tinsu AI sets at onboarding; agency admin can toggle.
- **Direct-write bypass:** agency-staff Excel upload + manual edits in Data Hub UI go through Data Hub's internal Python API (in-process), not the proposal endpoint. Trust boundary: agency staff *is* the hub.

**Phase 2 additions** (deferred):
- Manual mode: notification system (email + in-app), latency SLO (target 4 business hours), review queue endpoints (`GET /v1/hub/proposals?status=pending`, `:approve`, `:reject`, `:withdraw`).
- Hybrid mode: auto for trivial cases, flag non-trivial for manual review.

**Alternatives considered:**
- Direct write (CO has `hub:write:bom` token, posts straight to `bom_artifacts`): rejected — violates canonical-data ownership; no gating against malformed/malicious writes.
- Reviewer-amends-in-place: rejected — breaks audit integrity (record of "what CO actually proposed" lost).
- Hub-counter-proposal-supersedes: considered (preserves audit, no mutability creep) but rejected for MVP — adds workflow complexity that auto-only doesn't need.

**Consequences:**
- **Round-3 critic's "BOM model is thrashing" concern resolves.** "What does CO writing to hub mean?" has a clean answer: CO proposes, hub decides.
- M9 deliverable #5 (service-to-service auth): CO needs `hub:propose:bom` (not `hub:write:bom`). Phase 2 adds `hub:approve:bom` for manual reviewers. Direct-write internal flows use no public scope.
- **Auto-rule criterion #2** ("context.case_id is an active CO case") forces a service-discovery dimension: Data Hub queries CO via API to validate. This couples Data Hub to CO at runtime — Data Hub can't process BOM proposals if CO is down. Defer hardening to service-discovery design pass.
- **Schema additions** (folded into `.ai/features/2026-05-01-data-hub-read-api.md`):
  - `hub.bom_artifacts`: `actor`, `intent`, `parent_artifact_id`, `context` jsonb, `tombstoned_at`, `tombstone_reason`, `normalized_hash` (replaces `composition_hash`).
  - `hub.bom_change_requests`: full proposal record table.
  - `hub.bcct_rows.artifact_id`: point-of-use binding (per round-3 critic) — BCQT settlement reads what was bound at transaction time, not "current."
- **Provenance is two axes**, not a flat enum: `actor ∈ {agency_staff, co_system, erp_pipeline}` × `intent ∈ {asserted_technical, derived, modified_for_case, staff_edit}`. Channel (file/form/api) goes to `context`.
- **"Latest BOM" is a query**, not stored state: `GET /v1/hub/products/{p}/bom/latest` returns most recent published version with `intent ∈ {asserted_technical, staff_edit, derived}` (excludes `modified_for_case`). No `is_current` column.
- **Tracking-code mode is per-DNCX, immutable, set at onboarding** — affects URL grammar (mode-aware variants `/by-customs-code/{c}`, `/by-product-code/{c}`, `/by-key/{c}`). DNCX switching modes mid-life requires re-onboarding under new `dncx_id`.

---

## 2026-05-02 Settlement code resolver moved out of hub

**Context:** Hub hosted `app/stores/code_resolution.py` — a canonical-pick resolver materializing `hub.code_mapping_resolutions` and a denormalized `bcct_rows.resolved_customs_code` column. Code comments explicitly stated the algorithm was ported from `bcqt-growatt/settlement/code_map.py`. Independent critic review (`.ai/features/2026-05-02-rip-resolver-from-hub.md` for the brief) surfaced three issues:

1. **BCQT-flavor leaks into hub schema.** `bcct_qty_pick` strategy + `direction='import'` filter + 5-enum `resolution_basis` CHECK constraint are all settlement-side rollup concepts. Hub is master-data app — should not encode consumer-specific views.
2. **Lossy port.** Original Growatt algorithm distinguishes NVL (E11/E15/E13 import qty) vs TP (E42 export qty). Hub's port collapses to `direction='import'` for everything → resolved_customs_code stored for TP rows is *wrong today*.
3. **Window cost.** Read API has zero real consumers (CO not migrated, BCQT not migrated). Cost of removal = 0 right now, grows weekly.

**Decision:** **Option B-lite** — drop the materialization from hub; move algorithm to a CLI script. Specifically:

- Drop `hub.code_mapping_resolutions` table.
- Drop `hub.bcct_rows.resolved_customs_code` column + `idx_bcct_resolved` index. Migration `009_rip_resolver.sql`.
- Move `app/stores/code_resolution.py` → `scripts/settlement_resolver.py` (CLI, NOT imported by `app/`). Reads hub raw data as a consumer would. Writes nothing to hub.
- Remove API endpoint `/v1/hub/code-mappings/resolutions`. Remove `resolved_customs_code` field from `/v1/hub/bcct/*` responses.
- Remove BQD page resolutions panel + manual "Resolve" button.
- Drop `tests/test_code_resolution.py` (5 tests). Equivalent tests get rebuilt in BCQT when it migrates and adopts/fixes the algorithm.

**Alternatives considered:**
- **Option A (rename + DECISIONS entry, keep in hub):** rejected. Critic point 2 — hub stores wrong canonical data for TP today. Renaming doesn't fix data integrity. Tech debt entry doesn't undo coupling.
- **Full Option B (move to BCQT-System repo):** rejected for now. BCQT hasn't migrated to consumer mode yet. Putting it in `data-hub/scripts/` keeps the algorithm reachable for current demo/dev needs while signaling it's destined for BCQT. When BCQT migrates, this script gets ported there + fixed for NVL/TP split.
- **Option C pluggable strategies:** rejected — over-engineering for MVP.

**Consequences:**
- Hub schema shrinks: 1 table dropped, 1 column dropped, 1 index dropped, 1 API endpoint gone, 1 API field gone.
- `app/parsers/goods_name.py` STAYS at hub — that's genuine ingestion (parser extracts internal_code from goods_name at upload time). Hub-job legitimate.
- `bcct_rows.internal_code` still populated at upload via the parser. BQD pairs in `hub.code_mappings` still master data hub-owned.
- `hub.clients.code_resolution_mode` field still meaningful — controls parser pick (identity vs growatt regex). Not the canonical-pick strategy (that's gone).
- `scripts/settlement_resolver.py` is a hub-side helper for now. When BCQT migrates: copy/move into BCQT repo, fix NVL/TP split per original Growatt algorithm, store output in `bcqt` schema or per-project SQLite.
- Cross-app coupling permanently severed — hub will never serve a "canonical HQ" answer that depends on consumer-side strategy.
- M9 deliverable list updates: BCQT migration scope grows by "build settlement_resolver consumer-side" — but that work was always going to happen, just deferred to BCQT-side from day 1 instead of being a hub→BCQT decoupling later.

**Cross-repo:** No update to BCQT-System or CO-main needed — they haven't migrated yet, no integration code exists. When migration sprint lands, settlement_resolver.py goes with BCQT.

---

## 2026-05-03 BOM flattening — flatten metadata as separate axis from actor/intent

**Context:** CO repo posted an implementation prompt (`~/workspace/client/barry-CO-main/.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`) requiring Data Hub to land technical-BOM flattening before CO migrates to consume Data Hub BOM. Spec required new fields for source kind / flatten status / strategy / lineage. Existing `bom_artifacts.actor` (`agency_staff|co_system|erp_pipeline|system`) and `intent` (`asserted_technical|derived|modified_for_case|staff_edit`) were the obvious tempting overload — but those answer "who created this" and "why", not "what kind of artifact is it" or "is it calculation-ready". Overloading them would have made `intent='asserted_technical'` semantically split between "raw technical BOM" and "manually-written flat BOM", confusing every downstream consumer.

**Decision:** Add **separate** flatten-axis fields (`source_bom_kind`, `flatten_status`, `flatten_strategy`, `source_channel`, `lineage`) to `bom_artifacts`. Keep `actor` and `intent` semantically pure. Persist staff-confirmation gates as audit rows in `hub.bom_flatten_decisions` (linked to `bom_artifacts.materialized_artifact_id`); persist non_flattened evidence per node in `hub.bom_unresolved_nodes`. Stand up a dedicated UOM model (`uom_canonical` + `uom_aliases` + `client_uom_overrides`) — none existed in CO either.

**Alternatives considered:**
- **Overload `intent`** with new values like `intent='technical_flattened'`: rejected — splits "what artifact" semantics across one field, breaks existing `/v1/hub/proposals` filtering and CO/BCQT consumer code that already keys off `intent`.
- **Single `flatten_state` enum** combining status+strategy: rejected — strategy is orthogonal to status (a `flattened` version can use any of three strategies; `non_flattened` has no strategy). Keeping them separate makes the dual-source variant case (status=flattened × strategy ∈ {purchased, exploded}) representable.
- **No staff-confirm at all, auto-publish like CO**: rejected — silent corruption is the spec's explicit primary risk. Staff gates for dual-source / non_flattened / non-alias UOM are non-negotiable.

**Consequences:**
- **Append-only versioning preserved.** Two dual-source variants are two distinct rows in `bom_artifacts` (different `flatten_strategy` + different `normalized_hash`) — no in-place mutation. The existing `uq_bom_idempotent` constraint extends to include `flatten_strategy` + `bom_variant_id` so dual variants don't collide.
- **`/v1/hub/products/{p}/bom/latest` is now flatten-aware.** Filters `flatten_status` and returns `409 dual_source_variants` when multiple flattened variants live for one product. Documented in `docs/API_CONTRACT.md`. Backward-compat: backfilled `manual_flat` versions get `flatten_status='not_applicable'` so legacy callers see `200`.
- **`artifact_no` is variant-scoped.** Per spec §3A, two `bom_variant_id` values for the same product can both legitimately be at `artifact_no=1`. Consumers MUST compare on `artifact_id` or the structured tuple, not bare `artifact_no`.
- **`display_label` is denormalized cache.** Persisted for UI ergonomics but never used as a DB key; spec §3A. Tests assert structured fields, not labels.
- **All stored values are stable English machine codes.** Vietnamese stays in UI/i18n — spec §3B, enforced by CHECK constraints + a typing-level enum-audit test.
- **Cross-app coordination:** Sister-app note posted at `.ai/sister-app-notes/2026-05-03-bom-flatten-shipped.md`. CO migration sprint MUST handle the flatten contract before consuming `/v1/hub/products/{p}/bom/*`. BCQT settlement consumer also affected on its eventual migration.
- **CO write-back path (proposal queue) untouched.** It now flows new versions through the same `create_version` extension with `source_bom_kind='co_modified'` defaulting; no API change.
- **Test count:** 239 → 295 (+56) all green. 28 spec test items each have ≥1 corresponding test.

---

## 2026-05-03 PM Ghost-code policy: tolerate + surface, never auto-derive from BOM

**Context:** Audit during the parser-quality sprint surfaced a 99.8 %
gap on Growatt: `hub.materials` has 16 rows but BOM uses 2440 distinct
material_codes and BCCT seen 301 distinct customs_codes. The pattern
holds because Growatt's BOM rows are written with **supplier-internal
codes** (Mã NB), only some of which map to HQ-registered customs codes
via `code_mappings` (BQD). Many leaf-material codes legitimately have
no HQ registration — they're supplier-internal-only references.

The temptation: extend the existing `derive_from_bcct` auto-derivation
helper to ALSO derive from BOM, materializing a catalog row for every
ghost code. That would close the gap fast.

**Decision:** Do **not** auto-derive catalog rows from BOM. Instead,
**tolerate ghost codes and surface their count** so staff can review
and decide register-vs-ignore per code.

Engineering work that lands now:
- A `bom_unresolved_material_count(client_id)` helper that counts BOM
  material_codes failing all three resolution paths
  (materials.customs_code, materials.internal_code, code_mappings.internal_code).
- A soft toast on the catalog page exposing the count + a hint that
  the codes may be legitimate supplier-internal OR a sign that DS NVL
  / BQD upload is incomplete.

**Alternatives considered:**

- **(a) Auto-derive from BOM (rejected).** Would mint catalog rows
  with no HQ-registration provenance, then later confuse "really
  registered" vs "fabricated by tooling". Compliance audit needs to
  trace every catalog row back to a registration event; auto-derive
  from BOM violates that.
- **(b) FK constraint + reject ghost BOM rows (rejected for now).**
  Would block legitimate uploads where the agency genuinely uses
  supplier-only codes. Could revisit once 100 % of clients have
  uploaded their authoritative DS NVL.
- **(c) Tolerate + surface (chosen).** The catalog page surfaces the
  gap; staff is the human that decides each code's status. Engineering
  doesn't fabricate provenance.

**Consequences:**
- Real-data audit shows ~2434 BOM-only codes for `growatt-vn` —
  expected, not a bug.
- Staff sees the count badge on the catalog page; they can resolve a
  ghost by either uploading a complete DS NVL, adding a BQD entry, or
  manually adding the code to the catalog with explicit "user_added"
  provenance (catalog UI affordance, planned).
- BCQT consumers that try to settle a BOM whose materials don't
  resolve will surface the same gap symptomatically; eventually they
  may want a stricter contract from Data Hub. Out of scope until BCQT
  cutover sprint.
- Sister-app note in `.ai/sister-app-notes/` if/when this changes.

---

## 2026-05-03 PM Future-migration checklist (Sprint A/B/C lessons)

**Context:** Two recent migrations (024, 025) had latent fragility the
plan-review critic surfaced — a NULL `STT hàng` row would have
silently survived 025's preflight; 025's currency overwrite would have
erased rows that used `Nguyên tệ` header instead of `Đơn vị tiền tệ`.
Neither caused current corruption (corpus uniform), but the pattern
will bite future migrations.

**Decision:** When a migration backfills typed columns from the
`payload` jsonb of `hub.bcct_rows` (or any other source-preserving
jsonb), follow this checklist:

1. **Coalesce all known alternative header names**, not just one
   canonical key. Example for `currency`:
   `coalesce(payload->>'Đơn vị tiền tệ', payload->>'Nguyên tệ')` —
   not just the first.
2. **Pre-flight count BOTH the populated and the NULL cases** for any
   key the migration depends on. A pre-flight that filters
   `where key IS NOT NULL` misses rows that need the migration but
   are excluded from the count, leading to mid-flight UPDATE order
   collisions.
3. **Drop and re-add the PK around UPDATE blocks that change PK
   columns** (migration 025 hit a transient collision during single-
   statement UPDATE). NOT the same as `DEFERRABLE INITIALLY DEFERRED`
   — Postgres validates PK at end-of-statement, not end-of-tx, so
   UPDATE that swaps two rows' PKs needs the drop-and-re-add pattern.
4. **Disable user-defined triggers** (e.g., `trg_bcct_row_history`)
   for bulk system rewrites; don't try to disable system FK triggers
   (`alter table ... disable trigger all` fails with permission denied
   on system constraint triggers).

**Alternatives:** Could enforce via a migration-template / linter — too
heavy for current pace. The checklist + a `/rev` review on every
migration PR is the right level.

**Consequences:** Future migrations review against this list. If
checklist grows past ~5 items, promote to a real lint.

---

## 2026-05-04 PM — BOM raw graph + flat rows storage

**Context:** Growatt and Johnson factory technical BOMs are multi-level
graphs. Existing `technical_flatten` parser paths correctly produce
leaf-flat output, but they lose direct parent-child edges needed for
audit, source-row traceability, and comparison against staff-converted
workbooks such as Growatt `GOM BOM TP/BTP`.

**Decision:** Store BOM in two physical row shapes under the existing
`hub.bom_artifacts` table:

- `hub.bom_edges` for `source_bom_kind='technical_raw'`,
  `flatten_status='non_flattened'`, `flatten_strategy='no_strategy'`.
  Each row is one direct `parent_code -> child_code` edge with
  `root_code`, `qty_per_parent`, level/path/source-row metadata.
- `hub.bom_artifact_rows` remains the flat/manual row table for
  `manual_flat`, `technical_flattened`, `staff_edit`, and CO/staff
  modifications.

`technical_raw` upload is a separate profile from `technical_flatten`.
Raw parsing uses dedicated edge parsers and does not reconstruct edges
from already-flattened adapter output. `technical_raw` versions are
excluded from `/latest` by the existing `flatten_status in
('flattened','not_applicable')` filter; pinned version reads can return
`edges`.

**Consequences:** Growatt/Johnson factory workbooks can be ingested as
source graphs, then flattened later with lineage. Staff-converted files
such as `GOM BOM` stay as flat/staff versions and can be diffed against
raw or generated-flat output. Existing flat consumers continue to read
only calculation-ready versions.

---

## Decisions to add post-discovery

(Placeholder — entries to be written during/after M9 discovery sprint)

- Schema canonical choice per entity (BCQT current vs CO seed) — picked entity-by-entity.
- ORM/DAL choice (SQLAlchemy / psycopg raw / etc.).
- Migration tool choice (Alembic / raw SQL).
- Service-to-service auth model (token type, scope design).
- File storage abstraction implementation (`FileBackend` interface).
- SSO session/cookie strategy across 3 apps.
