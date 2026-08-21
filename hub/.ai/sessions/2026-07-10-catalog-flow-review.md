# Session: Catalog flow review → discovery brief

**Date:** 2026-07-10 (second session this day; the first shipped SSO refresh tokens)
**Type:** Review + discovery. **No production code written.**
**Deliverable:** `.ai/features/2026-07-10-catalog-candidates-merge/brief.md`

## What was asked

"Review the catalog build flow; suggest how to make it better." Escalated mid-session to
a design decision (merge `catalog_candidates` into `materials`), then to a full discovery
brief after a `critic` pass and three domain rulings.

## What was found

Everything below was verified against the local dev DB or by reading code — not inferred.

**The catalog has three population mechanisms, and the one in the UI is unused.**
`derive_from_bcct` auto-inserts `customs_code` as `status='active'` with no review;
`catalog_candidates` is the review queue; `materials.status='under_review'` +
`promote_material` is dead code (0 rows → the route 404s every call).
**100% of accepted candidates were approved by a script** (`decided_by='bulk_nvl_accept_*'`,
1207 rows in 255 seconds). Zero manual approvals, zero rejections, ever.

**Bugs found (all new):**

1. `derive_from_bcct` (`stores/provenance.py:33`) filters `customs_code <> ''` but not
   `'.'` → one junk material named `.` per client. 3,509 Growatt BCCT rows and 13 Johnson
   rows collapse into it. Those rows are BYD forklifts and storage racks (100% `import`/`E13`).
2. Those same rows yield **218 NB codes, 210 of which appear only on fixed-asset lines**
   — forklift/rack parts sitting in the approval queue as if they were production materials.
   None has reached `materials` yet.
3. `refresh_candidates()` runs inside a `GET` handler (`routes/catalog_candidates.py:143`).
   Measured 2.19s / 2.19s / 2.45s on Growatt. The comment above it claims
   *"cheap: sub-second on Growatt-scale data"*.
4. `/v1/hub/materials` has no `status` filter, while `tombstone_material` sets
   `status='tombstoned'`. A tombstoned material would be served to CO. Latent only because
   all 13,631 rows are `active`.
5. `unreject_candidate` does not undo an accept — the material and its `code_mappings` stay.
6. `accept_candidate` hardcodes `source='bcct_observed'` even for BOM-origin codes;
   `bom_observed` has no live writer (Johnson's 3,822 such rows came from a fixup script).
7. `promote_material` sets `source='client_declared'` when promoting — wrong semantics.
8. Catalog state depends on ingest path: 694 distinct `customs_code` in Growatt's
   `bcct_rows`, only 302 became materials, because `derive_from_bcct` runs in the route and
   part of the data was loaded by `scripts/ingest_curated_xlsx_direct.py`.

**Keystone:** the paren-extraction result is never persisted. `bcct_rows` has no extracted
code column and no link table exists, so the same Python regex re-runs in five places.
`stores/material_observations.py` is a self-declared workaround for the resulting blind spot
in `v_material_roles`; mig 050 concedes SQL cannot do the extraction ("would require plpython").

**BQD:** the upload flow is not broken — it runs end to end (replayed on a scratch client:
73 rows ingested, `parse_status='done'`). It stalls because `upload_initial_dispatch` only
skips the column-mapping page when a *confirmed* mapping is cached, and the cache is only
written on confirm. Nobody confirmed; a script was used instead. Growatt's two real BQD
uploads are still `mapping_pending` from 2026-05-05, while all 2,892 `code_mappings` rows
were written by `ingest_curated_xlsx_direct.py`, whose docstring says it
*"bypasses the unified-mapping-flow UI"*.

**Four ingest surfaces have been bypassed by scripts.** The DB's current state was authored
largely by scripts, not by the product. This is the real reason the flow is hard to hold in
one's head: the logic that produced the data is not the logic in the routes.

## Decisions

Domain rulings from the user (recorded in memory `project_customs_code_semantics`):

1. **HQ bucket codes are materials.** `LK-DAY2` groups 158 NB codes and stays in the
   catalog. Consequence: BCCT signals must never be bridged from an HQ code to its NB
   children via `code_mappings` — it would overcount by up to 158×. This killed the
   `critic`'s proposed alternative to the link table.
2. **`'.'` is a fixed-asset marker and must be excluded**, and the placeholder set must be
   per-client configurable. `declaration_type` is not the discriminator (Growatt has 102
   `E13` rows with real codes; Johnson 4,260).
3. **`hq_registered` is tracking only.** `api.py` never emits it; CO has never seen it.
4. **Mark machinery codes, don't drop them** — `customs_relevance='excluded_non_material'`,
   still visible, excluded from bulk approve by default.
5. **Build a bulk-approval UI.** Per-item review is not viable and never happened.

Design decisions in the brief: pending needs no persistence (anti-join view); reject is a
suppression table, not a material status; `_collapse_unaffiliated_kinds` must stay a
corpus-level view computation; persist only `bcct_nb_codes`; **no `v_catalog` view** — a
view is not enforcement when the API runs as the read-write role, so ship a default filter
plus a regression test.

## What didn't work

- `/grilling` — the user found code-level design forks unproductive. Abandoned after two
  questions. The useful move was to map the subsystem first.
- The first brief (merge candidates into `materials` as `under_review`) was written and then
  superseded within the same session, twice: once by the `critic` pass, once by the user's
  question "what does *rejected* even mean". Both corrections were right.
- Two SQL `NULL` traps in my own analysis queries (`NOT IN` over a set containing `NULL`
  silently returns zero rows). Both caught by cross-checking that the partitions summed to
  the total. Worth remembering.
- I reported CO findings from a subagent without reading CO myself; the user caught it. I
  then verified the three load-bearing claims directly. All held.

## Open items

Blocking Phase 0: **where does the placeholder config live** — `text[]` on `hub.clients`,
or a per-client config table? Seeding must be guarded or CI on a fresh DB goes red
(`feedback_guard_client_seed_in_migrations`).

Not blocking Phase 0/1: accept provenance columns on `materials`; what `source` bulk
approval writes; whether the discovery view needs a "first surfaced" timestamp.

Known risk for Phase 5: bulk-approving 2,157 codes fires the mig-058 trigger once per row
and marks nearly every Growatt BOM stale. Correct behaviour, but it must be batched.

Also unreconciled: the 392 Growatt HQ codes that were never derived because their BCCT file
came in through a script. Separate call.

## Next step

`/tdd` on Phase 1 (default `status='active'` on the two `/v1/hub/materials` routes + a
regression test). It has zero open questions and a byte-identical-response oracle. Phase 0
needs the config-location decision first.

Expected end state for Growatt: 3,306 pending → 2,157 approvable by rule, 210 marked as
machinery, ~939 left for human review.
