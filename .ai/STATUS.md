# Project Status

**Date:** 2026-05-09 — BCCT view format + catalog multi-source (mig 042-046) + dual-source roles + Mã chờ duyệt deferred to next session

## Current State

**Two streams shipped this session, uncommitted in working tree:**

### Stream A — BCCT view format (READY)

User asks (currency bug, format, column picker) all addressed:
- Format helpers: `_format.html` macros (`format_number`, `format_money`, `format_date`, `format_int`) — locale-aware (vi `1.234.567,89`)
- `_sort.html` macro extracted from inline duplication
- BCCT main list: 2 cột giá trị tách bạch — "Giá trị NT" (FX `total_value_nt + currency_nt`) + "Giá trị VND" (`total_value` + literal "VND"). Bug 12B-VND-cạnh-USD đã fix.
- Column picker (`col-picker.js`) — vanilla JS, localStorage-backed, Ấn/hiện cột bất kỳ với persistence.
- 12 new tests (format macros), all pass.
- 4 screenshots committed at `.ai/features/2026-05-08-bcct-view-format/screenshots/`.

### Stream B — Catalog multi-source (Phase 1 SHIPPED)

7 migrations + cross-cut refactor + new derive tool + adoption guide.

**Schema:**
- Mig 042 — RENAMED `materials.customs_code → material_code` (mode-agnostic primary code), DROPPED vestigial `internal_code`, added 5 cols (`source/status/hq_registered/promoted_to_declared_at/promoted_by`), backfilled source from old `provenance->'seen_in_bcct'` jsonb (9000 rows for Growatt+Johnson).
- Mig 043 — `catalog_derive_configs` table (+ wizard form UI).
- Mig 045 — audit trigger on `hub.materials` writing to `material_audit_events` on UPDATE/DELETE (mirrors mig 013 BCCT pattern).
- Mig 046 — `v_material_roles` extended: 4-role observed_roles (added `btp_nm` for dual-source case where has_imports + has_own_bom + is_consumed_in_bom). Dual-source emerges naturally as `btp_sx + btp_nm` both fire → `is_multi_role=true` → UI badge "Đa nguồn (BTP)".

**App refactor:**
- `material_identity` struct: dropped `display_code`, renamed `declared_customs_code → customs_code`, `declared_internal_code → internal_code`. Added `resolution_status='resolved_pending_review'` for `bcct_observed/under_review` materials.
- 11 app/script files refactored for `customs_code → material_code` rename (~50 SQL touch sites).
- Resolver, agent tools, provenance store, BOM, scripts all updated.

**UI:**
- Catalog list (`/clients/<id>/catalog`) — full redesign with column picker pattern from BCCT view. Drop dead "Mã NB" column (`internal_code` gone). New columns: source pill, status pill, ĐK HQ, observation stats (count + first_at + last_at + directions live from view), Chi tiết link, Promote/Tombstone actions. Status filter chip. Sourcing-confirmation conflict badge (Python derive: staff `btp_sourcing` vs observed pattern in `observed_roles[]`).
- New detail page (`/clients/<id>/catalog/<material_code>/detail`): 5 sections — current state (incl. provenance jsonb), live observed signals, audit history (from material_audit_events), BCCT references (recent 20), BOM artifacts (recent 20).
- Catalog-derive wizard (`/clients/<id>/catalog/derive`) — shipped but **deferred for redesign next session** (user pivoted to passive candidate feed).

**Tests:** 644 pass / 15 skip / 0 fail. From 638 baseline + 6 new (`test_format_macros.py`) + 6 new (`test_catalog_derive.py`) − 6 obsolete tests refactored.

**Adoption guide:** `.ai/sister-app-notes/2026-05-09-catalog-multi-source-and-vocab.md` covers all schema/struct/vocab changes for CO + BCQT to adopt at their pace (CO is paused; no live coordination required).

## Recent Changes — files

```
NEW (uncommitted):
  db/migrations/042_catalog_material_code_rename_and_provenance.sql
  db/migrations/043_catalog_derive_configs.sql
  db/migrations/045_materials_audit_trigger.sql
  db/migrations/046_v_material_roles_dual_source_btp.sql
  app/routes/catalog_derive.py
  app/templates/clients/catalog_derive.html
  app/templates/clients/catalog_detail.html
  app/templates/_format.html
  app/templates/_sort.html
  app/static/js/col-picker.js
  tests/test_format_macros.py
  tests/test_catalog_derive.py
  .ai/features/2026-05-08-bcct-view-format/   (brief + ui_smoke + 4 screenshots)
  .ai/features/2026-05-08-catalog-multi-source/   (brief rev 4 + ui_smoke + 3 screenshots)
  .ai/sister-app-notes/2026-05-09-catalog-multi-source-and-vocab.md

MODIFIED (uncommitted):
  app/routes/{api,bom,catalog}.py
  app/agent/tools.py
  app/resolvers/bcct_material_identity.py
  app/stores/{bom,provenance}.py
  app/templates/clients/{bcct,catalog}.html
  app/main.py
  scripts/{bootstrap_btp_roster, bootstrap_catalog_from_bcct, derive_btp_shallows,
           detect_dual_source_btps, feed_demo_company, materialize_shallow_and_full_flat,
           screenshot_flatten}.py
  tests/test_*.py (15 files)
  .ai/{STATUS,BACKLOG}.md
```

Total: ~50 file diff, ~891 insertions / ~390 deletions.

## Next Steps

Per `BACKLOG.md` priority order:

1. **Mã chờ duyệt — passive candidate feed** (~1-1.5 days) — replaces
   the wizard form `catalog_derive` shipped this session. User
   redesign decision 2026-05-09: drop wizard, build passive feed
   that watches BCCT + BOM continuously and surfaces candidates from
   existing `client_parser_rules`. Drop `catalog_derive_configs` +
   wizard. Add `catalog_candidate_rejections` table. Page name "Mã
   chờ duyệt". Logic finalized in BACKLOG entry.

2. **Catalog conflicts page** (~0.5-1 day) — surface
   `declared_observed_conflict` rows + sourcing-confirmation conflict
   rows in dedicated review queue. Page
   `/clients/<id>/catalog/conflicts`. Reuses existing endpoints.

3. **Phase 2 catalog — multi-role roles[] + manual fields** (~2-3
   days) — `materials.roles[] text[]`, drop `category` + `category_override`,
   add manual fields (`production_source`, `hq_registration_no/date`,
   `supplier_hint`, `name_source`, `uom`). Cross-cut refactor 30-50
   files. Critic round 2 already flagged dual-source-of-truth trap;
   commit to drop `category` same release window.

4. **Wipe + ingest fresh — Growatt + Johnson** (memory
   `project_reingest_pending.md`) — pre-MVP one-shot reset. Triple
   unblocked now: rule engine works, FX/VND domains split, payload
   pruned, catalog architecture finalized.

5. **CO + BCQT consumer migration** — adoption guide written
   (`.ai/sister-app-notes/2026-05-09-catalog-multi-source-and-vocab.md`).
   Coordinate when CO unpause from current pause.

## Blockers

None hard. Soft (carry-over):
- 14 orphan BTPs Growatt (data quality — staff classify when TP context arrives).
- T1-T2/2026 BCCT for Growatt missing (agency hasn't supplied file).

## Notes for Next AI Session

**Read first** (in order):
1. This STATUS
2. `.ai/sessions/2026-05-09-catalog-multi-source-and-bcct-view-format.md` (this session's full log)
3. `.ai/features/2026-05-08-catalog-multi-source/brief.md` (rev 4 — the design that drove migs 042-046; note `catalog_derive` part is now superseded per BACKLOG)
4. `.ai/features/2026-05-08-bcct-view-format/brief.md`
5. `BACKLOG.md` "Mã chờ duyệt" entry — has the design contract for next session

**Key memory** (load when reasoning about catalog/multi-role):
- `project_bom_code_multirole.md` — "code can be TP+BTP+NVL simultaneously"
- `feedback_no_derived_in_source.md` — derived values via view/runtime, never store as column
- `feedback_naming_discipline.md` — names encode role, not implementation context
- `reference_terminology_client.md` — `client` = DNCX manufacturer (not Tinsu/agency)
- `feedback_macros_over_view_engine.md` — read divergent templates before abstracting
- `feedback_review_depth.md` — cap review at 2 passes
- `feedback_drive_ops_dont_handoff.md` — execute via ssh.exe/scp.exe/gh

**Architecture / contracts that are LOCKED, don't relitigate**:
- `materials.material_code` is the PK (renamed from customs_code mig 042). Mode-agnostic.
- `bcct_rows.customs_code` and `code_mappings.customs_code/internal_code` UNCHANGED (semantically accurate in those contexts).
- `material_identity` struct fields: `customs_code`, `internal_code`, `resolved_code` (no `declared_` prefix). `display_code` DROPPED — consumer composes `resolved_code or internal_code or customs_code` 3-tier fallback.
- `source` enum: `client_declared / bcct_observed / bom_observed / system`. NOT "agency_declared" — DNCX terminology per memory.
- `status` enum: `active / under_review / deprecated / tombstoned` (+ legacy `inactive` accepted).
- `v_material_roles` view computes observation stats live (NEVER cache `observed_count` on materials per `feedback_no_derived_in_source.md`).
- Dual-source = `'btp_sx' AND 'btp_nm'` both in observed_roles. NO separate `is_dual_source` column on view (Python derives from observed_roles content).
- `resolution_status='resolved_pending_review'` when resolver hits `bcct_observed/under_review` material.

**Working-tree state**: ALL uncommitted. After /handoff, user will commit.

**Migration state**:
- DB: at mig 046 applied locally. Schema_migrations recorded.
- mig 044 reserved (planned drop catalog_derive_configs in next session if user wants Mã chờ duyệt redesign).
- Mig file order: 042 (catalog rename + provenance) → 043 (catalog_derive_configs) → 044 (RESERVED) → 045 (audit trigger) → 046 (v_material_roles dual-source).

**Environment quirks**:
- Native Postgres on `/var/run/postgresql` socket, owner `vp`.
- WSL2: Windows OpenSSH (`/mnt/c/Windows/System32/OpenSSH/{ssh,scp}.exe`).
- Port 8754 pinned for dev. Server may still be running from this session.
- Login: `admin@data-hub.local` / `admin123`.

**Critical user feedback this session** (also in memory + BACKLOG):
- Numbers + currency labels must reflect real domain (FX vs VND).
- Catalog view must reflect schema mới — no dead "Mã NB" columns.
- `material_code` rename "đã bàn rồi" — semantic correctness > touch-site convenience.
- Derived values stay in view, never stored as cached columns.
- `is_dual_source` separate flag was confusing; collapsed into `observed_roles` containing both `btp_sx + btp_nm`. `btp_sourcing` becomes "Xác nhận nguồn cung" — staff confirmation; conflict warning when staff confirm differs from observed.
- Catalog-derive wizard form UX = confusing; pivot to passive candidate feed (Mã chờ duyệt) next session.

**Sister-app coordination state**:
- CO `barry-CO-main`: paused awaiting Data Hub stabilize. Adoption guide written + complete.
- BCQT `BCQT-System`: forward-looking only.
