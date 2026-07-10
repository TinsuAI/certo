# Backlog — FROZEN 2026-07-10

**This file is a historical record. Do not add work items to it.**

Open items were migrated to GitHub Issues on `TinsuAI/data-hub` (#14-#35), which is now
the single ticket store. Shipped and deferred entries stay below, unedited, the same way
`.ai/DECISIONS.md` holds decision history. See `docs/agents/issue-tracker.md`.

---


Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>/brief.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

Audited 2026-05-13 — open items grouped by theme; shipped items moved
to the bottom log with brief annotation.

---

## Themes (TOC)

- [A. Catalog & material identity](#a-catalog--material-identity)
- [B. BOM upload & adapter infrastructure](#b-bom-upload--adapter-infrastructure)
- [C. Sister-app coordination](#c-sister-app-coordination)
- [D. Aggregate data history](#d-aggregate-data-history)
- [E. Architectural follow-ups](#e-architectural-follow-ups)
- [F. Data operations](#f-data-operations)
- [G. Polish & independent items](#g-polish--independent-items)
- [Shipped — kept for context](#shipped--kept-for-context)
- [Notes](#notes)

---

# A. Catalog & material identity

Cluster of catalog data-quality work captured 2026-05-09 (Mã chờ duyệt
session). Phase 1 of catalog multi-source SHIPPED (provenance, observed
roles, candidate feed, candidate richness). Phase 2 + supporting items
remain open. Identity-resolution items (parser-rules, paren-extract)
sit here too because they share the catalog data graph.

## A.0 Material Group + declarability (mig 078+079) — SIGNED OFF 2026-06-13; pushed; demo/prod backfill + CO adoption pending

**Captured 2026-06-09.** Branch `feat/bom-material-group-declarability` (pushed
2026-06-13; mig 078+079 applied on local dev DB only — demo/prod NOT yet). `/rev` done → found a Critical import-blind
bug, fixed by **mig 079** (import wins over MG; RD07 drawing→assembly_set; backfill
made re-runnable/import-aware; parity test added). Suite 1456 passed; verified 0
imported materials excluded. Remaining:
- **Owner signed off 2026-06-13** → branch rebased on main + pushed. Demo/prod
  mig-apply + backfill and CO adoption remain (gated, deliberate).
- **Follow-up (deferred):** precise drawing auto-hide — RD07 drawings currently
  surface as `declarable_unmatched` (review), not auto-excluded, because the SAP
  group is overloaded and ~704 lack a name in catalog_candidates. Needs name-level
  classification at ingest.
- Gates C.x (CO `customs_relevance` adoption —
  `.ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md`).
Detail: `.ai/features/2026-06-08-leaf-nvl-declarability/brief.md` (STATUS).

## A.1 Phase 2 catalog — CLOSED 2026-05-28 (dead-code drop, not refactor)

**Captured 2026-05-09**. Original plan: replace single-value `category`
+ `category_override` patch with multi-role `roles[] text[]`. ~2-3 days
cross-cut refactor.

**Closed without doing the refactor.** Discovery 2026-05-28 found:

- `category_override` + `override_reason` (mig 002 scaffold) were a
  "patch instead of edit" design from before mig 045 audit trigger and
  the A.3 edit form supplanted them. The UI to set overrides was never
  built (session 2026-05-01 to-do #11, dropped on the floor).
- Data audit on local dev DB: **0/13,589 rows** across Growatt + Johnson
  have either column set. Dead architecture, not active hack.
- `observed_roles[]` (mig 046) already surfaces multi-role truth at the
  view level. The 421 observed-multi-role rows render "Đa nguồn" badge
  today without any declared-side change.
- Declared/observed conflict count: **1** out of 13,589. The hypothetical
  pain `roles[]` would resolve does not exist in current data.

**Mig 072 shipped** (2026-05-28): drop both columns + recreate
`v_material_roles` without `coalesce(override, category)`. ~30 min,
not 2-3 days. Phase 3 declared multi-role deferred until a concrete
staff workflow blocker appears. See
`project_bom_code_multirole.md` memory revision.

Manual fields (item 2 of the original plan: `hq_registration_no`,
`hq_registration_date`, `supplier_hint`, `name_source`, `uom` — `uom`
already shipped via mig 063) tracked separately if/when needed.

## A.2 Catalog conflicts page — SHIPPED 2026-05-15

Dedicated review queue at `/clients/<cid>/catalog/conflicts` surfacing
both `declared_observed_conflict` (column on `v_material_roles`) and
sourcing-confirmation conflict (Python/SQL-derived from
`btp_sourcing` vs observed `observed_roles[]`). Inline `btp_sourcing`
dropdown with `return_to` redirect to keep staff on the queue.
Catalog list shows a "X dòng cần review" nav banner when count > 0.
Brief: `.ai/features/2026-05-15-catalog-conflicts-page/brief.md`.
+8 provider tests (1101 passed). No suppress mechanism — staff
resolve by editing declared category or btp_sourcing (immutable
principle, [[feedback_no_derived_in_source]]).

## A.3 Catalog edit permission (per-role configurable)

**Moved to [#14](https://github.com/TinsuAI/data-hub/issues/14)**. Full text lives in the issue. Do not edit here.

## A.4 Catalog material detail — cross-source inconsistency warnings

**Moved to [#15](https://github.com/TinsuAI/data-hub/issues/15)**. Full text lives in the issue. Do not edit here.

## A.4.2 Substitute XLSX bulk upload (P1 client_confirmed)

**Moved to [#16](https://github.com/TinsuAI/data-hub/issues/16)**. Full text lives in the issue. Do not edit here.

## A.4.3 Smarter goods_name similarity (insignificant-diff folding)

**Moved to [#17](https://github.com/TinsuAI/data-hub/issues/17)**. Full text lives in the issue. Do not edit here.

## A.4.4 Convertibility-aware UoM divergence (accept convertible, flag only incompatible)

**Moved to [#18](https://github.com/TinsuAI/data-hub/issues/18)**. Full text lives in the issue. Do not edit here.

## A.5 v_material_roles paren-aware (replace material_observations workaround)

**Moved to [#33](https://github.com/TinsuAI/data-hub/issues/33)** (folded into catalog phase 3). Full text lives in the issue. Do not edit here.

## A.6 Scripts that lost SQL `material_identity` access (deferred 2026-05-08)

Mig 038 dropped `bcct_rows.material_identity` jsonb column. Three
scripts that did SQL-side `material_identity->>...` access now fall
back to `customs_code` only — degraded for Growatt-style imports
where the agency NVL code lives in goods_name parens.

1. **`scripts/settlement_resolver.py::_load_bcct_universe`** — used to
   collect distinct internal codes from BCCT rows for BCQT-side
   settlement matching. Now returns customs_code only. Rewrite to
   call `compute_internal_code(row, client=client)` per row in Python,
   then dedup. ~30 min.
2. **`scripts/detect_dual_source_btps.py`** — classifier for
   "imported BTP that's also self-produced". Used `material_identity`
   to match `b.<computed>=m.customs_code` for the import-count
   subquery. Now uses `b.customs_code = m.customs_code` only —
   under-counts Growatt imports because customs_code is the HQ-side
   "DOV"/"TEM.IN" bucket, not the agency NVL code in parens.
   Rewrite needs Python-side compute per row + GROUP BY in code.
   ~1h.
3. **`app/agent/tools.py::_query_bcct`** — agent tool that surfaced
   `internal_code` to the LLM for natural-language BCCT lookup. Now
   omits the field. Agent can still infer from goods_name. Lower
   priority — rewrite when agent feature ramps up.

All three are at the SAME architectural pinch-point: SQL-side
aggregation over jsonb that's no longer there. Generalized fix:
materialized view that re-derives material_identity for analytics
queries. Defer until performance pain emerges. Tightly coupled with
A.5 (same root cause).

---

# B. BOM upload & adapter infrastructure

Cluster around the BOM upload flow: UX polish, parser robustness,
adapter framework. Auto-detect default + manual_flat 4-shape SHIPPED
2026-05-13; remaining items below.

## B.0 Adapter "module management" + format-variant-as-data — items 1+2 SHIPPED 2026-06-14; item 3 open

**Driver:** concern that the BOM/declarability work over-fits Johnson + these
SAP technical BOMs, and that new formats/customers force per-case rework → a
messy, hard-to-control codebase. Investigation showed the worry is mostly
addressed already (`app/parsers/bom_adapters/__init__.py` is a real plugin
registry: `BomAdapter` Protocol + `register()` + detect-ranked `parse_with_fallback`
+ pluggable `HOOKS`; core/engine/routes import NO specific adapter). "In the repo"
≠ "coupled to core". Status per item:

1. **Read-only "Adapter registry" admin view** — ✅ SHIPPED (`fc48a96`, PR #3).
   `GET /admin/bom-adapters` (`app/routes/admin.py:293`) renders
   `bom_adapters.registry_info()` + `adapter_binding.list_bindings()`; linked from
   `_admin_nav.html` ("Adapter BOM"). Visibility + per-client binding matrix, no
   runtime code upload — exactly as scoped.
2. **Format-variant → DATA, not code.** — ✅ SHIPPED (`fc48a96`). `client_column_aliases`
   (mig 075) + group-map UI + per-client default-adapter binding (`POST
   /clients/{id}/bom/default-adapter`, `bom.py:210`). Tree-adapter binding path also
   fixed to land as raw_graph (`017c4ea`, see G.2). Most "new format from an existing
   customer" now needs ZERO code.
3. **Tighten + document the adapter contract** as THE extension point: make
   `detect()` mandatory; add capability metadata. New structural format = 1 adapter
   file + tests + deploy (git/CI-governed). Document this onboarding flow. **OPEN** —
   `detect()` ranking exists (`f161f12`, B.1) but stays optional/abstain (not
   mandatory) and there is no capability metadata yet. Only remaining B.0 work.
4. **DO NOT build runtime .py upload** ("dev a module, upload it, hot-add"). It is
   RCE-by-design, bypasses CI, crash blast-radius, ungoverned versioning — it
   *increases* the chaos. Defer entry-point/package-based boot-time loading until
   a real forcing function (non-Tinsu adapter authors, or >10 formats added often).
   Decision recorded in DECISIONS 2026-06-09.

## B.0b Declarability generalization follow-ups (captured 2026-06-09)

**Moved to [#19](https://github.com/TinsuAI/data-hub/issues/19)**. Full text lives in the issue. Do not edit here.

## B.1 Modular BOM ingest adapters (per supplier shape)

**Moved to [#20](https://github.com/TinsuAI/data-hub/issues/20)**. Full text lives in the issue. Do not edit here.

## B.2 UI BOM upload — wire up v3 concepts (Phase 3c follow-ups)

**Moved to [#21](https://github.com/TinsuAI/data-hub/issues/21)**. Full text lives in the issue. Do not edit here.

## B.3 BOM/BQD/Catalog parse-error UX — BOM side SHIPPED 2026-06-07

**BOM side SHIPPED 2026-06-07.** The 5 parse-error `HTTPException(400)`
sites in `bom.py::upload_submit` (auto no-match, technical_raw, rigid,
LLM-unavailable, LLM-mapping-rejected) now return
`_render_parse_error()` → `clients/bom_upload_error.html` (status stays
400, body is friendly HTML with recovery options + re-upload link) instead
of raw FastAPI `{"detail": ...}` JSON. The `Invalid profile` validation
guard intentionally stays a bare 400. **BQD/Catalog parse-error paths NOT
yet converted** — same treatment still open for them.

Original note (kept for the BQD/Catalog remainder):
Phase 2 universal preview-confirm pattern surfaces parsed
rows nicely when parsing succeeds. But when the parser rejects the file
outright (no LLM available, or LLM also fails), `app/routes/bom.py`
still raises `HTTPException(400, ...)` which the browser renders as raw
FastAPI JSON `{"detail": "..."}`.

Compare BCCT's `parse-mapping` error path which renders a proper
template with recovery options.

**Fix:** catch the final parse-error path and render an error template
or redirect with a `?error=...` toast (matching the post-upload toast
pattern from `c77da85`). Auto-detect 2026-05-13 already returns a
friendly Vietnamese 400 message but the rendering as raw JSON detail
remains.

## B.4 Manual mapping UI when LLM disabled

**Moved to [#22](https://github.com/TinsuAI/data-hub/issues/22)**. Full text lives in the issue. Do not edit here.

## B.5 Unified import UX across all data-import surfaces

**Moved to [#23](https://github.com/TinsuAI/data-hub/issues/23)**. Full text lives in the issue. Do not edit here.

## C.1 CO + BCQT — adopt service-account JWTs

**Moved to [#24](https://github.com/TinsuAI/data-hub/issues/24)**. Full text lives in the issue. Do not edit here.

## C.1.a BCCT by-codes — soak test under real CO load

**Moved to [#25](https://github.com/TinsuAI/data-hub/issues/25)**. Full text lives in the issue. Do not edit here.

## C.2 API auth — flip dev-permissive reads to strict by default

**Moved to [#26](https://github.com/TinsuAI/data-hub/issues/26)**. Full text lives in the issue. Do not edit here.

## C.3 Drop BOM vocab v1 aliases — SHIPPED 2026-05-28

3-week grace period elapsed; sister apps verified clean of old URL
refs (CO + BCQT, `grep -rn "bom/version\|bom/versions"` zero hits).
`_alias_*` handlers in `app/routes/bom.py` + `app/routes/api.py`
deleted, the 3 redirect tests in `tests/test_bom_vocab_rename.py`
removed (schema + ID-prefix tests retained), `docs/API_CONTRACT.md`
alias section removed, `docs/API_CHANGELOG.md` Breaking entry added.

## C.4 `/v1/hub/products` — real `total` + cursor pagination (DEFERRED)

**Captured 2026-06-07** from CO API request
`barry-CO-main/.ai/api-requests/2026-06-07-products-total-count.md`.

`GET /v1/hub/products` is hard-capped at 50 with `total_estimate: null`
and no `next_cursor` — the route (`app/routes/api.py:1631`) calls
`list_products_with_bom(client_id, q=q)` with default `limit=50,
offset=0`, never honors a `cursor`/`limit`, never calls the existing
`count_products_with_bom()`. So any consumer that enumerates products
is silently truncated.

**The store layer already supports it** — `list_products_with_bom`
takes `limit`/`offset`, and `count_products_with_bom` returns an exact
count. The fix is route-wiring only:
1. Accept `cursor` + `limit` query params (validate → `400 invalid_cursor`
   / `400 invalid_limit`; server max e.g. 1000). Reuse the `_page_args`
   offset-cursor idiom already in the file.
2. Fetch `limit+1` to detect a next page; emit `next_cursor` (offset
   string) when more remain, else null.
3. Add `total = count_products_with_bom(client_id, q=q)`; keep
   `total_estimate` populated with the same value for back-compat.
4. Add `server_time`. Item payload unchanged.
5. Provider tests: exact `total` across pages, `next_cursor` non-null
   until last page, `sum(len(items)) == total` no dups, `limit` honored,
   negative cases (bad cursor/limit, scope/client 403), edge cases
   (0 products, exactly page-size, > page-size).

**Population note:** `/products` enumerates BOTH tp + btp products with
an alive (non-tombstoned) BOM artifact — `total` must match that
population (sum of `len(items)`). If CO specifically wants "# thành
phẩm (tp) có BOM" that is the `bom.product_count` in source-summary
(see the source-summary `bom` block work, shipped separately).

**Status: DEFERRED 2026-06-07.** CO does not need product enumeration
this way yet — its BOM dashboard headline is served by the
`source-summary.bom` block instead. Pull this out when a consumer
actually needs to page the full product list, or when the silent 50-cap
bites someone. ~2-3h (route + validation + tests).

---

# D. Aggregate data history

Single big-ticket item — generalizes the BOM immutability principle
(memory `project_bom_immutable_principle.md`) to other aggregate
tables. Touches every mutable hub table.

## D.1 Aggregate-data git-history

**Moved to [#27](https://github.com/TinsuAI/data-hub/issues/27)**. Full text lives in the issue. Do not edit here.

## D.2 BOM staleness — Scope A SHIPPED 2026-06-08; Scope B (fingerprint rebuild) DEFERRED, revisit-if

**Captured 2026-06-07** during A.4.4 discovery. Split into two scopes after a
critic review 2026-06-08. Brief: `.ai/features/2026-06-08-bom-staleness-fingerprint/brief.md`.

**Problem (original):** trigger-push + binary flag — D1–D9 plpgsql triggers set
`is_stale`/`has_uom_drift` on every source change. Two faults: (1) whack-a-mole
false positives (mig 069/070/071 = three narrowings of the same leak); (2)
`is_stale` conflates "an input changed" with "the output is now wrong".

**Scope A — narrow fix — ✅ SHIPPED 2026-06-08** (mig 077, commit `f17e405`
"D.2-A"). Widened `hub.has_drift_remaining` to mirror `classify_uom_relation`
(alias + per-material/client-wide override either direction + same-family
`base_factor` + tier-A 1:1 → not-stale; tier-B + unknown token → stale). D7/D9
triggers call it by name. Backfill clears now-resolvable flags. Parity guard
`tests/test_has_drift_remaining_parity.py`. **This killed fault (1)** — the
concrete cry-wolf pain that motivated the rebuild. Convertible catalog edit
(kg→g) no longer churns published rows.

**Scope B — input-fingerprint rebuild — DEFERRED, critic-rejected as proposed.**
The big-bang "replace all 9 triggers with stored `input_fingerprint` +
derive-on-read" design was flagged 2026-06-08 as **over-built in the wrong
direction** (verified against code). NOT planned work — a *revisit-if* gated on:
- **No family-canonical normalizer** — `uom.py` resolves only pairwise; the
  fingerprint needs a new single-arg "normalize qty to family base" primitive.
- **Guarantee downgrade (the killer)** — triggers observe *every* write
  (psql/script/bulk re-ingest, documented workflows); app-hook + Python recompute
  silently under-flags on bypass paths until a cron that **does not exist** (mig
  062 `background_jobs` is a subprocess tracker, not a scheduler). For a TT
  39/2018 product feeding CO/BCQT, under-flag is a worse failure class than the
  triggers' over-flag.
- **Fan-out cost** — `reconcile_for_material` caps at 50 / reports `deferred`;
  sync full-tree re-derive needs a real job queue first.
- **Float-hash instability** (`normalized_hash` rounds float) + **unknown-token
  sentinel** (adding an alias would flip the hash = NEW false positive).

Fault (2) remains conceptually true but is now *aesthetic*, not real maintenance
pain (Scope A removed the leak). **If B is ever revived**, use the hybrid shape:
a thin trigger that only stamps `fingerprint_dirty=true` (keeps universal cheap
write-observation) + an off-path worker (all-Decimal quantized arithmetic, stable
unknown-token rule, backfill that preserves genuine staleness). **Revisit only
when a job queue exists OR the trigger-push model causes real (not aesthetic)
maintenance pain.** Trigger-push stays the working model until then.

---

# E. Architectural follow-ups

Items captured during /rev cycles or sprint retros that didn't make
the original cut. Smaller individually; bundle when convenient.

## E.1 Sprint D — parser/data architectural follow-ups (post-Sprints A/B/C)

**Moved to [#28](https://github.com/TinsuAI/data-hub/issues/28)**. Full text lives in the issue. Do not edit here.

## E.2 Phase 3 review follow-ups (deferred 2026-05-07)

Captured during /rev of commits `5fb814a..dadbd0f`. Four Minor
findings deferred — low value individually, batch when convenient.

1. **Catalog matching column ≠ classifier matching column.**
   *Superseded 2026-05-09 by A.5 "v_material_roles paren-aware" entry
   above — same root cause, more concrete plan + workaround link.*
2. **`api_create_preset` body validation thin.** No name length
   cap, no whitespace strip, no charset restriction. Add
   `name = body["name"].strip()` + max length guard (e.g. 64).
3. **PATCH preset has no `updated_at` audit.** Mig 030 schema only
   has `created_at`; PATCH overwrites silently. Add
   `updated_at timestamptz` column via fresh migration; auto-touch
   in PATCH endpoint.
4. **`derive_btp_shallows` count-before/count-after `created` flag.**
   Fragile under concurrency. OK for single-threaded CLI.
   Migrate to `RETURNING xmax = 0` (Postgres-native "was this an
   insert?") if running multi-process becomes a thing.

## E.3 Parser-rules infra polish (deferred 2026-05-08)

Captured during the configurable-bcct-parsing bundle session
(commits `046601e..9dbbbca`). Core CRUD + UI + 3 test panel modes
shipped; below are nice-to-haves deferred:

1. **Playwright E2E** for `/clients/<id>/parser-rules` flow:
   create rule → test panel preview → disable → audit history.
   Memory `feedback_feature_folder_with_screenshots.md` requires
   committed screenshots for UI features.
2. **Per-key cache invalidation** for `_RULES_CACHE` in
   `app/parsers/client_parser_rules.py`. Currently any rule edit
   calls `clear_rules_cache()` which drops all cached entries
   process-wide. Benign at current scale (~5-10 clients × 1-2 output
   fields), but per-key drop would scale better.
3. **`preview_token` mechanism** on rule create/update endpoints
   (brief R2 belt-and-suspenders). Save-time would require user to
   have run preview within last N minutes against the same pattern.
   Defer until first real-world misconfig surfaces.
4. **CI workflow: soft-fail LLM `/models` smoke step** — ✅ DONE
   (verified 2026-06-08). The `Smoke LLM /models (best effort)` step in
   `.github/workflows/ci-cd.yml` already carries `continue-on-error: true`
   AND wraps the probe in `if curl ...; then ... else echo non-blocking; fi`,
   so a `/models` 401/timeout can no longer redden the run. Both fixes the
   item asked for are in place. Note: the recent red CI runs (2026-06-08)
   were NOT this step — they were a genuine Docker build failure
   (`COPY CHANGELOG.md` blocked by `.dockerignore *.md`, fixed in `00ab911`).
   The self-hosted runner does `git reset --hard origin/main`, so a run
   builds whatever is latest on main at execution time, not the triggering
   commit — which is why those failures looked mis-attributed.
5. **Memory updates** — pending verification across sessions:
   - `internal_code` + `material_identity` columns gone; live via
     runtime helpers.
   - Hardcoded growatt regex replaced by `hub.client_parser_rules`.
   - BCCT field semantic split: FX (`*_nt`) vs VND domains.
   - Resolver Stage 2 (paren-extract) wins over Stage 1 (customs).
   - Payload jsonb sparse; typed columns are source of truth.

## E.4 /rev cross-cuts (still open)

**Moved to [#29](https://github.com/TinsuAI/data-hub/issues/29)**. Full text lives in the issue. Do not edit here.

## F.1 Growatt programmatic bulk re-ingest — SHIPPED 2026-05-28 + 2026-05-29

Both halves delivered (see "Shipped" section for the full record):
- **BCCT** — Growatt onboard session 2026-05-28 (`ccbb3ad`), incremental
  ingest.
- **BOM** — wipe + re-ingest 2026-05-29 (`03e9c4b`): 57 TP raws from 3
  source batches → 212 BTP raw_graphs derived → 269 raw_graphs × 3 shapes
  = 807 published artifacts, + 16 manual_flat restored from snapshot
  (no XLSX source to replay) = 823 artifacts on local + demo. 1260 tests
  pass. Session log: `.ai/sessions/2026-05-29-growatt-bom-wipe-reingest.md`.

The `scripts/bulk_reingest.py --client <id>` generalization (fold Johnson
+ Growatt into one tool) was **not** built — both ran via the existing
per-step scripts. Capture as a fresh item if a third client makes the
duplication worth abstracting.

---

# G. Polish & independent items

Smaller items not yet themed into a cluster.

## G.1 Redesign navigation menu — SHIPPED 2026-06-14 (admin bar)

**Captured 2026-06-14.** User: *"Thiết kế lại menu điều hướng các thứ cho
chuẩn."* The admin button-bar was an ad-hoc pile — `admin/users.html` had a
6-link `btn-secondary` row; the other 6 admin pages each hand-rolled a
*different* "← prev / next →" set; `/admin/settings/embedding` was orphaned.

**Shipped:** one shared `app/templates/_admin_nav.html` with **grouped
dropdowns** (user pick, mirrors the per-client `_client_nav.html` `<details>`
idiom): Người dùng · Dữ liệu tham chiếu(▾ Mã loại hình / Preset DNCX / UoM) ·
Adapter BOM · Hệ thống(▾ Service tokens / Cài đặt kỹ thuật / Embedding, dev-only).
Self-highlights from `request.url.path`; reuses `.tabs`/`.nav-menu` CSS (only
add: `.admin-tabs` to the `overflow:visible` override). Wired into all 8 admin
templates, divergent link rows removed, orphaned Embedding page now linked.
3 tests (`tests/test_admin_nav.py`), 1480 passed. Brief + screenshots:
`.ai/features/2026-06-14-nav-redesign/`.

**Not touched (didn't need it):** per-client nav already grouped; global topnav
already separates the Admin chip from the client tab bar. If a future admin
surface lands, add one `<a>` to `_admin_nav.html` (promote Adapter BOM into a
"Nhập liệu" dropdown when a 2nd ingest-config surface appears).

## G.2 Per-client adapter binding — explicit-path tree-adapter gap — SHIPPED 2026-06-14

**Captured 2026-06-14** during B.0 review. The tree-adapter → raw-edges reroute
(`90ba345`) lived ONLY in the `if profile == "auto"` branch, so pinning a tree
adapter (`sap_indented_walk` / `multi_sheet_per_root`) via the per-client binding
or manual dropdown took the explicit-profile path → flat-stash, flatten silently
skipped (MPL0100-39) — *worse* than `auto`.

**Fixed (option a):** extracted `_tree_adapter_needs_raw_edges(blob, adapter,
root_hint)` in `app/routes/bom.py` (tree adapter AND a raw-edge parser also
matches → reroute to `technical_raw`). Applied to the explicit-profile path
(before the `auto` block) AND refactored the `auto` block to share it, so any
tree-adapter selection — auto, bound, or hand-picked — lands as raw_graph with
the materialize hook. No-regression: returns False when the file isn't
raw-edge-parseable. 2 tests in `tests/test_bom_ingest_followups.py` (helper unit
+ end-to-end confirm → `non_flattened` artifact). 1480 passed.

**Still open (minor, deferred):** binding is a UI pre-select only —
`upload_submit` server default stays `manual_flat` and programmatic/API ingest
ignores the binding. Low impact (the form always submits the chosen profile);
fold into a future binding-hardening pass if it bites.

---

# Shipped — kept for context

Recent ships (2026-05-09 onward) annotated for cross-reference. Older
ships are in the legacy "Notes" section at the very bottom or removed
per `git log .ai/BACKLOG.md`.

## BOM UoM conversion engine (Phase 2 + Phase 3) — SHIPPED 2026-05-12 + 2026-05-13

**Phase 2** brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`.
Migrations 055-058. 18 commits + UX polish. +103 tests. Sub-tasks A
(ingest preview), B (refresh wires UoM), C (`client_uom_overrides`
admin UI), D (audit trail) all delivered.

**Phase 3 follow-ups** (E manual_flat drift signal + F
refresh-as-supersede + G refresh-time preview):
- E + F folded into Phase 2 ship (brief items 2/3/6).
- G shipped 2026-05-13: `plan_refresh()` pure planner +
  `commit_refresh()` with `skip` + `edits` params; GET preview route
  + template; POST extensions for skip/inline_factor; UI swap to GET
  preview default; no-op detection with "Xác nhận đã xem". 18 new
  tests. Reused `hub.bom_audit_events` (mig 006) for `refresh.skipped`
  events — no new audit table. Brief:
  `.ai/features/2026-05-13-bom-refresh-preview/brief.md`.

## UoM standardization table — SHIPPED 2026-05-10

Mig 051 + `app/stores/uom_standards.py`. Reused existing
`hub.uom_canonical` + `hub.uom_aliases` (mig 021); extended with 10
new canonicals + ~50 aliases covering real BCCT data. Wired into
`_uom_drift` warning (only fires on real semantic conflict) and
candidate refresh (canonical buckets, not raw alias counts).

**Per-agency override (`client_uom_aliases`)**: NOT shipped — deferred.
Only needed when an agency uses an alias that conflicts with another
client's canonical mapping.

**Admin UI polish — DEFERRED 2026-05-10** (user: "chưa hài lòng lắm,
sẽ quay lại sau"). Pending improvements: edit canonical inline;
delete with FK protection; conversion factor explorer; group aliases
under canonical; per-client `client_uom_aliases` override + UI;
better empty-state; tooltip / docs explaining `base_factor`.

## Mã chờ duyệt — passive candidate feed — SHIPPED 2026-05-09

Mig 047 created `hub.catalog_candidates` + `hub.catalog_candidate_rejections`
+ added `hub.materials.production_source` enum. Route
`/clients/<id>/catalog/candidates` shipped. Replaced the deferred
`catalog_derive_configs` rule-form design.

Brief: `.ai/features/2026-05-09-ma-cho-duyet/brief.md`.

## Candidate richness — match catalog row fields — SHIPPED 2026-05-09

Mig 048 (extra stats: import/export/decl counts, bom_role,
co-occurrence) + Mig 049 (richness: hs_code, uom, origin,
inferred_production_source). Refresh logic enriches candidates from
BCCT + BOM. Accept form prefills these fields so staff don't drop
sparse materials into catalog.

## Track D BOM staleness — SHIPPED 2026-05-11 + 2026-05-13

Captured 2026-05-10 as part of BOM vocab + 3-shape audit. 8 dimensions
of staleness identified; option 1 (staleness flag + manual refresh)
picked over options 2-4. Phase 1 mig 053+054 (`is_stale` flag + 5
triggers D1/D7/D8/D2±). Phase 2 mig 055-058 (Phase 2 UoM, D9
catalog-insert trigger). Phase 3 G (refresh preview). Memory
`project_bom_staleness.md` captures the model.

## BOM upload — auto-detect adapter — SHIPPED 2026-05-13

Adds `auto` as the default option in BOM upload form. Calls
`bom_adapters.parse_with_fallback()` with filename stem as
`root_code` hint; first adapter producing non-empty rows wins. Skips
mapping page; lands on `/bom/preview/<id>` with
`proposed_by='parser_auto:<adapter>'`. Friendly Vietnamese 400 when
all 5 adapters fail. Manual override preserved.

## Manual_flat 4-shape model — SHIPPED 2026-05-13

`bom_shape()` returns `'manual_flat'` for `manual_flat_as_provided`
strategy (was conflated with `'shallow'`). `BomShape` Literal
extended to 4 values. Memory `project_bom_3_shapes.md` updated.

## UI rename "tombstone" → friendly Vietnamese — SHIPPED 2026-05-13

UI/template/i18n only — code/DB/API stay `tombstone`. Mapping:
catalog material → "đã loại"; BOM artifact lineage / replace → "đã
thay thế"; preset retract → "thu hồi". 9 files edited.

## BCCT by-codes lookup — SHIPPED 2026-05-13 (soak test pending → C.1.a)

`GET /v1/hub/clients/{client_id}/bcct/by-codes?codes=A,B,C` per CO API
request `barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.
Row shape mirrors `/v1/hub/bcct`; case-insensitive exact match against
`customs_code`; max 100 codes/request; same auth model + `hub:read` scope.

Motivation: CO's substitute-stock derivation needed to paginate the
full 65k Johnson BCCT (~30s) just to derive stock for ~20 candidate
codes. Splitting "Data Hub returns BCCT slice" + "CO applies its own
`allocation_code`/`lot_policy` rules" keeps CO config out of Data Hub
(consistent with the 2026-05-02 `/co-config → /client-config` rename).

`app/routes/api.py` (+ `_parse_codes_param` helper). 19 provider tests
in `tests/test_bcct_by_codes_api.py`. `docs/API_CONTRACT.md` +
`docs/API_CHANGELOG.md` updated.

**Soak test pending — see C.1.a.** Provider tests cover the contract,
but real-load behaviour from CO (concurrent requests, long-history
codes, `include_material_identity` on large slices, EXPLAIN ANALYZE
under prod-shaped data) has not been validated. CO consumer not yet
shipped — awaiting their consumer PR per their CLAUDE.md rule (Data
Hub provider tests + changelog must land first; both done).

## Bearer-aware substitute API mirror — SHIPPED 2026-05-13

Triggered by CO blocker report: `GET /api/v1/clients/{c}/materials/{m}/substitutes`
returned 401 for any Bearer token. That route used cookie-only
`auth.require_user`; sister-app server-to-server can't carry the cookie.

New mirror at `/v1/hub/clients/{c}/materials/{m}/substitutes`
(`app/routes/api.py`). Uses existing `_require_token` +
`_require_can_view_client` (user JWT or service token with `hub:read`,
`client_ids` whitelist honored). Same response shape. Cookie route
preserved for in-app catalog detail page. 7 tests. Sister-app note:
`.ai/sister-app-notes/2026-05-13-substitute-api-bearer-available.md`.
Commit `ae3373b`.

Partial unblock of C.1 (sister-app cutover) — other cookie-only routes
under `/api/v1/...` may need the same mirroring as CO usage expands.

## A.7 BOM parser — extract "Object description" — SHIPPED 2026-05-13

`_DESCRIPTION_ALIASES` constant added in `sap_indented_walk.py` covering
EN ("Object description", "Description", "Material description"), VI
("tên hàng", "mô tả"), and ZH ("物料描述", "物料名称"). Both the leaf-emit
adapter (`SapIndentedWalkAdapter.parse`) and the raw-edge parser
(`parse_sap_indented_raw_edges` in `bom_edges.py`) capture description.
Raw path stores into `bom_edges.payload->>'description'` (jsonb,
no schema mig). `catalog_candidates._backfill_sample_from_bom` added
as fallback after `_backfill_sample_from_bcct`: picks most-recent alive
artifact's description for BOM-only candidates. +5 tests. Re-ingest
Johnson BOM still pending to backfill descriptions for existing rows.

## Johnson programmatic bulk re-ingest — SHIPPED 2026-05-11

Originally captured here as F.1 (programmatic plan, ~1 week). Shipped
in session 2026-05-11 via 4 existing scripts rather than a single
`bulk_reingest_johnson.py` tool. Commits `11ea9bd` + `dcc6216` +
`cac2bcb` + `e7578bf`. Session log:
`.ai/sessions/2026-05-11-johnson-onboarding-ship.md`.

**What landed:**
- Wipe: `scripts/setup_clients_for_reingest.py` — cascade DELETE from
  `hub.clients`, recreated client row.
- BCCT ingest: `scripts/ingest_johnson_real.py` →
  NK 60,173 + XK 5,673 = 65,846 rows / 37s.
- BOM ingest: `scripts/ingest_technical_raw_batch.py` — 106
  SAP-exploded XLSX → 27,848 raw edges across 106 TP raw_graphs.
- Post-BOM catalog fixup:
  `scripts/fixup_johnson_btp_sx_after_bom.py` — inserted 2,615
  missing BTP_SX (`source='bom_observed'`) + reclassified 416
  `nvl→btp_sx`.
- Post-ingest hooks (`derive_btp_shallows` + `materialize_shapes`)
  ran via adapter registry.

**Bugs caught + fixed during verification:**
- BTP artifact bloat (8,837 → 3,337, 2.6× reduction): BTP slice
  edges preserved TP-context fields (`level`, `node_path`,
  `source_row_no`, `sheet_name`) so identical slices under different
  parents produced different `normalized_edges_hash` → no dedup. Fix
  in `derive_btp_shallows._subtree_edges`. Also passed
  `parent_artifact_id=None` to bypass per-TP dedup fragmentation.
- UI hook resolution gap: `parse_raw_edges_with_fallback` returned
  adapter names (`sap_indented_raw`, `growatt_factory_technical`)
  not registered in `bom_adapters._REGISTRY`. Fixed via
  `_LEGACY_ALIASES` mapping → silent no-op hooks now fire.

## Growatt programmatic bulk re-ingest — SHIPPED 2026-05-28 + 2026-05-29

Closes open F.1. Same playbook as Johnson, run via existing per-step
scripts (no single `bulk_reingest.py` tool).

- **BCCT** — onboard session 2026-05-28, commit `ccbb3ad`
  (`docs(handoff): Growatt 2026-05 onboarding + volume bug fix + backup
  pipeline session`). Incremental ingest.
- **BOM** — wipe + re-ingest 2026-05-29, commit `03e9c4b`. 57 TP raws /
  3 source batches → 212 BTP raw_graphs derived → 269 raw_graphs × 3
  shapes = 807 published + 16 manual_flat restored from snapshot
  (`agency_rescued_only_gom` + `TEST_TP_DRIFT`, no XLSX to replay) = 823
  artifacts on local + demo. Johnson dedup fix (`7552c64`) already in
  place → clean BTP count (212 vs old 427). 1260 tests pass. Session log:
  `.ai/sessions/2026-05-29-growatt-bom-wipe-reingest.md`. Memory:
  `project_reingest_pending.md` (Growatt marked SHIPPED),
  `feedback_wipe_enumerate_unreplayable.md` (lesson on enumerating
  unreplayable buckets pre-wipe).

---

# Notes

The previously-tracked items below have all shipped (verified in HEAD
as of 2026-05-02 PM):

- Pre-commit upload preview at all stages → `359ebec` Phase 2.
- Catalog multi-source provenance + auto-derive from BCCT → `6141d1e` A4.
- BCCT (and all 4 tab) staleness metadata → `53da49b` A3.
- Parser bugs A/B/C/D from 2026-05-02 real-data smoke → `338be91` Phase 1.
- BCCT confirm-on-update gate + history page → `b3a59d6` + `91d2ca7`.
- LLM smart parser → `175d1f8` (BCCT) + `5d44b60` (BOM/BQD).
- /rev cache `use_count` overcount + `Path(stored_path).read_bytes()`
  FileNotFoundError → `2e8cd05`.
- Apply confirm-gate pattern to catalog/bqd/bom (was a cross-cut from
  prior /rev) → `359ebec` Phase 2.
- Service-account JWTs → migration 020, `app/jwt_issuer.py:make_service_token`,
  `scripts/mint_service_token.py`, `tests/test_service_account_jwts.py`
  (13 new tests, 232 total).

These were removed from this file on 2026-05-02 PM. See git history of
`.ai/BACKLOG.md` for the original entries.
