# ADR-0001: Catalog discovery is a view, not a table

**Date:** 2026-07-10 · **Status:** Accepted

## Context

`hub.catalog_candidates` (mig 047) stores codes discovered in BCCT, BOM, and BQD that are
not yet in `hub.materials`. It is a sticky state machine (`pending / accepted / rejected`)
rebuilt from source data on every read by `refresh_candidates()`, which runs inside a `GET`
handler and costs 2.19s / 2.19s / 2.45s on Growatt (39,203-row scan, Python regex per row,
3,306 UPSERTs).

Evidence gathered 2026-07-10 on the dev DB:

- 100% of accepted candidates were approved by `scripts/accept_nvl_candidates_from_artifact.py`
  (`decided_by='bulk_nvl_accept_*'`, 1,207 rows in 255 seconds). Zero manual approvals.
- Zero rejections have ever been recorded, for either client.
- The catalog has three population mechanisms, not one: `derive_from_bcct` (auto-inserts
  `status='active'`, dominant), candidate accept, and the dead `promote_material` route.

## Decision

Three kinds of information, three homes:

| Information | Nature | Home |
|---|---|---|
| Which codes exist but are not in the catalog | derived | a **view**, stored nowhere |
| Staff said no to this string | manual input | a small **suppression table** |
| This string is a material | manual input (accept) | a row in `hub.materials` |

`hub.catalog_candidates` and `app/stores/catalog_candidates.py` are deleted. "Pending" is
computed as an anti-join between discovered codes, `hub.materials`, and the suppression
table. It is the absence of a decision, so it is not stored.

Rejection is **not** a material lifecycle state. A rejected string was never a material, so
`status='inactive'` on a `materials` row would assert something false. `materials.status`
gains no `rejected` value.

The BCCT paren extraction is persisted as `hub.bcct_nb_codes`, because it is the only fact
in the discovery inputs that is not already a column (BOM codes live in `bom_edges` and
`bom_artifact_rows`; BQD codes in `code_mappings`; HQ codes in `bcct_rows.customs_code`).
Migration 050 records that the extraction cannot be expressed in SQL without plpython.

## Consequences

- `stores/material_observations.py` — a self-declared workaround for `v_material_roles`
  joining only on `customs_code` — is deleted once the view reads `bcct_nb_codes`.
- `_collapse_unaffiliated_kinds` must live in the view, not an ingest hook: it asks whether
  a string ever co-occurs with a different code anywhere in the corpus, so a per-row hook
  would make `code_kind` order-dependent and break ingest-order invariance. Verified
  expressible in pure SQL once the link table exists: a self-join on
  `(transaction_key, line_no)`, measured at 0.162s on Growatt.
- Invalidation of `bcct_nb_codes` is delete-and-rebuild per client, not an incremental
  staleness domain. A full re-extract measured 0.88s (Growatt) and 0.14s (Johnson).
- Approval becomes a bulk operation over a filtered view. The filter is the rule; there is
  no rule-authoring DSL. The 2026-05-09 pivot away from the `catalog_derive` wizard rejected
  per-page regex authoring, not automation.

## Rejected alternatives

**Merge candidates into `materials` as `status='under_review'`.** Drafted, then dropped:
it would insert ~3,300 rows that fire the mig-058 staleness trigger, leak to CO (which
copies `status` through and never filters on it), and inflate `v_material_roles`.

**Guard the read boundary with a `hub.v_catalog` view.** A view is not enforcement here —
the read API runs as Data Hub's own read-write role, so `SELECT` on `hub.materials` cannot
be revoked, and choosing the wrong object is exactly as forgettable as omitting a `WHERE`.
Ship a default `status='active'` filter on `/v1/hub/materials` plus a regression test.

**Bridge NB codes to their HQ code's BCCT signals via `code_mappings`.** Rejected: HQ codes
are buckets. `LK-DAY2` maps to 158 NB codes; the bridge would attribute the bucket's entire
declaration history to each child. See ADR-0002.

## References

- Brief: `.ai/features/2026-07-10-catalog-candidates-merge/brief.md`
- Session: `.ai/sessions/2026-07-10-catalog-flow-review.md`
- Supersedes nothing. The `roles[]` refactor (`.ai/features/2026-05-28-catalog-roles-array/`)
  remains rejected per mig 072 and BACKLOG A.1 — do not revive it.

## Amendment (2026-07-11, #34 implementation)

Shipped as a **set-returning SQL function** `hub.catalog_discovery(client_id)`
rather than a plain view. The discovery CTEs are referenced repeatedly, so a
view materializes the whole corpus on every query regardless of the client
filter (measured 4.5s, all clients); the function computes one client
(~0.6–1.3s Growatt). The decision's substance is unchanged: pending is the
absence of a decision, computed at read time, stored nowhere. Two further
refinements from the same session: the suppression key is `(client_id, code)`
— staff say no to the *string*, so one rejection hides every kind of it — and
`hub.bcct_nb_codes` also stores the unified self-link (extracted code equal to
the row's `customs_code`), which is how the function detects the NB==HQ case
without re-running the regex.

## Amendment (2026-07-17, #49 — `under_review` removed for real)

The first rejected alternative above is now enforced, not merely declined.
`under_review` survived in `materials.status` as a leftover of the abandoned
`catalog_derive` wizard: accepting one candidate wrote it, while the bulk
button beside it wrote `active`, and BCCT ingest — which nobody reviews —
wrote `active` too. So the unreviewed path produced the more trusted state.

Migration 094 drops the value from the CHECK (`active | deprecated |
tombstoned | inactive`). The `promote_material` route, the `?status=under_review`
chip, the status badges, and the resolver's `resolution_status='resolved_pending_review'`
are all deleted. `promoted_to_declared_at` / `promoted_by` are retained but no
longer read.

This closes the gap the ADR's own reasoning predicted — "leak to CO (which
copies `status` through and never filters on it)" was true right up until #49.
Sister apps: `.ai/sister-app-notes/2026-07-17-under-review-removed.md`.

## Amendment (2026-07-18, #55 — bulk approve accepts a client selection)

The Consequences section said: *"Approval becomes a bulk operation over a
filtered view. The filter is the rule; there is no rule-authoring DSL."* The
route enforced that by re-applying the filter server-side and **ignoring** any
client-sent code list — the button approved the whole filtered set, nothing
less.

#55 adds per-row checkboxes: the filter narrows, the operator picks a subset.
That requires the POST to carry a code list, which the original design refused
to trust. The refusal is preserved by **intersection, not trust**: the server
recomputes `_filter_pending(...)` and accepts only `selected ∩ filtered-pending`.
A code that is stale, already a material, machinery, or outside the active
filter is dropped. A code that was never pending cannot be forced in by placing
it in the POST — verified by `test_injected_code_is_dropped`.

Two submit shapes:
- explicit `codes[]` — the checked rows, intersected as above;
- `select_all_matching=1` — no code list; reproduces the original whole-filter
  behaviour exactly (`_filter_pending` is the set).

"The filter is the rule" still holds as the **outer bound**: the filter defines
what *may* be approved, and the selection chooses within it. The filter can only
ever shrink the writable set, never grow it. No rule-authoring DSL was added;
the change is a subset selector over the same filtered view.

Single-row approval moved from an inline `<details>` form in the table cell to
a native `<dialog>` (the repo's first modal), posting to the unchanged
`/accept` route. Route + tests: `app/routes/catalog_discovery.py::bulk_accept`,
`tests/test_catalog_candidate_selection.py`. UI:
`.ai/features/2026-07-18-catalog-selection-modal/`.
