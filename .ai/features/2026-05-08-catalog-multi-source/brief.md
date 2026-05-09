# Catalog multi-source + vocab cleanup

**Date:** 2026-05-08
**Status:** Brief — pending review
**Owner:** dennis
**Predecessor:** `.ai/features/2026-05-08-configurable-bcct-parsing/brief.md` (mig 035-041)

## Why

Three concrete pains, captured during BCCT view-format session 2026-05-08:

### Pain 1 — Catalog incompleteness leaks into BCCT display

**Symptom**: row `108130349500-1/1` (Growatt) shows "Mã NB = IC" in BCCT
list view despite goods_name parens carrying agency code `007.0050100`.
Parser DOES extract `007.0050100` correctly via mig 036 rules, but
`material_identity.display_code` falls back to `customs_code = IC`
because resolver Stage 1 requires `code in materials` and
`007.0050100` is not in catalog.

**Scope**: 21,015 of 21,411 affected Growatt rows (96%) — BCCT goods_name
carries paren codes that are not in `hub.materials`. Catalog has 451
rows (mostly HQ buckets); BCCT references ~21,000 NB codes the agency
uses internally. Catalog hasn't been populated by agency at the NB
level — they uploaded HQ-side categorization, which is the customs
declaration scope, not their full SKU master.

**Counter-proposal (rejected)**: blindly auto-fill catalog from BCCT
parens via existing `bootstrap_catalog_from_bcct.py`. Rejected by user
("nếu cứ fill catalog vào từ BCCT thì catalog có tác dụng gì?"):
defeats catalog's role as source-of-truth + validation gate +
metadata enrichment. Bootstrapped rows would have garbage names
(truncated goods_name) and guessed categories. Right answer:
3-source catalog with explicit provenance.

### Pain 2 — Field naming bakes in misleading assumptions

`materials.customs_code` (PK) is the **mode-agnostic primary
material code**, not specifically a customs concept. In identity-mode
clients (Johnson) this column holds the DNCX client's ERP code; in
rule-mode (Growatt) it holds the HQ bucket. Same column, different
semantics by mode — name encodes the rule-mode case as if universal.

`material_identity.display_code` is a 2-tier fallback (`resolved_code`
or `customs_code`), but the name implies UI concern. UI dev reads
"display_code" → assumes it's the right thing for any column → ships
bug like Pain 1. Documented in memory `feedback_naming_discipline.md`.

### Pain 3 — Multi-role + provenance gaps

Memory `project_bom_code_multirole.md` (2026-05-04): "a code can be
TP+BTP+NVL simultaneously (rework / cải chế). Catalog single-value
category is impoverished; data graph is truth. Phase 3 needs
multi-role flags."

Phase 3a/3b shipped `v_material_roles` view (mig 033/034) deriving
multi-role from BCCT direction + BOM containment. But `materials.category`
remains single-valued, and provenance (source: agency-declared vs
BCCT-observed vs BOM-observed) is implicit. No way to query
"codes seen in BCCT but not yet in agency catalog" → Pain 1
materializes invisibly.

## Goal

A **3-source catalog** with explicit provenance + a configurable
**catalog-derive tool** that pulls codes from BCCT/BOM under
staff-controlled rules — adding them as `under_review`, never silently
authoritative. Plus a resolver upgrade that fixes Pain 1 immediately
even before any derive runs. Plus vocab cleanup
(`materials.customs_code → material_code` rename, drop misleading
prefix `declared_*` from `material_identity` struct, drop derivable
struct fields).

After this lands:
- Pain 1 fix (immediate): `display`-equivalent fallback chain in
  consumer code returns parser-extracted code before customs_code raw,
  so Growatt row `108130349500-1/1` shows `007.0050100` instead of `IC`.
- Catalog growth path: staff use derive tool to bulk-add observed
  codes as `bcct_observed/under_review`; review + promote on catalog
  list page; client-uploaded Excel still authoritative.
- Future-proof source tracking: `materials.source` enum makes
  "where did this row come from?" queryable; future audits + lifecycle
  ops have a foundation.
- Mode-agnostic catalog vocab: `material_code` reflects column's actual
  semantic regardless of client mode. No more "customs_code is actually
  the DNCX ERP code in identity-mode" mental gymnastics.

Phase 2 (deferred): multi-role `roles[]`, manual fields
(`production_source`, HQ registration detail, supplier_hint).
Explicit out-of-scope list at end of brief.

## Schema diff

### Design principle (anchor — see memory `feedback_no_derived_in_source.md`)

> Source tables/structs hold ONLY: manual input, provenance, workflow
> state. Derivable values compute at runtime via view or helper, never
> stored as columns/cached struct fields.

This rules out columns like `observed_count` (derive via view) and
struct fields like `display_code` (consumer composes). Caches don't
exist on source data — they breed staleness + conflated semantics.

### Vocab rename (bundled in this PR)

User principle (memory `feedback_naming_discipline.md`): **semantic
correctness > touch-site convenience. If many references → refactor
all, even rebuild from scratch.** Critic round 2 argued 620 sites
overscoped for `customs_code → material_code` rename; user overrode
explicitly: "sai semantic, sai mental model sao được? Nếu có nhiều
nơi gọi thì refactor hết, chạy lại từ đầu cũng được."

| Cũ | Mới | Action |
|---|---|---|
| `materials.customs_code` (PK) | `materials.material_code` (PK) | RENAME — mode-agnostic primary code. Current name implies HQ concept, but column holds: HQ buckets (Growatt rule-mode), DNCX client ERP codes (Johnson identity-mode), parser-extracted codes (`bcct_observed`), BOM node codes (`bom_observed`). Same column, multiple semantics. `material_code` neutral. |
| `materials.internal_code` | (drop) | DROP — vestigial (100% = customs_code) |
| `material_identity.declared_customs_code` | `material_identity.customs_code` | RENAME — drop misleading "declared_" prefix; mirrors `bcct_rows.customs_code` value |
| `material_identity.declared_internal_code` | `material_identity.internal_code` | RENAME — `internal_code` is parsed annotation from goods_name, NOT formally declared to HQ; "declared_" prefix misleading |
| `material_identity.bom_product_code` | (drop) | DROP — derivable: `resolved_code if product_kind in ('tp','btp_sx') else None` |
| `material_identity.selected_candidate_code` | (drop) | DROP — derivable: `resolved_code or candidates[0].product_code` |
| `material_identity.display_code` | (drop) | DROP — derivable; conflates 2 semantics under "best for display"; consumer composes 3-tier fallback explicitly |

**Source enum value naming** — corrected per memory `reference_terminology_client.md`:
- ~~`agency_declared`~~ → **`client_declared`** (DNCX client uploaded their Excel, NOT customs broker / Tinsu)
- `bcct_observed`, `bom_observed`, `system` — accurate, kept

**Kept (no rename)** — names accurate in their respective contexts:
- `bcct_rows.customs_code` — what's filed on customs declaration line. Accurate.
- `code_mappings.customs_code` ↔ `code_mappings.internal_code` — translation table; both sides explicit. Accurate.
- `material_identity.resolved_code` — points to a `materials.material_code` value. Accurate.

**Rename consequential refs**:
- All `materials.customs_code` → `materials.material_code` in SQL queries, JOINs, ORM-equivalents.
- All `materials_table[customs_code]` Python dict reads → `materials_table[material_code]`.
- All `m.customs_code` SQL aliases for the materials table column.
- Foreign key references in `bom_artifact_rows.material_code` (already has this name; no change), `client_uom_overrides.material_code`/`material_code_key` (already has this name; no change), etc.
- Index renames: `idx_materials_customs_code → idx_materials_material_code` if such index exists.

`code_mappings.customs_code` stays — it specifically means "the
HQ-side code in this translation pair" (paired with `internal_code` =
DNCX side). Both names accurate in that table's context.

`bcct_rows.customs_code` stays — it IS what was filed on the customs
declaration line. Semantic accurate.

### New columns on `hub.materials` (provenance + state + manual fields ONLY)

```sql
alter table hub.materials
  -- Provenance (where this row came from — set once at insert)
  add column source text not null default 'client_declared'
    check (source in ('client_declared', 'bcct_observed', 'bom_observed', 'system')),

  -- Workflow state (manual)
  add column status text not null default 'active'
    check (status in ('active', 'under_review', 'deprecated', 'tombstoned')),

  -- Manual flags (workflow / business)
  add column hq_registered boolean,
  add column promoted_to_declared_at timestamptz,
  add column promoted_by text;
```

**Deliberately NOT added** (would violate source-data principle):
- `observed_count`, `observed_first_at`, `observed_last_at`,
  `observed_directions[]` — all derivable from `bcct_rows`. Compute
  via `v_material_roles` view extension (see below).
- `roles[]` (multi-role) — defer to Phase 2; existing `category`
  works for now and `v_material_roles.observed_roles[]` already
  derives the live multi-role view.
- `production_source` (nk/sx) — defer to Phase 2 (manual but not
  needed for Pain 1 fix).
- `hq_registration_no`, `hq_registration_date`, `supplier_hint`,
  `name_source`, `uom` — defer to Phase 2 (lower priority manual
  fields; keep `provenance` jsonb for audit detail like
  `registered_with_hq.{first_seen, source_upload_id}` as already
  exists).

### View extension `v_material_roles` — derive observation stats live

```sql
-- Mig 042 also extends v_material_roles. Drop + recreate (views
-- can't ALTER add columns).
drop view hub.v_material_roles cascade;
create view hub.v_material_roles as
select
  m.client_id, m.customs_code,
  m.category as declared_kind,
  -- Existing role flags (mig 033/034)
  bool_or(b.direction = 'import') as has_imports,
  bool_or(b.direction = 'export') as has_exports,
  ... (giữ nguyên các flag khác),
  -- NEW: observation stats — always live, never stale
  count(b.transaction_key) filter (where b.transaction_key is not null)
    as observed_count,
  min(b.registration_date) as observed_first_at,
  max(b.registration_date) as observed_last_at,
  array_agg(distinct b.direction)
    filter (where b.direction is not null)
    as observed_directions
from hub.materials m
left join hub.bcct_rows b
  on b.client_id = m.client_id and b.customs_code = m.customs_code
group by m.client_id, m.customs_code, m.category;
```

**Why view not column**: BCCT data changes every upload. Column =
stale until refresh hook. View = always reflects current BCCT.
Performance: index `idx_bcct_customs btree (client_id, year, customs_code)`
exists; aggregate over 22k Growatt rows ~50-200ms full; with LIMIT 50
on catalog page <50ms. If perf becomes pain at 100k+ rows, promote
to materialized view with refresh on BCCT ingest.

### Migration order (single mig 042, atomic)

```sql
-- 1. Rename PK
alter table hub.materials rename column customs_code to material_code;

-- (rename indexes, constraints, FK refs as needed — atomic in same mig)

-- 2. Drop vestigial column (after verifying no consumer reads it)
alter table hub.materials drop column internal_code;

-- 3. Add new columns (provenance + state + manual)
alter table hub.materials
  add column source text not null default 'client_declared'
    check (source in ('client_declared','bcct_observed','bom_observed','system')),
  add column status text not null default 'active'
    check (status in ('active','under_review','deprecated','tombstoned')),
  add column hq_registered boolean,
  add column promoted_to_declared_at timestamptz,
  add column promoted_by text;

-- 4. Backfill from existing provenance jsonb
update hub.materials
   set source = 'bcct_observed'
 where provenance ? 'seen_in_bcct'
   and source = 'client_declared';
update hub.materials
   set provenance = provenance - 'seen_in_bcct'
 where provenance ? 'seen_in_bcct';
update hub.materials
   set hq_registered = true
 where provenance ? 'registered_with_hq';

-- 5. Drop + recreate v_material_roles with observation stats
drop view hub.v_material_roles cascade;
create view hub.v_material_roles as ... (with observation stats);

-- 6. Recreate any cascade-dropped views/functions (Phase 1 audit
--    confirms what depends on v_material_roles)
```

After backfill, `provenance` jsonb retains audit-only keys:
- `btp_inferred` (2580 rows) — Phase 3 BTP roster bootstrap audit
- `registered_with_hq` (4 rows) — registration audit detail

Single mig, atomic. CO + BCQT consumers update SQL refs to
`materials.material_code` same release window per sister-app note.

### Drop fields from `material_identity` struct

Resolver returns smaller struct. Consumers compose at read time:

```python
# Display (was display_code):
display = (mi.get('resolved_code')        # catalog-validated
           or mi.get('internal_code')     # parser-extracted from goods_name
           or mi.get('customs_code'))     # raw filed at customs

# Has BOM (was bom_product_code):
has_bom = (mi.get('product_kind') in ('tp', 'btp_sx')
           and mi.get('resolved_code') is not None)

# Best candidate (was selected_candidate_code):
best = (mi.get('resolved_code')
        or (mi.get('candidates') and mi['candidates'][0].get('product_code')))
```

Three drops:
- `display_code` — was `resolved_code or customs_code` (2-tier)
- `bom_product_code` — was `resolved_code if has_alive_bom else None`
- `selected_candidate_code` — was `resolved_code if resolved else best_candidate`

**Behavior change disclosure** (NOT equivalent rename):

The new 3-tier consumer chain `resolved_code or internal_code or customs_code`
is **NOT** semantically equivalent to old `display_code = resolved_code or customs_code`.
For rows where `resolved_code is None` AND `internal_code` is set (parser
extracted a code that wasn't in catalog — exactly Pain 1's case), the new
chain returns the parser-extracted code instead of falling back to
`customs_code` raw. This is a **deliberate upgrade**:

| Row case | Old `display_code` | New consumer chain |
|---|---|---|
| Resolved (catalog hit) | `resolved_code` | `resolved_code` (same) |
| Unresolved, parser extracted code from goods_name | `customs_code` (raw) | `internal_code` (parser-extracted) — UPGRADE |
| Unresolved, no parser match | `customs_code` (raw) | `customs_code` (same) |

The upgrade fixes Pain 1 directly: Growatt row `108130349500-1/1` previously
showed `IC` (raw customs_code), now shows `007.0050100` (parser-extracted)
when catalog still doesn't have the agency code.

Consumers (CO 6 sites + BCCT UI + BCQT) update per sister-app note. Sister-app
note explicitly flags this as a semantic change, not a rename.

## Catalog-derive tool — UI page `/clients/<id>/catalog/derive`

### Two surfaces — distinct purposes (clarification)

These are easy to conflate. Brief clarifies up-front:

| Surface | Source query | Shows | Mục đích |
|---|---|---|---|
| **Catalog list** `/clients/<id>/catalog` | `materials` LEFT JOIN `v_material_roles` | Codes ALREADY in `materials`, with live observation stats (count, first_seen, directions) from view | Browse + edit existing catalog |
| **Catalog derive** `/clients/<id>/catalog/derive` | Extract from `bcct_rows.goods_name` parens via filter rule, ANTI-JOIN `materials` | Codes IN BCCT but NOT yet in `materials` | Populate catalog from observed agency codes |

Catalog list view never sees codes outside `materials`. Derive tool is
the surface that exposes "what's in BCCT but missing from catalog" → staff
review → bulk-add → those codes then visible in catalog list.

### Filter rules — single table `catalog_derive_configs` (revised per critic)

Critic flagged splitting filter logic across `client_parser_rules`
(regex) + `catalog_derive_configs` (non-regex) creates "two places to
update one logical rule." Single table owns everything:

```sql
create table hub.catalog_derive_configs (
  config_id bigserial primary key,
  client_id text not null references hub.clients(client_id) on delete cascade,
  name text not null,                            -- "BCCT NVL codes (NNN.xxx)"
  source_table text not null
    check (source_table in ('bcct_rows', 'bom_edges')),
  -- Regex extraction (what `client_parser_rules` would have done)
  pattern text not null,                         -- '\((\d{3}\.[\w\-]+)\)'
  source_field text not null default 'goods_name',
  match_group int not null default 1,
  -- Non-regex filters
  direction_filter text[],                       -- {'import'} or NULL = all
  min_observed_count int default 1,
  date_from date,
  date_to date,
  -- Defaults applied to derived rows
  default_status text not null default 'under_review'
    check (default_status in ('under_review','active')),
  default_category text                          -- 'nvl', 'btp_sx', etc.
                                                 -- (Phase 2 if multi-role)
  -- Workflow
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  created_by text not null
);
```

ReDoS protection reuses `google-re2` validator from
`client_parser_rules`. Pattern compile + reject backreferences at save
time (same code path).

Note: the derive tool's regex extraction happens at preview/apply
time, NOT at catalog read time. The view-based observation stats
(via `v_material_roles`) operate on `materials.customs_code` after
codes have been added. So derive engine and resolver engine stay
separate — they don't share runtime path.

### UI sketch

```
┌─ /clients/growatt-vn/catalog/derive ─────────────────────────────┐
│                                                                    │
│  ┌─ Filter rule: BCCT NVL agency codes ──────────────[Edit]──┐   │
│  │  Source: bcct_rows                                          │   │
│  │  Pattern: \((\d{3}\.[\w\-]+)\)         (extract NNN.xxx)    │   │
│  │  Source field: goods_name                                   │   │
│  │  Direction: import only                                     │   │
│  │  Min freq: ≥3 observations                                  │   │
│  │  Date: 2026-01-01 → today                                   │   │
│  │  Default role: nvl   |   Default prod_source: nk            │   │
│  │  [Preview] [Apply]                                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  Preview (top 50 by observed_count):                               │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Mã          | obs | suggested_name                  | actions│  │
│  │ 007.0050100 | 156 | "Mạch tích hợp IC, ISO1430..."  | [skip] │  │
│  │ 015.0052000 | 134 | "Adapter, ổ cắm AC..."          | [skip] │  │
│  │ 940.0012600 | 98  | "Tem nhãn polyimide..."         | [skip] │  │
│  │ ...                                                          │  │
│  │                                                              │  │
│  │  [+ 21,012 more codes match]                                 │  │
│  │  [Apply all to bcct_observed (status=under_review)]          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌─ Review queue: bcct_observed (under_review, 21,015) ────────┐  │
│  │  Sort: observed_count desc                                   │  │
│  │  Mã          | obs | role  | name                | actions   │  │
│  │  007.0050100 | 156 | nvl   | "Mạch tích hợp IC"  | [Promote] │  │
│  │                                                                │  │
│  │  [Bulk promote selected →agency_declared]                    │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### Workflow

1. Staff opens page, picks/edits filter rule (`catalog_derive_configs`
   row). Preview button reuses `google-re2` engine to extract candidate
   codes from BCCT goods_name parens, anti-JOINs `materials`.
2. Preview shows distinct codes with observation stats (computed live
   from BCCT aggregate, not stored) + suggested name (longest common
   prefix of goods_name across observations).
3. **Bulk apply** → insert `materials` rows with:
   - `source='bcct_observed'`
   - `status='under_review'` (or `active` per rule's `default_status`)
   - `category=default_category` from rule
   - `name=suggested_name` (staff edits later)
   - `customs_code` = the extracted code
4. Catalog list page (`/clients/<id>/catalog`) shows new rows with
   live observation stats from `v_material_roles` view. Staff filters
   `status='under_review'`, sorts by `observed_count desc` (live), edits
   name/category/hq_registered, then promotes:
   - **Promote action**: sets `status='active'`, `source='client_declared'`
     (now treated as if agency uploaded), `promoted_to_declared_at`,
     `promoted_by`.
5. BOM-observed flow: separate `catalog_derive_configs` row with
   `source_table='bom_edges'`. Pulls `parent_code`/`child_code` not
   yet in catalog. Same review workflow.

**No separate review queue page** — review happens on the existing
catalog list page filtered by `status='under_review'`. One page, two
filter modes (per critic: avoid building separate review queue UI when
existing list page + filter does the job).

## Resolver behavior change

Current `_empty_result` (line 346):
```python
"display_code": row.get("customs_code") or "",  # was the fallback
```

Change: drop `display_code` field. Consumer composes 3-tier fallback.

`code in catalog` invariant (Stage 1, line 436): currently checks
`code in materials.customs_code`. After this brief, the membership
check should treat `materials` rows as eligible regardless of `source`,
BUT factor `status` into resolution:

| Materials row state | Stage 1 behavior | resolution_status |
|---|---|---|
| `source=client_declared`, `status=active` | resolves | `resolved` |
| `source=bcct_observed`, `status=active` (auto-promoted) | resolves | `resolved` |
| `source=bcct_observed`, `status=under_review` | resolves | `resolved_pending_review` (new status) |
| `source=*`, `status=deprecated` | not eligible | falls through |
| `source=*`, `status=tombstoned` | not eligible | falls through |

`resolution_status='resolved_pending_review'` is a new value alongside
existing `resolved`, `unresolved`, `ambiguous`, `unverified`. Consumers
treating `resolved_pending_review` as `resolved` for display + as
`needs_review` for write-side validation. Spec lives in this brief
(per critic — don't hand-wave confidence semantics).

No `confidence` weighting per source — keep `confidence` semantics
unchanged (driven by resolution evidence, not row provenance).

## Sister-app coordination — adoption guide approach

**Strategy lock (2026-05-09)**: Data Hub ships independently as hard
cut. CO + BCQT adopt at their own pace using the adoption guide. CO
is currently paused waiting for Data Hub to stabilize, so this is
the right time for breaking changes. No same-release-window
coordination required.

The "sister-app note" output of this PR is a **thorough adoption
guide** at `.ai/sister-app-notes/2026-05-08-catalog-multi-source-and-vocab.md`
written for CO/BCQT teams to follow when they're ready to consume.
Goes into more detail than the prior 2026-05-08 hard-cut precedent
because no live coordination call to fill in gaps.

CO consumer migration (CO repo `barry-CO-main`):

| File:line | Old | New |
|---|---|---|
| `app/data_hub_client.py:415,426,438,538` | `mi['display_code']` | `mi.get('resolved_code') or mi.get('internal_code') or mi.get('customs_code')` |
| `app/bom_service.py:266` | same pattern | same |
| `app/main.py:1794` | same pattern | same |
| `mi['declared_customs_code']` reads | `mi['customs_code']` |
| `mi['declared_internal_code']` reads | `mi['internal_code']` |
| `mi['bom_product_code']` reads | `mi['resolved_code'] if mi.get('product_kind') in ('tp','btp_sx') else None` |
| `mi['selected_candidate_code']` reads | `mi.get('resolved_code') or (mi.get('candidates') and mi['candidates'][0].get('product_code'))` |
| Any SQL `materials.customs_code` ref | `materials.material_code` |
| Any Python dict `mat['customs_code']` for materials catalog row | `mat['material_code']` |
| Any ORM/dataclass `material.customs_code` | `material.material_code` |

**Behavior change flag** (sister-app note must call out): the new
`display`-equivalent fallback chain returns `internal_code` (parser-extracted)
before `customs_code` (raw filed). For rows with parser hit but no catalog
match, displayed value changes from raw customs_code → parser-extracted code.
This is a deliberate upgrade, not a rename.

**Vocab rename flag**: `materials.customs_code → materials.material_code`
PK column rename. CO + BCQT teams grep their codebase for `materials.customs_code`
SQL refs and Python dict reads `mat["customs_code"]` for materials rows.
Note: `bcct_rows.customs_code` and `code_mappings.customs_code` UNCHANGED —
only `materials` table renames. CO/BCQT teams need to be careful to update
ONLY the materials-context refs.

BCQT consumer: forward-looking only (no current consumer). Sister-app
note documents the new shape so BCQT picks it up cleanly when integration
starts.

Pre-production hard-cut precedent from mig 035-041: same release
window. No grace alias. Sister-app note at
`.ai/sister-app-notes/2026-05-08-catalog-multi-source-and-vocab.md`.

## Manual test plan

Run after migration applied + tool shipped:

1. **Schema smoke**:
   - Login dev, browse `/clients/growatt-vn/catalog`. Verify list page
     renders with new columns (`source`, `status`, observation stats
     from view).
   - Run `pytest -q` — all 638 tests still pass with `materials.customs_code →
     material_code` renamed, `materials.internal_code` dropped, and
     `material_identity` field renames applied.
   - SQL spot check: `select count(*) from hub.materials where material_code is not null;`
     returns same count as `select count(*) from hub.materials;` (rename
     doesn't lose data).
2. **BCCT display bug fix (Pain 1)**:
   - Navigate to `/clients/growatt-vn/bcct/history/108130349500-1/1`.
     Before catalog-derive: "Mã NB" shows `007.0050100` immediately
     after resolver upgrade — even before catalog-derive runs — because
     `display`-fallback chain now picks `internal_code` (parser-extracted)
     before `customs_code` raw fallback.
   - This is the resolver behavior change effect. Pain 1 fix doesn't
     wait for catalog-derive completion.
3. **Catalog-derive flow**:
   - Open `/clients/growatt-vn/catalog/derive`. Configure rule:
     pattern `\((\d{3}\.[\w\-]+)\)`, source=bcct_rows, direction=import,
     min_observed_count=3.
   - Preview shows ~21,000 codes, sorted by live observed_count desc.
   - Click "Bulk apply" — codes inserted with `source=bcct_observed`,
     `status=under_review`.
   - Reload `/clients/growatt-vn/catalog?status=under_review`.
     `007.0050100` row visible with live observed_count from view.
4. **Provenance / lifecycle**:
   - On catalog list, promote `007.0050100` row → status=active,
     source=client_declared, promoted_at + promoted_by stamped.
   - After promote, BCCT history page for `108130349500-1/1` now
     shows `material_identity.resolution_status='resolved'` (was
     `resolved_pending_review` while under_review).
   - Tombstone test: tombstone an under_review row. Verify it
     disappears from active catalog but stays in audit (status='tombstoned').
5. **View staleness check (the original concern that drove view-not-column)**:
   - Upload new BCCT file containing `007.0050100` again. Reload
     catalog page. observed_count incremented immediately (live view,
     no manual refresh).
6. **Resolver `resolved_pending_review` status**:
   - For a row resolving to a `bcct_observed/under_review` material,
     verify `material_identity.resolution_status == 'resolved_pending_review'`.
   - Display chain returns the resolved code (consumer can render
     normally; UI may add a "needs review" badge based on status).

## Effort breakdown

Revised rev 4 — restored vocab rename per user principle. Multi-role
+ manual fields still deferred Phase 2.

| Phase | Estimate | Content |
|---|---|---|
| 1. Discovery + audit | 1 day | grep all `materials.customs_code` refs (SQL + Python + templates + tests) — separate from `bcct_rows.customs_code` / `code_mappings.customs_code` (semantically distinct, unchanged). Verify CO consumer sites. Confirm `v_material_roles` cascade-drop dependents. |
| 2. Mig 042 + backfill | 1 day | Schema rename + drops + adds + backfill + view recreate. Atomic single mig. |
| 3. Refactor `customs_code → material_code` Data Hub side | 1.5-2 days | Update all `materials.customs_code` SQL refs, Python dict reads, ORM-equivalent, templates. Run pytest until clean. |
| 4. Resolver update | 0.5-1 day | Drop 3 fields from struct, rename 2 fields. Add `resolved_pending_review` status. Update `_resolved`/`_empty_result` helpers. Update existing resolver tests. |
| 5. Catalog-derive tool — backend | 2 days | New table `catalog_derive_configs`. New route module `app/routes/catalog_derive.py` (list/save/preview/bulk-apply endpoints). re2 pattern validate. |
| 6. Catalog-derive tool — UI | 2 days | New page `/clients/<id>/catalog/derive`. Filter rule editor. Preview table (paginated). Bulk-apply. |
| 7. Catalog list page enhancements | 1 day | Status filter chip, source pill in row, observation stats columns from view, Promote + Tombstone actions. |
| 8. CO/BCQT adoption guide | 1-2 days | Thorough adoption guide doc (CO will adopt later, no live coordination). Cover: rename map (materials-scoped), material_identity field renames, display_code drop + 3-tier pattern, resolved_pending_review status, behavior change disclosure, end-to-end migration steps with grep commands. |
| 9. Tests + screenshots | 1 day | Unit tests for derive endpoints, integration for flow, Playwright for UI per memory `feedback_feature_folder_with_screenshots.md`. |
| **Total** | **~11-13 days** | |

vs rev 3 (~9-10 days): +2-3 days because vocab rename restored. User
explicitly accepts this cost for semantic correctness.

Could still slip 20-30% if CO consumer audit reveals unexpected
coupling. No way to know until grep runs.

## Out of scope (explicit deferrals)

Per critic round 2 + user override on rename: vocab rename of
`materials.customs_code → material_code` IS in scope (per user
principle). Phase 2 brief later for the deferrals below.

- **Multi-role `roles[]` array column on materials** — `v_material_roles.observed_roles[]`
  view already provides the live multi-role view. Adding stored `roles[]`
  on `materials` while keeping `category` = dual-source-of-truth trap.
  Phase 2 decides: drop `category` entirely or commit to `roles[]`.
- **Manual fields**: `production_source` (nk/sx), `hq_registration_no`,
  `hq_registration_date`, `supplier_hint`, `name_source`, `uom`. Lower
  priority than Pain 1 fix. Phase 2.
- **Code mapping (HQ↔NB) auto-derive** from BCCT — `code_mappings` has
  2,892 Growatt entries. Auto-deriving more is separate feature.
- **Materialized view** `v_material_roles` — keep as live view; promote
  to materialized only if perf becomes pain at 100k+ BCCT rows.
- **Auto-bootstrap from `barry-CO-main`** — defer until CO is live.
- **BTP_SX `derive_btp_shallows.py` integration** — Phase 3c script;
  keep separate until both ship.
- **Per-role HQ registration** — single `hq_registered` boolean for now.
- **API CRUD for `catalog_derive_configs`** — MVP UI-only.
- **`under_review` warning badge in BCCT view** — `resolution_status='resolved_pending_review'`
  available; UI rendering of "needs review" badge is Phase 2 polish.

## Decisions locked (2026-05-09)

1. **`resolved_pending_review` status name** — confirmed.
2. **Phase 1 / Phase 2 split** — confirmed. This brief = Phase 1
   (provenance + derive tool + vocab cleanup + Pain 1 fix). Phase 2
   later: multi-role, manual fields, supplier hints.
3. **Sister-app coordination strategy** — Data Hub ships first as
   hard cut. CO is currently on pause "to wait for Data Hub to
   stabilize"; CO + BCQT adopt at their own pace using the adoption
   doc. **No same-release-window coordination required.** Implication:
   - This brief ships independently. No grace alias.
   - Sister-app note → "**adoption guide**" instead of "coordination
     note". Written thoroughly so CO/BCQT teams pick up cleanly later.
   - Adoption guide covers: rename map (`customs_code → material_code`
     scope-limited to materials), `material_identity` field renames,
     `display_code` drop + 3-tier replacement pattern, status enum
     additions (`resolved_pending_review`), behavior change disclosure.
4. **Behavior change for `display_code`**: confirmed deliberate upgrade.
   3-tier consumer chain returns `internal_code` (parser-extracted)
   before `customs_code` (raw). Doc'd in adoption guide.
5. **`v_material_roles` cascade-drop dependents**: pre-implementation
   audit step.

## Files touched (estimated)

```
A db/migrations/042_*.sql                    (rename customs_code→material_code + schema additions + backfill + view extension + drop internal_code)
M app/resolvers/bcct_material_identity.py    (drop 3 fields, rename 2, add 'resolved_pending_review' status)
M app/routes/bcct.py                         (Mã NB column → 3-tier fallback compose; consumer pattern)
M app/routes/catalog.py                      (status filter, source pill, observation cols from view, promote/tombstone actions)
A app/routes/catalog_derive.py               (new — derive tool endpoints)
A app/templates/clients/catalog_derive.html  (new — derive UI)
M app/templates/clients/catalog.html         (status filter chip, source pill, observation cols, promote button)
M app/templates/clients/bcct.html            (Mã NB column → 3-tier fallback macro)
M app/templates/clients/bcct_history.html    (drop display_code references; show 3-tier components)
M app/seed.py                                (seed sample catalog_derive_config for growatt-vn)
M scripts/bootstrap_catalog_from_bcct.py     (deprecate or align with derive tool)
M scripts/settlement_resolver.py             (customs_code → material_code in materials refs; declared_internal_code → internal_code)
M scripts/detect_dual_source_btps.py         (same rename pass)
M scripts/bootstrap_btp_roster.py            (customs_code → material_code)
M scripts/feed_demo_company.py               (customs_code → material_code)
M scripts/onboard_client.py                  (customs_code → material_code)
M scripts/setup_clients_for_reingest.py      (customs_code → material_code)
M scripts/audit_pass2_deps.py                (customs_code → material_code)
M app/agent/tools.py                         (provenance jsonb access → source enum + view JOIN; rename)
M app/stores/provenance.py                   (drop seen_in_bcct logic; keep audit-only keys)
M app/stores/materials.py                    (column rename throughout)
M app/seed_master_data.py                    (rename)
M app/data_promotion.py                      (rename)
M app/parsers/derivations.py                 (rename refs to materials catalog lookup)
M app/resolvers/bcct_material_identity.py    (rename + drop fields + add 'resolved_pending_review' status)
A tests/test_catalog_derive.py               (new — derive flow)
A tests/test_catalog_observation_view.py     (new — view stays fresh after BCCT writes)
M tests/test_bcct_material_identity*.py      (update for dropped/renamed fields)
M tests/test_catalog*.py                     (update for new cols + view JOIN)
A .ai/sister-app-notes/2026-05-08-catalog-multi-source-and-vocab.md
A .ai/features/2026-05-08-catalog-multi-source/screenshots/*.png
```

Estimate: ~50-70 file touches, 1 migration, 1 new route module, 1
new template, ~10 test file updates. Vocab rename of `customs_code →
material_code` restored per user principle, so touch count back up.

Sister-app touch (separate repos):
- `barry-CO-main`: ~8-12 sites in app/data_hub_client.py, bom_service.py,
  main.py, plus any SQL queries referencing `materials.customs_code`.
- `BCQT-System`: forward-looking only.

## References

- Predecessor brief: `.ai/features/2026-05-08-configurable-bcct-parsing/brief.md`
- Sister-app note (this PR): `.ai/sister-app-notes/2026-05-08-catalog-multi-source-and-vocab.md` (TBD)
- Memory: `project_bom_code_multirole.md`, `project_bom_immutable_principle.md`,
  `feedback_naming_discipline.md`, `feedback_bom_vocab.md`,
  `reference_terminology_client.md`
- Critic-rejected proposals (avoided in this brief):
  - UNION code_mappings into Stage 1 resolution → violates catalog invariant
  - Merge `internal_code` rules with `material_identity_candidates` rules → conflates
    consumer contracts
  - Auto-fill catalog from BCCT without provenance → defeats catalog purpose
