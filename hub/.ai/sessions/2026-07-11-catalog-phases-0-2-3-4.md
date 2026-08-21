# Session 2026-07-11 — Catalog phases 0, 2, 3, 4 shipped

Four issues implemented, reviewed, merged, and prod-verified in one session:

| Issue | PR | Merge | What |
|---|---|---|---|
| #30 placeholder config | #41 | `4d74819` | `hub.clients.customs_code_placeholders text[]` (mig 090), one `_is_missing_hq` predicate + 4 readers, junk `.` materials deleted |
| #32 refresh out of GET | #42 | `15ad288` | Candidates GET read-only (0.36s vs 2.2s), post-ingest hooks + «Làm mới» button |
| #33 bcct_nb_codes | #43 | `2f68100` | Paren extraction persisted (mig 091), v_material_roles 6th def, machinery marking, material_observations workaround deleted |
| #34 discovery function | #44 | `58e1994` | `hub.catalog_discovery(client)` SQL function (mig 092), `catalog_rejections`, `catalog_candidates` DROPPED, −1,817 lines |

Prod after `58e1994`: pending growatt = 3,306 (exact preservation), 1,207
decision tuples in `bom_audit_events` (`catalog_candidate_decision`),
`bcct_nb_codes` = 35,349 (boot backfill re-extracted with self-links),
suite 1591 passed / 16 skipped.

## Decisions made (beyond the issue texts)

1. **Machinery marking guard (#33):** a code that ever appears as its own
   `customs_code` is never marked `excluded_non_material` → 207 marked / 11
   spared vs the issue's measured 210/8 (3 direct-declared codes:
   `00G.0101600`, `PE07.0143500`, `PE07.0214500`). Spec review judged it
   honors intent. **User has not explicitly certified** — flagged in PR #43.
2. **Function, not view (#34):** a plain view materializes the whole corpus
   per query (4.5s measured); the set-returning function computes one client
   (~0.6–1.3s). ADR-0001 amended in-file.
3. **Suppression by string:** `catalog_rejections` PK `(client_id, code)` —
   one reject hides every kind. Per ADR "staff said no to this string".
4. **Accept source-by-stream:** bcct→`bcct_observed`, bom→`bom_observed`,
   bqd-only→`client_declared` (client-authored mapping sheet). Spec silent
   on the bqd case — flagged in PR #44, unchallenged.
5. **`bcct_nb_codes` widened (mig 092):** also stores the unified self-link
   (extracted code == customs_code) so SQL detects the NB==HQ case; mig
   truncates, boot backfill refills (35,349 vs 34,232).
6. **Parser renamed** `app/parsers/catalog_candidates.py` →
   `code_extraction.py` (it feeds `bcct_nb_codes`); its BOM/BQD helpers
   deleted as dead — those streams live in the SQL function now.
7. **`promote_material`** no longer rewrites `source` to `client_declared`.
8. **customs_relevance is 3-surface:** canonical view + 2 inline mirrors
   (api.py `_MATERIALS_SELECT_WITH_ROLES`, catalog.py list). #33's review
   caught the mirrors actively reporting machinery codes `declarable`;
   predicate extracted to `hub.v_placeholder_only_codes`, parity test seeds
   the case. Anyone touching customs_relevance must touch all three (the
   parity test now enforces it).

## What didn't work / gotchas

- **First view draft was whole-corpus** — multi-referenced CTEs are
  materialized, client predicate never pushes down. EXPLAIN before shipping
  any view with repeated CTEs.
- **Route collision:** `/catalog/candidates/detail` was swallowed by
  catalog.py's `/catalog/{material_code:path}/detail`. Discovery router now
  registers BEFORE catalog in main.py — keep that order.
- **Dev-server restarts leave orphan workers:** `pkill` on the master exits
  the tracked task but the 4 workers keep :8754 bound ("Address already in
  use" on relaunch). Kill worker PIDs from `fuser 8754/tcp` explicitly,
  verify exit 1, then start.
- **Editing an applied migration locally:** delete its `schema_migrations`
  row + drop the object + re-apply; mig 092's DO-block guard makes re-apply
  safe. Remember `bcct_nb_codes` refill after any 092 re-apply.

## Deferred, documented (not bugs on current data)

- Collapse `decl_count` sums per-kind counts instead of unioning
  declaration sets (double-count needs one declaration carrying the code on
  rows of both kinds AND collapse — no such row today). PR #44 body.
- `rejected_*` → `decided_*` aliasing in the function output (template
  contract predates). SQL classifier duplicates the Python classifier
  cross-language (rule changes touch both; cross-referenced in comments).
- #33 oracle note: A.5's "68 references" is now 77 (data grew since May);
  parity sample 20 rows = 0 diffs.

## Open items

1. **`/implement #35`** — bulk approval UI, last catalog phase, unblocked.
   Fresh session. Plan the mig-058 staleness trigger mass-fire (brief Risk
   2): ~2,157 accepts → batch or suspend-and-recompute.
2. **#37 decision (user):** dead materials in CO's BCCT identity payload —
   hide (apply #31 predicate) vs document-and-keep.
3. Housekeeping: `docs/agency-staff-guide` branch PR-or-drop; `v0.19.0` tag
   absent; prod collation-version mismatch (maintenance window); release cut
   0.21.0 (CHANGELOG `[Unreleased]` now holds 4 entries + pyproject/uv.lock
   bump).

Full specifics live in: PRs #41–#44, migs 090–092, ADR-0001 (amended),
`.ai/features/2026-07-10-catalog-candidates-merge/` (brief, design review,
ui_smoke + screenshots 10–13).
