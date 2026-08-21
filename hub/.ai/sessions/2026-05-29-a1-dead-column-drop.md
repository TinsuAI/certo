# 2026-05-29 — A.1 closed as dead-column drop (not the planned refactor)

## What Was Done

- `/discover` on BACKLOG A.1 — original plan: replace single
  `materials.category` + `category_override` patch with multi-role
  `roles[] text[]`, ~2-3 day cross-cut refactor (~30-50 file touches).
- Audit pass: 29 app files + 16 test files reference `category`.
  CO `data_hub_client.py` consumes `category` (lines 643/732/735/861,
  + `main.py:6679`) for product/material partition. BCQT touches none.
- Wrote initial brief at
  `.ai/features/2026-05-28-catalog-roles-array/brief.md` proposing
  the full refactor with primary_role priority policy + CO back-compat.
- Challenged by user multiple times:
  1. "Why drop the column at all?" → proposed `category` as Postgres
     `generated always as (primary_role(roles)) stored` column.
  2. "roles[] is multi-value, category single — how do you generate?"
     → admitted the priority-policy approach is lossy (filter
     `category='nvl'` silently excludes multi-role-nvl rows).
     Presented three options (drop / ordered-roles-with-roles[1] /
     generated-via-priority).
  3. "What does roles[] actually serve?" → forced honest assessment:
     limited current user-visible value; `observed_roles[]` (mig 046)
     already surfaces multi-role at view level.
- Data audit on local dev DB (native Postgres, peer auth):
  ```
  | client      | total | override set | observed multi-role | declared conflict |
  | Growatt VN  |   457 |     0        |          5          |        0          |
  | Johnson VN  | 13132 |     0        |        416          |        1          |
  ```
  → `category_override` + `override_reason` columns **completely
  unused** across 13,589 rows. 1 declared/observed conflict total.
- Traced origin: mig 002 scaffold (2026-05-01) added the columns
  under a "patch instead of edit" design. Session
  `2026-05-01-client-restructure-i18n-redesign.md` line 49 confirms
  intent; line 77 to-do #11 ("Material `category_override` +
  `override_reason` UI — schema ready; admin UI not exposed") was
  dropped on the floor and never resumed.
- Mig 045 audit trigger + A.3 edit form + mig 046 v_material_roles
  view supplanted the original use cases (audit history,
  direct editing, multi-role surfacing).
- Decision: drop the dead columns instead of doing A.1 as
  originally scoped.

**Shipped (commit `79ae85a`, ~35 min execution):**

- `db/migrations/072_drop_category_override.sql` — recreates
  `hub.v_material_roles` dropping `coalesce(override, category)`
  (declared_kind = `m.category`); drops both columns from
  `hub.materials`. Single transaction.
- 6 callsite refactor: `app/routes/catalog.py` (x2),
  `app/routes/api.py`, `app/resolvers/bcct_material_identity.py`,
  `app/templates/clients/catalog_detail.html`,
  `app/templates/clients/catalog_conflicts.html`. All strip the
  column ref or `coalesce()`.
- `docs/API_CONTRACT.md` — remove `category_override` from material
  response fields list.
- `docs/API_CHANGELOG.md` — Breaking entry for JSON field removal.
- `.ai/BACKLOG.md` — A.1 marked CLOSED 2026-05-28 with rationale.
- `.ai/features/2026-05-28-catalog-roles-array/brief.md` — kept as
  discovery artifact showing the path from "refactor" to
  "dead-code drop".

Tests: 1260 passed, 15 skipped (baseline unchanged).

**Then (commit `51503bf`):** STATUS.md refresh — Current State to
`79ae85a` + mig 072; Recent Changes section replaced; Notes for
Next AI Session headline updated.

Push timeline:
- `79ae85a` pushed → CI run 26583739686 → demo at new commit,
  healthz 200, demo DB columns confirmed dropped.
- `51503bf` pushed (docs-only).

Dev server restarted on :8754 after the code changes (manual,
`--workers 4`, no `--reload`).

Memory updated: `project_bom_code_multirole.md` notes mig 072 + the
view-level surfacing supersedes the originally-planned column-level
fix. Domain insight ("a code can be TP+BTP+NVL simultaneously")
retained because it remains true and informs Phase 3 if/when
revived.

## Decisions Made

- **A.1 closed without doing the refactor.** Data showed no pain
  to solve: 0/13,589 rows with `category_override` set; 1 declared/
  observed conflict total. The BACKLOG plan was solving a
  hypothetical problem.
- **Reject "generated column" intermediate** (my own mid-session
  proposal). Single-value `category` derived from multi-value
  `roles[]` requires a lossy priority policy. Filter
  `category='X'` would silently miss multi-role-X rows. Hidden bug
  worse than typed work to do the full refactor.
- **Keep `category` single-value.** Multi-role truth lives in
  `observed_roles[]` (mig 046 view), surfaced via "Đa nguồn" badge.
  Declared multi-role deferred to Phase 3 if concrete need appears.
- **Drop both `category_override` + `override_reason`** (not just
  the override). `override_reason` was dependent on `category_override`
  being settable; both go together. 0 rows had `override_reason` set
  either.
- **Single migration, single transaction.** DROP VIEW + recreate +
  DROP COLUMN in one BEGIN/COMMIT. Triggers in mig 053/057/058/069/
  071 reference `materials.category` directly (not override), so
  no trigger rewrite needed.
- **Standalone STATUS commit.** User asked explicitly to commit
  STATUS.md separately from the schema change, not bundle. Two
  commits in this session: `79ae85a` (schema + code) and `51503bf`
  (docs/status only).

## What Didn't Work

- **The original brief.** First draft of
  `.ai/features/2026-05-28-catalog-roles-array/brief.md` proposed
  the full refactor with primary_role priority policy + CO back-
  compat field. User challenge "why drop" + "what does roles[]
  serve" forced re-evaluation. Brief kept as artifact, not deleted,
  to show the discovery path.
- **"Generated column" mid-session pivot.** Suggested
  `category = generated always as (primary_role(roles)) stored`.
  Looked clever but failed scrutiny: `primary_role(['nvl','tp'])`
  returns `'tp'` (per proposed priority tp > btp_sx > btp_nm > nvl
  > ccdc); filter `category='nvl'` then excludes the row even
  though it does play nvl role. Silent semantic wrong, not loud
  fail. Dropped.
- **"Ordered roles[1] = primary" alternative.** Would have worked
  cleanly (Postgres preserves array order; `category = roles[1]`
  exact, not lossy). But user's "what does roles[] serve" question
  showed the whole multi-role direction was solving a non-problem
  given current data. Discarded along with full refactor.

## Open Items

- **F.1 Growatt BOM wipe + re-ingest** — still pending per
  `project_reingest_pending.md`. Hygiene only; defer unless surface
  pain appears.
- **A.4.3 follow-up** — current normalize-then-bucket gives 21%
  noise reduction on Johnson per-product codes. Only revisit if
  staff complain.
- **D.1 Aggregate-data git-history** — large principle work
  (materials/code_mappings/client_config history tables + revert
  UI). Needs `/discover` first.
- **STATUS open items unchanged** — offsite backup missing
  (single VPS = SPOF); ALARM file → external alert (user passed
  on this one explicitly).
- **Dirty state in working tree (pre-existing, not from this
  session):** 26 modified demo screenshots / xlsx / manifest files
  under `.ai/features/2026-05-04-demo-company-feed/`, plus
  untracked sessions (`2026-05-15-catalog-conflicts-page-ship.md`,
  `2026-05-15-m16-ingest-and-uom-evidence-audit.md`,
  `2026-05-25-bulk-zip-upload-shipped.md`,
  `2026-05-28-bom-vocab-v1-alias-drop.md`) and untracked scripts
  (`scripts/generate_training_input_scenarios.py`,
  `scripts/uom_drift_report.py`, `docs/training/`). Not introduced
  this session; not addressed here. Next session may want to
  triage.
