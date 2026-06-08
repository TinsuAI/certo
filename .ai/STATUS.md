# Project Status

**Date:** 2026-06-08 — **D.2-A shipped & committed to `main`** (convertibility-
aware staleness, narrow fix). Backlog review → `/discover` → critic → `/tdd` →
`/rev` → commit → docs → handoff.

## Current State

**Branch:** `main`, HEAD **`f17e405`** — committed, **NOT pushed** (user didn't
ask). **Tests:** full suite **1447 passed / 16 skipped** (run twice). **Migrations:**
latest **077** (`077_drift_remaining_classifier_parity.sql`).

**Dev server:** the `:8754` process from the prior session may still be running;
restart if gone: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8754
--workers 1 --reload`.

**Working tree:** clean except pre-existing untracked files NOT from this session
(`.ai/sessions/*.md` from older sessions, `docs/training/`,
`scripts/generate_training_input_scenarios.py`, `scripts/uom_drift_report.py`) —
left for repo hygiene, not mine to commit. This session's STATUS.md edit + the
new session log are the only tracked changes after the commit.

This session's commit:
- **`f17e405`** `feat(uom)`: widen `has_drift_remaining` to mirror
  `classify_uom_relation` (D.2-A). 10 files, +717/-18. Migration + parity test
  + 3 test updates + brief + 4 docs.

Full detail: `.ai/sessions/2026-06-08-staleness-convertibility-narrow-fix.md`.
Brief: `.ai/features/2026-06-08-bom-staleness-fingerprint/brief.md`.

## Recent Changes (this session)

D.2 started as a big fingerprint/derive-on-read rebuild (scope B); a **critic
review** found it over-built (non-existent family-canonical primitive,
DB-trigger→app-hook guarantee downgrade, fan-out cost, no job queue). Pivoted to
the **narrow fix (scope A)**: widen the SQL `hub.has_drift_remaining` to mirror
A.4.4's `classify_uom_relation` acceptance.

- **Mig 077** — `has_drift_remaining` returns "drift remaining" only for
  genuinely **incompatible** pairs. Now also accepts (→ no drift): same-family
  `base_factor` (g↔kg), tier-A 1:1 (count/assembly), client-wide override,
  reverse-direction override — not just alias + exact per-material override.
  `create or replace` only → D7/D9 triggers + `reconcile_for_material` pick up
  the new body. Backfill clears residual false-positives.
- **Parity guard** (`test_has_drift_remaining_parity.py`, 12 cases) — pins SQL
  `has_drift_remaining` ⇔ Python `classify_uom_relation` (absolute + cross-check).
  The drift guard (brief R1). Wrote failing first (6 red on old SQL).
- **Behavior change accepted by user:** convertible catalog edit (kg→g) no
  longer re-derives published rows — they keep their materialize-time unit
  (`2.5 kg`, physically == `2500 g`, self-describing). Updated the
  order-invariance test + 2 D9 tests (retargeted to incompatible kg↔ea pairs).
- **Docs:** API_CONTRACT (`stale_count`/`state` convertibility-aware + "read
  `row.uom`"), API_CHANGELOG (Cosmetic, silent), DECISIONS 2026-06-08,
  sister-app note. CO impact = **none** (verified CO doesn't gate on DH
  staleness flags + already reads `row.uom`).

## Next Steps

1. **(Optional) Push** `f17e405` to demo if you want it live (prior A.4.4
   session stopped at local commit too; this one likewise local-only).
2. **D.2-B (deferred)** — the fingerprint/derive-on-read rebuild. Only revisit if
   the trigger-push model causes *real* maintenance pain, and only after a job
   queue exists. Full why-deferred + critic blockers in the brief's "Deferred: B"
   section. Not scheduled.
3. **Other open backlog** (from this session's review): A.5 (v_material_roles
   paren-aware — list page shows wrong observed_count), D.1 (aggregate-data
   git-history, regulatory), A.3 (catalog edit form), C.1/C.2 (sister-app JWT →
   strict auth). See `.ai/BACKLOG.md`.

## Notes for Next AI Session

- **tier-A semantic choice (important):** tier-A 1:1 = "not stale" (mirrors
  classifier). The "cần xác nhận" surface comes from the materialize-time
  `unconfirmed_default_1to1` reason, NOT the trigger. Accepted consequence: a
  post-hoc edit that *newly* creates a tier-A pair on an aligned artifact goes
  silent (clean). Don't "fix" this as a bug — it's a deliberate decision
  (DECISIONS 2026-06-08).
- **Parity test is non-optional infra** — if you touch `has_drift_remaining` SQL,
  `test_has_drift_remaining_parity` guards against re-diverging from the Python
  classifier. Keep it green.
- **SQL vs Python normalization gap (minor, known):** `has_drift_remaining` /
  `is_uom_aligned` use `lower(trim())`; the classifier uses `normalize_uom_alias`
  (NFC + collapse-whitespace). Identical for all real ASCII uom tokens; a
  multi-word/NFC token could diverge and the corpus wouldn't catch it. Deferred
  (no real token triggers it).
- **`project_ingest_order_invariance` memory updated** with the convertible-edit
  nuance (byte-identity for uploads, physical-equivalence for convertible edits).
- Port **8754** pinned (CO JWT issuer). Don't change it.
