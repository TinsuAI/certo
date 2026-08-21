# Design review: catalog feature set vs the six-phase plan (#30–#35)

**Date:** 2026-07-11 · **Type:** review only, no code/issue edits · **Status:** uncommitted draft
**Inputs:** issues #30–#35, `brief.md` (this folder), ADR-0001, ADR-0002, session log
2026-07-10, the catalog code paths, CO's `data_hub_client.py`, local dev DB.

Everything below was verified against code (file:line) or the local DB on 2026-07-11,
except where marked "per brief" (claims re-used from the 2026-07-10 session that this
review did not re-measure: the 2.19s refresh timing, the 0.162s collapse prototype, the
0.88s/0.14s re-extract, the 392-undereived-codes count).

## A. Current flow map (what actually exists)

### Writers of `hub.materials` — five paths

| # | Path | Trigger | Writes | file:line |
|---|------|---------|--------|-----------|
| 1 | `derive_from_bcct` | BCCT upload **route only** (`routes/bcct.py:767`) | every non-empty `customs_code` → `status='active'`, `source='bcct_observed'`, `category='nvl'`, mode-UoM | `stores/provenance.py:44` (SQL at :23–76) |
| 2 | Excel upload / confirm | Danh Mục upload flow | `source='client_declared'`, status from file, provenance jsonb (`registered` / `user_added`) | `routes/catalog.py:886–935` |
| 3 | Candidate accept | UI form / `accept_candidate` | **default `status='under_review'`** (form default `routes/catalog_candidates.py:344`, store default `stores/catalog_candidates.py:669`), hardcoded `source='bcct_observed'` (:683); `on conflict` **overwrites** name/category/status of an existing row (:692–696); then `_auto_map_for_accept` inserts `code_mappings` (:653–659) | `stores/catalog_candidates.py:663–713` |
| 4 | Staff edit / tombstone / promote | catalog UI | edit sets any of `active/under_review/deprecated/tombstoned` (`routes/catalog.py:1014`, update :1021); tombstone action (:1317); promote flips `under_review`→`active` **and** `source='client_declared'` (:1060–1067) | `routes/catalog.py` |
| 5 | One-off scripts | operator | `scripts/fixup_johnson_btp_sx_after_bom.py` — the **only** writer of `source='bom_observed'` (3,822 rows); `scripts/accept_nvl_candidates_from_artifact.py` — the 1,207 bulk accepts, passed `status='active'` | scripts/ |

DB ground truth (2026-07-11): 13,631 rows, **all `active`**. By source/category:
bcct_observed 8,523 nvl + 668 tp + 421 btp_sx; bom_observed 2,615 btp_sx + 1,207 nvl;
client_declared 148 btp_sx + 44 nvl + 5 tp.

### `hub.catalog_candidates` — in and out

- **Refresh** (`stores/catalog_candidates.py:232–414`): scans BCCT + BOM + BQD, runs the
  Python paren extraction per row, `_collapse_unaffiliated_kinds` (:420–470), UPSERTs with
  sticky decision fields (:345–392), then **deletes** pending rows that no longer match any
  source (:393–412) — so `candidate_id` is unstable for pending rows.
- **Called from a GET page handler** (`routes/catalog_candidates.py:143`) on every load,
  including pagination; the comment above it still claims "cheap: sub-second" (:142).
  Measured 2.19–2.45s on Growatt per brief.
- **Transitions**: accept (:663), reject (:716), unreject (:730 — resets the candidate but
  leaves the inserted material and its auto-created `code_mappings`).
- DB ground truth: 4,513 rows = pending 3,306 (2,891 nb + 251 hq + 164 unified) +
  1,207 unified accepted. Zero rejected. Matches the brief's numbers exactly.

### Read surfaces that expose `materials` to CO

1. `GET /v1/hub/materials` and `/materials/{code}` (`routes/api.py:465`, `:506`) — **no
   status filter** (list has an opt-in `?status=`; get-by-code has none).
2. BCCT identity resolver (`resolvers/bcct_material_identity.py:120–133`) — builds its
   catalog `where m.client_id = %s` with **no status filter**, carries `status`, `name`,
   `category` into the payload CO fetches via `GET /v1/hub/bcct?include_material_identity=true`.
3. `app/data_promotion.py:91` — ships the whole `materials` table in the client bundle
   (candidates are deliberately not shipped; recomputed on destination, :158).

CO consumption (verified read-only): `list_materials` (`data_hub_client.py:79`),
get-by-code (:483, 404→`{}`), product roster = `category=='tp'` over the list with a
fallback **only when the whole list is empty** (:973–977), TTL cache of the catalog rows
(`co_case.py:540`). CO copies `status` through and never filters on it (:1095).

### Adjacent but unrelated

`routes/substitutes.py:91` calls a **different** `refresh_candidates` — the one from
`stores/material_substitutes.py:217` (substitute-pair candidates), behind a POST button.
Same function name, different table. Confusion hazard only; not a catalog-candidates
call site, and #32 does not touch it.

## B. Assessment of the six-phase plan

**The target shape is right.** ADR-0001's three-homes split (pending = derived → view;
reject = manual input → suppression table; accept = manual input → `materials` row) matches
what the data shows: pending rows are 100% recomputable (the refresh already deletes and
rebuilds them today), zero rejections exist, and every accept is already a `materials` row.
Discovery-as-view also deletes the stored derived stats (`observed_count`, `sample_text`,
`suggested_category`, … 28 columns) — which aligns with the standing rule that derived
values are computed, not stored. `bcct_nb_codes` is the one deliberate exception: a
persisted derivation, justified because SQL cannot express the extraction (mig 050) and
with a stated delete-and-rebuild invalidation policy measured ≈1s. Acceptable.

**Ordering is mostly right** (#33 blocked by #30; #34 by #33; #35 by #33+#34 — all real
dependencies: machinery marking needs the placeholder config + per-row attribution; the
view needs the link table; bulk approve needs marking + the view). Two order claims are
not supported; see C.8.

**Checked against the standing domain rules:**

- *Codes are multi-role; single-value `category` is impoverished* — the plan keeps
  `category` single-value; `roles[]` was rejected 2026-05-28 with evidence (mig 072) and
  the brief marks it do-not-revive. Consistent with the recorded decision. The tension is
  real but re-litigating it is out of scope here.
- *No derived values in source tables* — the plan is a net improvement (drops a table of
  cached derivations). ✓
- *Client-specific behavior in config/adapters* — the per-client placeholder set (#30) is
  exactly this. ✓
- *Never hard-delete without enumerating unreplayable buckets* — **#34 violates this as
  written.** See C.7.

## C. The mess, named

1. **Three lifecycle vocabularies encode fragments of one question.** "Has a human
   reviewed this code?" is spread across `materials.status` (5 enum values, only `active`
   ever used), `materials.source` (promote rewrites it as if provenance were approval,
   `routes/catalog.py:1060`), and `catalog_candidates.status` (pending/accepted/rejected).
   No single field answers it, and the fragments disagree — see 2.
2. **The trust ordering is inverted between paths.** A code that arrives via BCCT ingest
   is auto-inserted `active` with zero review (`stores/provenance.py:49`), while a code a
   human explicitly accepts enters as `under_review` (`stores/catalog_candidates.py:669`,
   form default `routes/catalog_candidates.py:344`). The unreviewed path yields the more
   trusted state.
3. **Interaction bug inside the plan's own phase window:** #31 as written filters
   `status='active'`; the accept form's default is `under_review`; so between phase 1 and
   phase 4 a staff-accepted candidate becomes a material **invisible to CO**, releasable
   only via `promote_material` — a route the brief itself documents as dead (0 rows →
   404s every call, brief :17–18). The critic's amended predicate
   (`not in ('tombstoned','inactive')`) dissolves this; `active`-only trips over it.
4. **Two leak surfaces, one in the ticket.** Dead rows reach CO through `/v1/hub/materials`
   (#31's scope) **and** through the BCCT identity resolver
   (`bcct_material_identity.py:120–133`, no status filter). #31's "closes risk 3" framing
   overclaims until the second surface is filtered or explicitly deferred.
5. **Placeholder handling is scattered and half-missing.** One predicate exists
   (`_is_missing_hq`, `parsers/catalog_candidates.py:27`, hardcoded `'.'`), two inline
   duplicates (`stores/catalog_candidates.py:611`, `routes/catalog_candidates.py:321`),
   and the one writer that matters — `derive_from_bcct` — has no check at all, which is
   what created the two junk `.` materials (3,509 Growatt + 13 Johnson placeholder rows
   feed it). #30 covers exactly this. ✓ verified 2026-07-11.
6. **A GET handler writes and deletes rows.** `candidates_page` → `refresh_candidates`
   upserts 3,306 rows and deletes/reassigns pending `candidate_id`s on every page view
   (`routes/catalog_candidates.py:143`; delete at `stores/catalog_candidates.py:393–412`),
   also invalidating any bookmarked candidate-detail URL. #32 covers the write-on-GET;
   the id instability dies with #34 (natural key in the view).
7. **#34 as written destroys unreplayable audit data.** Dropping `catalog_candidates`
   deletes the 1,207 accept decisions' `decided_by` / `decided_at` / `decision_reason`.
   The accepted *materials* survive, but the record of who/when/why does not — that is
   manual input, not derived data, and it cannot be recomputed. The repo's own wipe rule
   requires enumerating unreplayable buckets first. Fix inside #34's existing scope:
   before the drop, migrate the 1,207 decision tuples into the existing generic audit
   table (`bom_audit_events` pattern — add an event type; do not create a new audit
   table) or into `materials.provenance` jsonb.
8. **The plan's own documents disagree on ordering.** `brief.md:172` says "Do not reorder
   1 before 0", while `.ai/STATUS.md` says "Start here next session: issue #31" (phase 1).
   No mechanism forces 0 before 1: phase 0 touches ingest + two junk `active` rows, phase 1
   touches the read filter; they do not interact (the junk rows are `active`, so phase 1
   neither hides nor exposes them). The constraint is unexplained and one document must
   yield.
9. **Accept clobbers staff edits.** `accept_candidate`'s `on conflict` overwrites
   `name`, `category`, `status`, `code_kind` of an existing material
   (`stores/catalog_candidates.py:692–696`). A re-accept after a staff edit silently
   reverts the edit. Dies with #34; worth knowing until then.
10. **Ingest-path dependence** (per brief, risk 1): `derive_from_bcct` runs only in the
    upload route; script-loaded BCCT bypassed it, leaving 392 Growatt HQ codes out of
    `materials`. The discovery view (#34) will make these *visible* as pending — it does
    not fix the asymmetry, and the brief correctly defers reconciliation. Expect the
    pending count to be scrutinized when the view lands.
11. **Name collision:** two unrelated `refresh_candidates` functions
    (`stores/catalog_candidates.py:232` vs `stores/material_substitutes.py:217`), both
    imported in route modules. Zero-cost to note; rename opportunistically when #34
    deletes one of them.

## D. Verdict + recommendation

**Keep the six-phase plan. Amend two issues; do not restructure.** The architecture
decisions (ADR-0001/0002) survive contact with the code: every stored thing the plan
deletes is either derived (pending rows, cached stats) or preserved elsewhere (accepts →
`materials`), with the single exception in C.7. The phase cut is coherent and the declared
blocking edges are real.

**Amendments:**

- **#31** — adopt the critic's five changes, now reinforced by C.3: predicate
  `status not in ('tombstoned','inactive')` on both routes (keeps `under_review`/
  `deprecated` visible — `status` is not the approval gate, and CO's roster/name-resolution
  paths break on hidden rows); add `?status=` to get-by-code; positive test set
  (`under_review`/`deprecated` present, `inactive` absent, tombstoned omitted + 404,
  `?status=tombstoned` returns); scope note naming `bcct_material_identity.py:120` as a
  second, deferred surface with a follow-up issue; `API_CONTRACT.md` + `API_CHANGELOG.md`
  duty; demote the byte-identical line from safety claim to observation.
- **#34** — add: migrate the 1,207 decision tuples (`decided_by`, `decided_at`,
  `decision_reason`, code, kind) into `bom_audit_events` (new event type) or
  `materials.provenance` **before** dropping the table. Also already listed in #34 and
  confirmed real by this review: `unreject` not undoing accepts (:730), hardcoded
  `source='bcct_observed'` (:683), promote's wrong `source` semantics (`catalog.py:1060`).
- **File one follow-up issue** (out of the six): status-filter the BCCT identity resolver
  (`bcct_material_identity.py:133`) once the #31 predicate is settled, so both CO surfaces
  share one definition of "visible".
- **Resolve C.8 by declaring order** — recommendation: **amended #31 first** (verified
  twice this session, no config decision pending), then #30 (one decision: placeholder
  config placement; the brief's `text[]`-on-`hub.clients` recommendation is consistent
  with existing per-client config columns), then 2 → 3 → 4 → 5 as blocked. Update either
  brief.md:172 or STATUS.md so they agree.

**What to do first:** amend #31's text (the five critic changes), then `/implement` it in
a fresh context on a branch, commit referencing `Closes #31`. Everything else in the plan
stands as written.
