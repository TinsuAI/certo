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
- M9 deliverable #5 (service-to-service auth) narrows but does not evaporate. **BOM remains CO-writable in MVP** — CO modifies BOM versions for origin-certificate dossiers (e.g., swapping NVL composition to meet RVC thresholds) and writes them back as `source=co_modified` immutable versions with `parent_version_id` lineage. Auth scopes needed: `hub:read:bcct`, `hub:read:materials`, `hub:read:bom` for BCQT and CO; plus `hub:write:bom` for CO. No `hub:write:bcct` for CO in MVP.
- CO migration becomes "add hub read-client (BCCT, Danh Mục, BOM) + add BOM write-client (modified-version submission)" — narrower than the original full write-API rewrite, but not pure read-only.
- The `client_id` → `agency_id`/`dncx_id` semantic split still matters for Data Hub's internal multi-DNCX model **and** at the BOM write boundary (CO submitting a modified version must identify the DNCX correctly).
- Cross-repo coordination: amendment block added to `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM" entry on 2026-05-01.

**Clarification (2026-05-01 evening):** This amendment is **BCCT-scoped only**. CO is a pure read consumer of hub *for BCCT and Danh Mục*; for **BOM**, CO reads versions and writes new modified versions back. The original 2026-04-30 PM ownership rule "CO has no write access to hub schema" still holds at the **schema/DB level** (CO has no Postgres role on `hub`), but the API surface includes a BOM POST endpoint for CO. BOM versions are append-only and tagged with `source ∈ {technical, co_modified, erp_derived, staff_edit, agency_upload}` for provenance. See `.ai/features/2026-05-01-data-hub-read-api.md` for the read-API + BOM-write-back design.

---

## 2026-05-01 (evening) BOM writes via auto-only proposal queue

**Context:** The 2026-05-01 BCCT-amendment narrowed CO from a "writes BCCT to hub" model to "reads BCCT, but still writes BOM modifications back." That left an open question: how does CO write BOM? The naive answer (direct `POST /v1/hub/products/{p}/bom`) makes CO an authoritative writer of canonical hub data, which violates the "Data Hub owns canonical data, consumers cannot directly write" stance. Round-3 critic flagged the BOM provenance model as conflated and the canonicalization story as incoherent.

**Decision:** **CO submits BOM modifications as proposals** (not direct writes). Data Hub gates every external BOM write through an auto-evaluator. MVP runs **auto-only**:

- New endpoint: `POST /v1/hub/products/{product_code}/bom/proposals`. Synchronous response: `{status: approved, version_id, version_no}` or `{status: rejected, decision_reason, failed_conditions}`.
- New schema table: `hub.bom_change_requests` — durable record of every proposal (approved or rejected), with full audit lineage.
- **Auto-rule** (proposal approves only if all hold):
  1. `parent_version_id` resolves to an existing version for same `(dncx_id, product_code)`.
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
- Direct write (CO has `hub:write:bom` token, posts straight to `bom_versions`): rejected — violates canonical-data ownership; no gating against malformed/malicious writes.
- Reviewer-amends-in-place: rejected — breaks audit integrity (record of "what CO actually proposed" lost).
- Hub-counter-proposal-supersedes: considered (preserves audit, no mutability creep) but rejected for MVP — adds workflow complexity that auto-only doesn't need.

**Consequences:**
- **Round-3 critic's "BOM model is thrashing" concern resolves.** "What does CO writing to hub mean?" has a clean answer: CO proposes, hub decides.
- M9 deliverable #5 (service-to-service auth): CO needs `hub:propose:bom` (not `hub:write:bom`). Phase 2 adds `hub:approve:bom` for manual reviewers. Direct-write internal flows use no public scope.
- **Auto-rule criterion #2** ("context.case_id is an active CO case") forces a service-discovery dimension: Data Hub queries CO via API to validate. This couples Data Hub to CO at runtime — Data Hub can't process BOM proposals if CO is down. Defer hardening to service-discovery design pass.
- **Schema additions** (folded into `.ai/features/2026-05-01-data-hub-read-api.md`):
  - `hub.bom_versions`: `actor`, `intent`, `parent_version_id`, `context` jsonb, `tombstoned_at`, `tombstone_reason`, `normalized_hash` (replaces `composition_hash`).
  - `hub.bom_change_requests`: full proposal record table.
  - `hub.bcct_rows.bom_version_id`: point-of-use binding (per round-3 critic) — BCQT settlement reads what was bound at transaction time, not "current."
- **Provenance is two axes**, not a flat enum: `actor ∈ {agency_staff, co_system, erp_pipeline}` × `intent ∈ {asserted_technical, derived, modified_for_case, staff_edit}`. Channel (file/form/api) goes to `context`.
- **"Latest BOM" is a query**, not stored state: `GET /v1/hub/products/{p}/bom/latest` returns most recent published version with `intent ∈ {asserted_technical, staff_edit, derived}` (excludes `modified_for_case`). No `is_current` column.
- **Tracking-code mode is per-DNCX, immutable, set at onboarding** — affects URL grammar (mode-aware variants `/by-customs-code/{c}`, `/by-product-code/{c}`, `/by-key/{c}`). DNCX switching modes mid-life requires re-onboarding under new `dncx_id`.

---

## Decisions to add post-discovery

(Placeholder — entries to be written during/after M9 discovery sprint)

- Schema canonical choice per entity (BCQT current vs CO seed) — picked entity-by-entity.
- ORM/DAL choice (SQLAlchemy / psycopg raw / etc.).
- Migration tool choice (Alembic / raw SQL).
- Service-to-service auth model (token type, scope design).
- File storage abstraction implementation (`FileBackend` interface).
- SSO session/cookie strategy across 3 apps.
