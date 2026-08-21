# Session 2026-06-08 — D.2 staleness: pivot to the narrow convertibility fix

**Commit:** `f17e405` on `main` (not pushed). Suite 1447 passed / 16 skipped.
Brief: `.ai/features/2026-06-08-bom-staleness-fingerprint/brief.md`.

## What Was Done

Backlog review (user: "xem backlog còn gì quan trọng") surfaced D.2 (BOM
staleness rework) as the natural next item — A.4.4 had just shipped
`classify_uom_relation` the prior session, unblocking it.

Ran the full risky-change workflow: `/discover` → critic review → `/tdd` →
`/rev` → commit → docs → handoff.

**Shipped (scope A — narrow fix):**
- **Mig 077** (`077_drift_remaining_classifier_parity.sql`) — `create or replace
  hub.has_drift_remaining` to mirror `classify_uom_relation` acceptance. Returns
  "drift remaining" (true) only for genuinely **incompatible** pairs. Newly
  accepted as convertible (→ false / no drift): same-family `base_factor`
  (g↔kg via `uom_canonical.family`), tier-A 1:1 (`{count, count_packaging,
  assembly}`), client-wide override (`material_code_key=''`), reverse-direction
  override. Function-only replace → D7/D9 triggers (mig 071) +
  `reconcile_for_material` pick up the new body by name. Backfill re-runs the
  mig 070/071 "all rows resolved? → clear" pass with the widened predicate.
- **`tests/test_has_drift_remaining_parity.py`** (new, 12 cases) — the drift
  guard: asserts SQL `has_drift_remaining` ⇔ `classify_uom_relation` (pinned to
  absolute expected values AND cross-checked against the classifier). Written
  failing first: 6 red on the old SQL (same-family ×2, tier-A ×2, reverse,
  client-wide).
- **`tests/test_bom_state_and_conditional_triggers.py`** (+4 tests) — D7 skips
  flag on same-family + tier-A edits; reconcile clears a same-family false
  positive; tier-A `needs_input` preserved (decoupled from staleness).
- **`tests/test_d9_catalog_insert_trigger.py`** — 2 tests retargeted from kg↔g
  (now convertible) to kg↔ea (tier-B incompatible) so they still exercise a
  genuine drift.
- **`tests/test_ingest_order_invariance.py`** — `..._propagates` renamed to
  `test_convertible_context_change_does_not_churn_published_rows`, asserts the
  new no-churn behavior.
- **Docs:** `docs/API_CONTRACT.md` (`stale_count`/`state` convertibility-aware +
  "read `row.uom`"), `docs/API_CHANGELOG.md` (Cosmetic, silent — no shape change),
  `.ai/DECISIONS.md` (2026-06-08 entry), `.ai/sister-app-notes/2026-06-08-...md`.

## Decisions Made

- **Scope A over scope B.** The original brief proposed a fingerprint /
  derive-on-read rebuild (drop 9 triggers, Python `recompute_staleness`). A
  **critic review** flagged it as over-built and verified-in-code: (1) the
  family-canonical normalizer it rests on doesn't exist (`uom.py` is pairwise-
  only); (2) DB-trigger → app-hook is a guarantee downgrade for a compliance
  product (triggers observe psql / bulk re-ingest; hooks don't) → under-flagging
  aimed at CO/BCQT; (3) `reconcile_for_material` already caps at 50 / `deferred`
  → sync full-tree re-derive doesn't scale, needs a job queue that doesn't exist.
  The narrow SQL backport (A.4.4 R2) delivers ~90% value (kills the UoM
  false-positive class) at ~10% risk — no schema change, no guarantee downgrade.
  User picked A.
- **tier-A 1:1 = not stale.** Mirrors the classifier (tier-A is convertible).
  The "cần xác nhận" surface comes from the materialize-time
  `unconfirmed_default_1to1` reason → `needs_input`, NOT the trigger. Accepted
  consequence (flagged in `/rev`): a post-hoc edit that newly creates a tier-A
  pair on an aligned artifact goes silent (clean). Output stays numerically
  correct (1:1); the confirm-prompt is not re-raised. User chose to accept (a).
- **No churn on convertible edits.** kg→g catalog edit doesn't re-derive
  published rows — they keep `2.5 kg` (== `2500 g`, self-describing). Trades
  byte-identity → physical-equivalence for convertible edits; byte-identity
  holds for upload ordering. User accepted. Memory `project_ingest_order_
  invariance` updated.
- **Mirror cascade in plpgsql, pin with parity test.** Can't call Python from a
  trigger (no plpython3u). Re-implementing acceptance in SQL risks re-diverging
  (the original leak) — the parity corpus is the non-optional guard.
- **Docs scope:** 4 targets (contract / changelog / decisions / sister-app note),
  each a distinct audience. Changelog classified `Cosmetic` (silent, no consumer
  code impact) deliberately — not Breaking.

## What Didn't Work / Rejected

- **Scope B (fingerprint rebuild)** — deferred, not abandoned. Kept in the brief's
  "Deferred: B" section with the critic's blockers + the recommended hybrid shape
  (thin dirty-flag trigger + worker verdict) if ever revived. Needs a job queue
  first.
- **Keeping tier-A as drift** (so it re-surfaces `needs_input` on edits) —
  rejected: diverges from the classifier and re-introduces churn.
- **`/rev` minor (normalization gap)** — SQL `lower(trim)` vs Python NFC+collapse.
  Not fixed: no real ASCII token triggers it; a corpus case would be contrived.
  Documented in STATUS notes.

## Open Items

- **Push/deploy** `f17e405` — local-only, user didn't ask to push.
- **D.2-B** — deferred fingerprint rebuild; revive only on real maintenance pain
  + after a job queue exists.
- **CO** — no action required (verified). Sister-app note left for ack; the
  standing "read `row.uom`" contract is now more pertinent due to no-churn.
- **Backlog tier-1 remaining** (from the review): A.5 (paren-aware
  observed_count, user-visible bug), D.1 (aggregate-data git-history,
  regulatory), A.3 (catalog edit form), C.1/C.2 (sister-app JWT → strict auth).
- **Pre-existing untracked files** (older session logs, `docs/training/`, two
  `scripts/*.py`) still need triage — not this session's, left as-is.
