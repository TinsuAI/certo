# Feature: Catalog discovery — anti-join model, bulk approval, machinery exclusion

**Date:** 2026-07-10 · **Status:** Discovery, revised after `critic` pass + domain rulings
**Supersedes:** the first draft of this file (merge-into-`under_review` model)

Replaces the `catalog_candidates` table and its 739-line store with a computed
discovery view, adds a bulk-approval surface, and stops machinery part numbers from
entering the material catalog.

## Why

The catalog has **three** population mechanisms, not one:

1. `derive_from_bcct` (`stores/provenance.py:23`, called from `routes/bcct.py:767`) —
   auto-inserts every `customs_code` as `status='active'`, no review. Dominant path.
2. `catalog_candidates` + `accept_candidate` (mig 047) — the review queue.
3. `materials.status='under_review'` + `promote_material` (`routes/catalog.py:1050`) —
   **dead code**; 0 rows are `under_review`, so the route 404s on every call.

And the review queue is not used by humans. **100% of accepted candidates** were
approved by `scripts/accept_nvl_candidates_from_artifact.py` (`decided_by='bulk_nvl_accept_*'`,
1207 rows in 255 seconds). Zero manual approvals. Zero rejections, ever.

Meanwhile `refresh_candidates()` runs inside a `GET` handler
(`routes/catalog_candidates.py:143`) and costs 2.19s / 2.19s / 2.45s on Growatt,
scanning 39,203 `bcct_rows`, running Python regex per row, then 3,306 UPSERTs — on
every page load, with no data change.

## Domain rulings (user, this session — do not relitigate)

1. **HQ bucket codes are materials.** For dual-code clients, `customs_code` is often a
   grouping code (`LK-DAY2` → 158 NB codes, `DAUNOI` → 134, `DIENTRO` → 131; 520 HQ ↔
   2,846 NB, 141 buckets fan out). They stay in `hub.materials`. Consequence: BCCT
   signals **must not** be bridged from an HQ code to its NB children via
   `code_mappings` — that would attribute `LK-DAY2`'s entire declaration history to
   each of its 158 children. The paren extraction exists precisely for this.
2. **`customs_code = '.'` marks fixed-asset lines and must be excluded.** Growatt:
   3,509 rows, 100% `import` / `E13`, goods are BYD forklifts and storage racks.
   Johnson: 13 rows. Those lines also yield **218 NB codes, of which 210 appear only on
   fixed-asset lines** — forklift and rack parts. `declaration_type` is **not** the
   discriminator (Growatt has 102 `E13` rows with real codes; Johnson 4,260). The
   discriminator is the placeholder string, and it **must be per-client configurable**.
3. **`hq_registered` is tracking only.** Appearing on a declaration ≠ being registered
   with customs. The column exists (mig 042) but only 4 of 13,631 rows set it, two of
   which are demo seeds. `app/routes/api.py` never emits it; CO has never seen it.
   Declarability is assessed separately via `customs_relevance`. Do not gate behaviour
   on `hq_registered`.

## Scope

**In:**

- Per-client placeholder config for `customs_code`; one predicate, four readers
  (`_is_missing_hq`, `derive_from_bcct`, `_bcct_paren_pairs_for_nb`, `_co_occurring_codes`).
- `derive_from_bcct` skips placeholder lines. Delete the two junk `.` materials.
- Extend `customs_relevance` derivation: a code observed **only** on placeholder lines
  → `excluded_non_material`, with evidence. **Marked, not dropped** (user's call) — the
  8 codes seen on both line types show the boundary is not absolute, and CO trusts this
  field (`origin_material_filters.py:3`). Lands in Phase 3, once `bcct_nb_codes` makes
  the predicate expressible in SQL.
- Default `status='active'` on both `/v1/hub/materials` routes, plus a regression test.
- Move `refresh_candidates` out of the `GET` handler.
- `hub.bcct_nb_codes(client_id, transaction_key, line_no, nb_code)` — persist the paren
  extraction. Only for clients with parser rules; Johnson's half is empty.
- Rebuild `v_material_roles` on it; delete `stores/material_observations.py`.
- **Anti-join discovery model:** pending is a view; reject is a suppression table;
  accept is a row in `materials`. Drop `catalog_candidates` and its store.
- **Bulk approval UI** — the filter is the rule. First-class scope, not deferred.

**Out:**

- `category` → `roles[]`. Rejected 2026-05-28 with evidence (mig 072). Do not revive.
- Dropping the `unit` JSON alias — CO still reads it (`data_hub_client.py:1105`, `:1120`),
  six weeks past its 2026-05-25 sunset.
- `hub.v_catalog` as an enforcement mechanism — see Decision 5.
- BQD upload friction (`upload_initial_dispatch` never attempts a rigid parse before
  routing to the mapping page, so a first-time file shape always parks at
  `mapping_pending`). Affects all four modules; separate feature.
- Reconciling the 392 undereived HQ codes (see Risk 1) — separate, needs its own call.

## Decisions

1. **Pending needs no persistence.** "Which codes exist but are not in the catalog" is
   derivable: anti-join discovered codes against `materials` and a suppression table.
   The natural key `(client_id, code, code_kind)` is more stable than today's
   `candidate_id` bigserial, which `refresh_candidates` can delete and reassign
   (`catalog_candidates.py:395-412`). Accept and reject are both idempotent inserts.
2. **Reject is suppression, not a material state.** A rejected string was never a
   material, so `status='inactive'` on a `materials` row would assert something false.
   Rejections live in their own small table, which starts empty and probably stays that
   way. The `materials` CHECK has no `rejected` value and does not need one.
3. **`_collapse_unaffiliated_kinds` belongs in the view, not an ingest hook.** It asks
   whether a string ever co-occurs with a different code *anywhere in the corpus*
   (`catalog_candidates.py:420-470`). Per-row hooks would make `code_kind`
   order-dependent, breaking the repo's ingest-order-invariance guarantee.

   **Verified expressible in SQL, 2026-07-10.** Once `bcct_nb_codes` exists, co-occurrence
   is a self-join on `(transaction_key, line_no)` — both `text` columns. A throwaway temp
   table for Growatt (34,232 NB link rows) plus the collapse query ran in **0.162s** and
   reproduced the known answer: 0 strings carry more than one `code_kind`, 0 collapse.
   The prototype covered the BCCT co-occurrence source only; porting the full three-source
   union still needs care, but the shape and the cost are settled.
4. **Persist only the fact that is not already a column.** BOM codes are columns
   (`bom_edges`, `bom_artifact_rows`); BQD codes are columns (`code_mappings`); BCCT HQ
   codes are a column. The only non-columnar fact is the BCCT NB paren extract, and only
   for dual-system clients. Hence `bcct_nb_codes`, not a general link table.
5. **A view is not enforcement here.** The read API runs as Data Hub's own read-write
   role, so `SELECT` on `hub.materials` cannot be revoked. Choosing `v_catalog` over
   `materials` is exactly as forgettable as adding a `WHERE`. What cannot be forgotten
   is a regression test: tombstone a material, assert `/v1/hub/materials` omits it. Ship
   the default filter and the test; skip the view.
6. **The bulk-approve rule keys on "leaf corroborated by a fully-flattened artifact",
   not on `bom_role`.** `_bom_role_classification` reads `bom_edges`, which for Growatt
   contains only `non_flattened` artifacts (44,181 edges; the 538 flattened ones live in
   `bom_artifact_rows`, 72,168 rows). The two signals coincide for Growatt (2,157 codes,
   identical sets) only because its raw graphs happen to be fully expanded. A client with
   shallow BOMs would diverge, and `_suggest_category`'s refusal to trust `nvl_leaf`
   (`catalog_candidates.py:171-181`) would be right.
7. **Machinery codes are marked, not dropped.** `customs_relevance='excluded_non_material'`
   with evidence; still visible; excluded from bulk approve by default. Growatt has no
   `material_group` at all, so this gives it a classification path it currently lacks —
   with no API contract change, since CO already consumes `customs_relevance`.

## Risks

1. **Catalog state depends on ingest path.** `bcct_rows` holds 694 distinct
   `customs_code` for Growatt; only 302 became materials. `derive_from_bcct` runs only
   in the route (`bcct.py:767`), and part of Growatt's BCCT was loaded by
   `scripts/ingest_curated_xlsx_direct.py`, which bypasses it. So 392 HQ codes sit in the
   queue purely because of how their file was loaded. This is not designed behaviour.
2. **Bulk approval fires the mig-058 trigger once per row.** Approving 2,157 Growatt
   codes marks nearly every Growatt BOM artifact stale. That is the trigger working as
   designed, but it is heavy and must be planned — batch it, or suspend and recompute
   once. The `critic` pass called Phase 3 vestigial; it is not, the mass-fire risk simply
   moved from the merge to bulk approval.
3. **CO fails open on `status`.** `normalize_material_row` (`data_hub_client.py:1095`)
   copies `status` through with `row.get("status", "active")` and no call site filters on
   it. A latent leak already exists: `tombstone_material` (`catalog.py:1317`) sets
   `status='tombstoned'` and the read API has no filter. Never triggered, because no row
   is non-active.
4. **`promote_material` sets `source='client_declared'`.** Approving a code observed in
   BCCT does not mean the client declared it. Fix the semantics before reusing the route.
5. **`accept_candidate` hardcodes `source='bcct_observed'`** (`catalog_candidates.py:683`)
   even for BOM-origin codes. `bom_observed` has no live writer; Johnson's 3,822 such rows
   came from a one-off script.
6. **`unreject` does not undo an accept** (`catalog_candidates.py:730`). It resets the
   candidate row but leaves the inserted material and the auto-created `code_mappings`.
7. **`data_promotion.py:91`** dumps the `materials` table into the client bundle.
8. **Invalidation of `bcct_nb_codes`.** It derives from `bcct_rows × client_parser_rules`.
   A rule edit or a BCCT re-ingest invalidates it. Measured cost of a full re-extract:
   **0.88s for Growatt, 0.14s for Johnson.** So the policy is delete-and-rebuild per
   client, not an incremental staleness domain. (`critic` argued this would become a
   second Track-D; the measurement says otherwise.)

## Open questions

1. Where does the placeholder config live — a `text[]` column on `hub.clients`, or a
   per-client config table? Precedents exist for both (`clients.substitute_rules jsonb`,
   `hub.client_material_group_map`). Seeding must be guarded (`where exists (select 1
   from hub.clients …)`) or CI on a fresh DB goes red.
2. Accept provenance on `materials`: `promoted_by` / `promoted_to_declared_at` mean
   "promoted to declared". Bulk approval needs its own `approved_by` / `approved_at` /
   `approval_rule`, or a reuse decision.
3. What `source` does bulk approval write? It must reflect the originating stream, which
   today it does not.
4. Does the discovery view need `created_at` — "when our system first surfaced this
   code"? BCCT `first_seen` is recoverable; the surfacing timestamp is not. Probably not
   worth a table.

## Implementation order

Each phase ships independently. Do not reorder 1 before 0, or 5 before 2.

| # | Phase | Notes |
|---|---|---|
| 0 | Placeholder config + `derive_from_bcct` skip + delete 2 junk `.` rows | No API change, no CO impact (none of the 210 machinery codes reached `materials`). |
| 1 | Default `status='active'` on both read routes + regression test | No-op on current data (all rows `active`). Closes risk 3. |
| 2 | Move `refresh_candidates` out of `GET` | ~5 lines. Kills "GET writes to DB" and most of the 2.2s. |
| 3 | `bcct_nb_codes` + ingest hook + backfill; rebuild `v_material_roles`; delete `material_observations.py`; **machinery marking** | Backfill ≈ 1s total. |
| 4 | Anti-join model: discovery view + suppression table; drop `catalog_candidates` + store | The structural change. |
| 5 | Bulk approval UI | Needs 3 (marking) and 4 (view to filter). |

**Why machinery marking sits in Phase 3, not Phase 0.** Deciding that a code appears
*only* on placeholder lines requires per-row code attribution. For HQ codes that is a
column (`bcct_rows.customs_code`); for the 210 NB codes it is not — it needs the paren
extraction, i.e. `bcct_nb_codes`. Doing it earlier would mean re-running the Python
regex pass this work exists to remove. Phase 0 therefore only stops the `.` string from
becoming a material; the machinery *parts* stay in the queue until Phase 3, harmlessly
(none is a flattened-BOM leaf, so no current rule would approve them).

## Bulk approval — the surface

The filter **is** the rule. No rule-authoring DSL; the 2026-05-09 pivot away from the
`catalog_derive` wizard was a rejection of per-page regex authoring, not of automation.

- Discovery view gains signal filters: `leaf_in_flattened_bom`, `sources[]`,
  `observed_count`, `customs_relevance`, `code_kind`.
- One button: *"Duyệt N mã đang lọc"*, with a preview count and a sample.
- One audit event per bulk action, carrying the predicate, the count, and the code list.
  `decided_by` is the user, not a script name.
- `excluded_non_material` is filtered out by default.
- A human presses the button. No standing rules that run at ingest — that is the wizard.

Expected effect on Growatt: 3,306 pending → 2,157 approvable by the flattened-leaf rule,
210 marked as machinery, leaving ~939 for per-item review. The residue is the tail, not
the main event.

## Manual test plan

1. **Phase 1 is a no-op.** Snapshot `GET /v1/hub/materials?client_id=growatt-vn` before
   and after; byte-identical. Same for Johnson.
2. **Tombstone leak closed.** Tombstone a material; it disappears from
   `/v1/hub/materials`, and reappears with `?status=tombstoned`.
3. **No junk material.** After Phase 0, `select * from hub.materials where material_code='.'`
   returns zero rows for every client, and re-running a BCCT ingest does not recreate it.
4. **Machinery marked, not lost.** The 210 fixed-asset-only NB codes carry
   `customs_relevance='excluded_non_material'`, are visible in the UI, and are absent
   from the default bulk-approve selection. The 8 shared codes are **not** marked.
5. **Placeholder is config, not code.** Set a second client's placeholder to `-`;
   its `-` rows behave as Growatt's `.` rows. No literal `'.'` remains in shared code.
6. **Extraction parity.** For 20 sampled Growatt BCCT rows, `bcct_nb_codes` equals what
   `candidates_from_bcct_row` returns. Zero diffs.
7. **View blind spot closed.** Pick a Growatt NB code that appears only in `goods_name`
   parens. Before Phase 3 `v_material_roles` returns no observations; after, it matches
   what `material_observations.py` used to compute.
8. **No writes on GET.** After Phase 2, load the candidates page and assert zero rows
   written to any table.
9. **Bulk approve.** Filter to the flattened-leaf rule, approve, and assert: 2,157
   materials created, one audit event with the predicate, `decided_by` = the operator,
   and a planned (not accidental) BOM staleness recompute.
10. **CO unaffected.** Load a Growatt C/O case before and after Phase 4; the material
    catalog index contains the same codes.

## Done criteria

- `hub.catalog_candidates`, `app/stores/catalog_candidates.py`, and
  `app/stores/material_observations.py` no longer exist.
- No `GET` route handler writes to the database.
- `/v1/hub/materials` never returns a non-`active` row unless `?status=` asks.
- No `'.'` literal, or any client placeholder, in shared ingest code.
- `hub.materials` has no `DELETE` path outside migrations.
- Suite green, plus new tests for: extraction parity, status default, machinery marking,
  placeholder config, `code_kind` collision raising rather than silently picking.
- UI proof committed under `.ai/features/2026-07-10-catalog-candidates-merge/screenshots/`
  with `ui_smoke.py` in the same folder.

## Sister-app coordination

- **CO** (`~/workspace/client/barry-CO-main`) — the only live consumer, verified by direct
  read. No call to `/v1/hub/code-mappings` (0 hits in `.py`); no `under_review` handling
  (0 hits); no `status` filter; only `category != "tp"` (`:978`). It **needs no change**
  provided Phase 1 ships first. It already consumes and trusts `customs_relevance`, so
  Phase 0's machinery marking reaches it with no contract change. It still reads the
  deprecated `unit` alias, so that alias stays. Write a note to `.ai/sister-app-notes/`.
- **BCQT** (`~/workspace/client/BCQT-System`) — **not a consumer.** Verified: 0 references
  to `hub.*` or `/v1/hub` in tracked code, no Postgres driver. It builds its catalog from
  its own SQLite `material_registry`. When the hub-consumer rebuild lands it must read the
  filtered surface, not the raw table.
- **BQD / `code_mappings`** — CO deliberately removed this dependency
  (`docs/co-data-hub-link.md:59`). It stays internal to Data Hub: discovery, `code_kind`
  backfill, mapping-drift warning, BCCT resolver. Growatt needs it (2,892 rows, loaded by
  script — both real BQD uploads are still stuck at `mapping_pending`); Johnson is a
  unified-code client and has none.

## Next step

`/tdd` on Phase 0 and Phase 1. Phase 0 has a sharp oracle (the two junk rows disappear and
do not come back; the 210 codes get marked; the 8 shared ones do not). Phase 1's oracle is
a byte-identical API response.
