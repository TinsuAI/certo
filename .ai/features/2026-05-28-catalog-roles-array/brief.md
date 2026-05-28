# Feature: Catalog `materials.roles[]` — multi-role first-class

Captures BACKLOG A.1 Phase 2. Promotes catalog material classification
from single-value `category` (+ patch `category_override`) to
multi-role `roles[] text[]`, aligning declared model with the data-
graph truth surfaced by `observed_roles[]` (mig 046).

## Scope

**In:**

- New `materials.roles text[] not null` with check `roles <@ ARRAY['nvl','tp','btp_sx','btp_nm','ccdc']` and `cardinality(roles) >= 1`.
- Backfill: `roles = ARRAY[coalesce(category_override, category)]` for every existing row.
- Drop both `category` and `category_override` columns in the **same migration** (per BACKLOG critic round 2 — no dual-source coexistence).
- Rewrite every internal consumer of `m.category` / `m.category_override` (~29 files) to use `roles[]` semantics.
- Update Bearer API surface (`/v1/hub/.../catalog/...` etc.) to emit `roles[]`; keep emitting a derived top-level `category` field for one release as backwards-compat for CO, then drop.
- Sister-app coord note for CO (`data_hub_client.py` filters `category == "tp"` to split product/material).
- Audit trigger (mig 045) verified to capture `roles[]` changes.
- Materials edit form (`catalog_material_edit.html`) gains multi-select chips for roles.
- Existing `declared_observed_conflict` column in `v_material_roles` recomputed: declared = `roles[]`, observed = `observed_roles[]`; conflict = the two sets are disjoint (no overlap) AND each non-empty.

**Out (explicitly):**

- `code_mappings.category` — that's per-mapping intent (customs↔internal), not material identity. Stays single-value.
- `catalog_candidates.suggested_category` — staff workflow intermediate, single-value is fine until accepted.
- `catalog_derive_configs.default_category` — config-level fallback for parser; rename to `default_roles[]` would be a paint job, not a value-add. Skip.
- BCQT touches (none currently consume `category` directly per grep).
- Tombstone/version history work — A.1 doesn't extend the immutable principle ([[project_bom_immutable_principle]]) beyond what mig 045 audit already does.
- Phase 3 manual fields (`production_source`, `hq_registration_no`, etc.) — listed in BACKLOG A.1 item 2 but separate feature.

## Decisions

1. **Single-release drop, no `roles[]`/`category` coexistence window.** BACKLOG critic round 2 already prescribed this; dual-source-of-truth bait is the worst outcome.
2. **API back-compat by derivation, not column.** CO sees `category` as a derived top-level JSON field computed from `roles[]` via `primary_role(roles)` policy (see #3) for **one release**. Cleanup tracked as a follow-up `/schedule` after CO migrates to read `roles[]`.
3. **`primary_role(roles)` policy = priority list `tp > btp_sx > btp_nm > nvl > ccdc`.** Justification: CO's `data_hub_client.py:732` partition is "tp vs everything else" — TP-first priority preserves that split for the multi-role edge (e.g. a code TP+BTP still counts as product to CO). Implemented as a stable SQL function `hub.primary_role(text[])` so it can be reused in views.
4. **Resolver `declared_kind` becomes `declared_roles[]`** in `bcct_material_identity.py` and `flatten/classify.py`. Per-callsite decision on whether to check single-membership (`'nvl' = ANY(roles)`) or pick a `primary_role`. Default is single-membership; primary_role only where the call truly needs one value (e.g. emitting a single badge in a row that doesn't show multi-role chips).
5. **`v_material_roles` redefined:** `declared_observed_conflict` keeps semantics ("at least one declared role is contradicted by observed") but compares two sets: `roles[]` vs `observed_roles[]`. Conflict = `roles && observed_roles = false` (no overlap) AND both non-empty.
6. **Audit event** stays under the generic `bom_audit_events` ([[feedback_reuse_audit_events]]); event_type for the change is `materials_roles_changed` (replacing implicit category change). Triggers in mig 053/057/058/069/071 that reference `'catalog_category'` dim key keep their dim name — the stale-flag dim semantic is unchanged ("declared classification of this code shifted"); column source migrates from `category` to `roles[]`.
7. **No grandfathered `category_override` UI.** Override exists today as a single per-row patch. With `roles[]`, the patch *is* the row — editing roles directly. Migration drops the override badge in `catalog_detail.html` and `catalog_conflicts.html`.

## Risks

- **CO sister-app drift.** `data_hub_client.py` lines 643/732/735/861 + `main.py:6679` consume `category`. With #2 (back-compat field), CO keeps working unchanged for one release. After-deploy sanity: `gh` grep CO repo for `\"category\"` to confirm no other consumers; if found, extend the back-compat window.
- **Single-value semantic creep.** Two places still need *one* declared kind: (a) BOM's `coalesce(m.category, 'tp') as raw_category` in `app/stores/bom.py:525`, (b) BCCT identity resolver `coalesce(m.category_override, m.category) as declared_kind`. Both should adopt `hub.primary_role(roles)`. Risk: forgotten callsite emits NULL where `category` was non-null.
- **Migration ordering with staleness triggers.** Triggers in mig 053/057/058/069/071 fire on `materials.category` UPDATE. Migration must (a) drop old triggers, (b) drop column, (c) recreate triggers reading `roles[]` (compare OLD.roles vs NEW.roles via `array(select unnest(...) order by 1)`). Risk: a tx mid-migration trying to write to materials sees mid-state — mitigate by wrapping migration in single transaction (`begin/commit`).
- **Backfill correctness for override rows.** Rows where `category_override IS NOT NULL` semantically should become `roles = ARRAY[category_override, category]` (the override *added* a role)? **Decision: no.** Override today *replaces* the displayed kind; backfill takes the override value only (matches user intent) and discards the original `category` for that row. Surfaced for explicit confirmation below.
- **Test surface.** 16 test files reference `category`. Estimate ~40-60 test assertion updates, mostly mechanical. New tests required: roles[] uniqueness/non-empty, primary_role policy, v_material_roles conflict recompute, API back-compat field, sister-app payload.
- **Template `m.category in ('btp_sx','btp_nm')` checks** in `catalog.html:369`, `catalog_conflicts.html:121`, etc., must become `'btp_sx' = ANY(m.roles) or 'btp_nm' = ANY(m.roles)` — Jinja side. Easy to grep but easy to miss one.

## Open Questions

1. **Backfill of `category_override`**: confirm decision in risk #4 — override-row becomes `roles = ARRAY[category_override]`, original `category` discarded. **Default answer if no objection: yes.**
2. **`primary_role` priority order**: proposed `tp > btp_sx > btp_nm > nvl > ccdc`. Drives CO back-compat field. Any reason to put `nvl` or another role above tp? Default: keep proposed.
3. **CO back-compat field lifetime**: one release = until CO PR ships consuming `roles[]`. After CO ships, drop on Data Hub side via `/schedule` follow-up. Acceptable? (Alternative: hard-cut at A.1 ship, force CO to ship same day. Riskier.)
4. **`m.category` in `embedding.py`, `llm.py`, `agent/tools.py`** — these feed semantic search / RAG. They need a textual representation of the role. Use comma-joined `roles` (`"tp,btp_sx"`) or `primary_role`? Embedding regen cost is non-trivial. Defer the embedding refresh as a separate follow-up; new ingests use new representation, existing embeddings stay until next regen pass.

## Manual Test Plan

After migration ships locally:

1. **Migration runs clean.** `make migrate` on dev DB; no errors. Verify `hub.materials` has `roles` column, no `category` / `category_override`.
2. **Backfill correctness.** Spot-check 5 rows pre/post: rows with override become `roles=[override]`; rows without become `roles=[category]`. SQL: `select material_code, roles from hub.materials limit 20`.
3. **Catalog list UI** (`/clients/<id>/catalog`): badge renders one chip per role; multi-role rows show 2 chips.
4. **Catalog edit form**: switch a row from `['nvl']` to `['nvl','btp_sx']`, save, reload — chips show both; audit log captures change.
5. **Catalog conflicts page**: row with `roles=['nvl']` but `observed_roles=['tp']` still flagged; row with `roles=['nvl','tp']` and observed `['tp']` no longer flagged.
6. **BOM flatten on a Growatt product**: run flatten; verify resolver classifies BTP nodes correctly (uses `'btp_sx' = ANY(roles)`).
7. **BCCT identity resolver**: upload a BCCT row referencing a multi-role code; resolver picks `primary_role` for `declared_kind`, no NULL.
8. **CO via API**: hit `/v1/hub/clients/<id>/catalog/materials` (or whatever Bearer surface CO uses); response includes both new `roles` array AND derived `category` top-level field. CO can still partition product/material.
9. **Audit event**: edit a row, check `bom_audit_events` row appears with `event_type='materials_roles_changed'` (or whatever final name).
10. **Test suite**: `uv run pytest -q` — target same or +N passed, zero new skip. Hard fail if any old assertion on `category` left untouched.

## Done Criteria

- Migration applied locally + on demo; no rollback required.
- 0 grep hits for `\.category_override` or `m\.category\b` outside the migration file itself.
- CO `data_hub_client.py` works unmodified against new API (manual smoke: trigger a CO sync against demo, check non-empty product + material lists).
- Sister-app note `.ai/sister-app-notes/2026-05-28-catalog-roles-array.md` written with CO migration steps + back-compat sunset date.
- Test count baseline +5/+10 expected (new roles[] tests minus consolidated category tests).
- BACKLOG A.1 marked **SHIPPED** with commit hash.

## Suggested Next Step

`/tdd` — write the migration test (backfill correctness + constraints) and the v_material_roles conflict recompute test first; they're the highest-risk changes. Implementation order: migration → resolver `primary_role` SQL fn → BOM/BCCT consumers → catalog routes + templates → API surface + back-compat field → sister-app note.
