# Adoption guide — catalog multi-source + vocab cleanup

**Released:** 2026-05-09
**Brief:** `.ai/features/2026-05-08-catalog-multi-source/brief.md` (rev 4)
**Migrations:** `042_catalog_material_code_rename_and_provenance.sql`,
`043_catalog_derive_configs.sql`
**Context:** Data Hub ships independently as hard cut. CO + BCQT adopt at
their own pace using this guide. CO is currently paused; BCQT has no live
consumer. No same-release-window coordination required.

---

## 1. SCHEMA RENAMES (`hub.materials` PK)

**`materials.customs_code` → `materials.material_code`**

Rationale: the column was mode-agnostic primary code (HQ bucket for
Growatt rule-mode, DNCX client ERP code for Johnson identity-mode,
parser-extracted code for new `bcct_observed` rows). Old name encoded
one accidental case as universal. Per user principle (memory
`feedback_naming_discipline.md`): semantic correctness > touch-site
convenience.

**`materials.internal_code` DROPPED.** Vestigial — 100% = customs_code in
every existing row across both clients. Either drop (this PR's choice)
or keep + document; we dropped.

**Unchanged (kept original semantics):**
- `bcct_rows.customs_code` — what's filed on customs declaration line.
  Accurate name; do not touch.
- `code_mappings.customs_code ↔ code_mappings.internal_code` —
  translation pair (HQ ↔ DNCX). Both names accurate in that context.

### Grep commands for CO/BCQT consumers

```bash
# Find materials-context references to update
grep -rn 'materials\.customs_code\|m\.customs_code\b' \
     app/ scripts/ tests/ --include="*.py" --include="*.sql"

# Python dict reads (materials catalog rows only — be careful NOT to
# touch dict reads on bcct_rows or code_mappings rows)
grep -rn '\["customs_code"\]\|\["internal_code"\]' app/ tests/

# SQL JOINs on materials
grep -rn 'JOIN hub\.materials\|join hub\.materials' app/ scripts/
```

For each match, check the table context:
- `hub.materials` (or `m.` alias for materials) → rename to `material_code`.
- `hub.bcct_rows` (or `b.` alias) → KEEP `customs_code`.
- `hub.code_mappings` → KEEP `customs_code` AND `internal_code`.

### Index renames

`materials_pkey` index name unchanged (doesn't encode column name).
`idx_materials_internal_code` dropped with column.

---

## 2. STRUCT FIELD CHANGES (`material_identity`)

API responses on `/v1/hub/bcct/*` carry a `material_identity` struct.
Six field changes:

| Old | New | Action |
|---|---|---|
| `declared_customs_code` | `customs_code` | RENAME (drop misleading "declared_" prefix; internal_code is parsed annotation, NOT formally declared) |
| `declared_internal_code` | `internal_code` | RENAME (same reason) |
| `display_code` | (dropped) | Consumer composes `resolved_code or internal_code or customs_code` 3-tier fallback |
| `bom_product_code` | (kept) | Same semantic; no change |
| `selected_candidate_code` | (kept) | Same semantic; no change |
| `resolution_status` | (extended) | New value `resolved_pending_review` for `bcct_observed/under_review` materials |

### Consumer migration patterns

```python
# OLD (pre-mig-042):
display = mi["display_code"]                     # opaque
internal = mi["declared_internal_code"]
customs = mi["declared_customs_code"]
resolved_for_join = mi["bom_product_code"]
best_candidate = mi["selected_candidate_code"]

# NEW (post-mig-042):
display = (mi.get("resolved_code")
           or mi.get("internal_code")
           or mi.get("customs_code"))             # 3-tier fallback
internal = mi.get("internal_code")
customs = mi.get("customs_code")
resolved_for_join = mi.get("bom_product_code")    # unchanged
best_candidate = mi.get("selected_candidate_code")  # unchanged
```

### CO consumer sites (audit reference)

Six known sites in `barry-CO-main`:
- `app/data_hub_client.py:415,426,438,538` — row normalizer
- `app/bom_service.py:266` — BOM lookup
- `app/main.py:1794` — display field

Pattern: each reads `display_code` as the canonical "best identifier for
this row". Replace with the 3-tier fallback above.

### Behavior change disclosure (NOT pure rename)

The new 3-tier chain returns parser-extracted `internal_code` BEFORE
falling back to raw `customs_code`. For rows where parser succeeded
but catalog didn't have the code, displayed value changes:

| Row case | Old `display_code` | New 3-tier chain |
|---|---|---|
| Resolved (catalog hit) | `resolved_code` | `resolved_code` (same) |
| Unresolved, parser extracted code | `customs_code` (raw) | `internal_code` (parser-extracted) — UPGRADE |
| Unresolved, no parser match | `customs_code` (raw) | `customs_code` (same) |

This deliberately fixes the BCCT view bug (rows showing HQ bucket "IC"
instead of agency code "007.0050100"). If your code asserted
`display_code == customs_code` for unresolved rows, that assumption no
longer holds.

### `resolution_status='resolved_pending_review'`

When the resolver hits a `bcct_observed/under_review` material (auto-derived
by the catalog-derive tool, awaiting staff promotion), it returns
`resolution_status='resolved_pending_review'` instead of `'resolved'`.
The resolved code is still set; the status flag tells consumers the
catalog row is provisional.

Consumer treatment:
- For DISPLAY: treat as resolved (use `resolved_code`).
- For WRITE-side validation (e.g. CO BOM lookup, BCQT settlement match):
  optionally require staff sign-off OR proceed with low-confidence flag.
- UI: surface a "needs review" badge.

Existing `resolution_status` values unchanged: `resolved`, `unresolved`,
`ambiguous`, `unverified`, `missing`.

---

## 3. NEW SCHEMA — `materials` columns

Five new columns added (provenance + state + manual fields):

| Column | Type | Default | Semantic |
|---|---|---|---|
| `source` | text enum | `'client_declared'` | `client_declared` / `bcct_observed` / `bom_observed` / `system` — where this row came from |
| `status` | text enum | `'active'` | `active` / `under_review` / `deprecated` / `tombstoned` — workflow state |
| `hq_registered` | boolean | NULL | Has this material been registered with HQ? |
| `promoted_to_declared_at` | timestamptz | NULL | When staff promoted from `bcct_observed/under_review` → `client_declared/active` |
| `promoted_by` | text | NULL | Who promoted (audit) |

**Backfill (already applied in mig 042):**
- Rows with old `provenance ? 'seen_in_bcct'` → `source='bcct_observed'`
- Rows with old `provenance ? 'registered_with_hq'` → `hq_registered=true`
- All others → `source='client_declared'`, `status='active'`

`materials.provenance` jsonb is NOT dropped. It still holds audit-only
keys:
- `btp_inferred` — Phase 3 BTP roster bootstrap audit (2580 rows)
- `registered_with_hq` sub-keys (first_seen, source_upload_id) for
  registration audit detail (4 rows)

The `seen_in_bcct` jsonb key was DROPPED — its data (decl_count,
first_seen, last_seen) is now derived live via `v_material_roles` view
(see below) so it never goes stale.

### Old `provenance` jsonb queries → new column queries

```sql
-- OLD
WHERE m.provenance ? 'seen_in_bcct'
WHERE m.provenance ? 'registered_with_hq'
WHERE NOT (m.provenance ? 'registered_with_hq')

-- NEW
WHERE m.source = 'bcct_observed'
WHERE m.hq_registered = true
WHERE m.hq_registered IS NULL OR m.hq_registered = false
```

```sql
-- OLD (stale cached counts)
SELECT m.provenance->'seen_in_bcct'->>'decl_count' as count

-- NEW (live aggregate via view)
SELECT vmr.observed_count
FROM hub.materials m
LEFT JOIN hub.v_material_roles vmr
       ON vmr.client_id = m.client_id AND vmr.material_code = m.material_code
```

---

## 4. VIEW EXTENSION — `v_material_roles`

Pre-existing fields (mig 033/034) all unchanged:
`client_id, material_code, declared_kind, has_imports, has_exports,
has_nvl_import, is_consumed_in_bom, has_own_bom, observed_roles,
is_multi_role, declared_observed_conflict`.

NEW columns added in mig 042:

| Column | Type | Computed via |
|---|---|---|
| `observed_count` | int | `count(distinct declaration_no) from bcct_rows` |
| `observed_first_at` | date | `min(registration_date)` |
| `observed_last_at` | date | `max(registration_date)` |
| `observed_directions` | text[] | `array_agg(distinct direction)` |

**Note:** view's primary key column was `customs_code`, now `material_code`
(mirrors materials table rename).

These are LIVE — recomputed each query. After any BCCT upload, these
update immediately without manual refresh. Do not cache them on the
materials table.

---

## 5. NEW TABLE — `catalog_derive_configs`

Rule-engine table for the catalog-derive tool. Powers the new
`/clients/<id>/catalog/derive` page in Data Hub. Sister apps don't
write to this table — read-only for diagnostics.

Schema:
```sql
config_id          bigserial PK
client_id          text FK
name               text
source_table       text ('bcct_rows' | 'bom_edges')
pattern            text   -- re2 regex
source_field       text   -- default 'goods_name'
match_group        int    -- default 1
direction_filter   text[] -- nullable
min_observed_count int    -- default 1
date_from          date
date_to            date
default_status     text   -- 'under_review' | 'active'
default_category   text   -- 'nvl' | 'tp' | etc.
enabled            boolean
created_at, created_by, updated_at, updated_by
```

ReDoS protection: same `google-re2` validator as `client_parser_rules`.

---

## 6. MIGRATION CHECKLIST FOR CO/BCQT

When ready to adopt:

1. **Data Hub schema is on mig 042+043 already.** Sister-app code can
   start consuming new fields immediately.
2. **Pull latest schema doc** — read `db/migrations/042_*.sql` and
   `043_*.sql` for the complete migration steps.
3. **Refactor SQL JOINs** on `materials.customs_code` → `material_code`.
   Use grep commands above.
4. **Refactor `material_identity` consumer reads:**
   - `display_code` → 3-tier fallback (or pick the level you need:
     resolved_code, internal_code, or customs_code).
   - `declared_customs_code` → `customs_code`
   - `declared_internal_code` → `internal_code`
5. **Test** for the behavior change: rows where `resolved_code is None`
   AND `internal_code is set` will display the parser-extracted code
   instead of customs_code raw. Verify this is what you want.
6. **Branch on `resolution_status='resolved_pending_review'`** if
   applicable. For settlement / origin cert workflows, you may want to
   defer write actions until the catalog row is promoted to
   `client_declared/active`.
7. **Drop legacy provenance jsonb queries** — replace with
   `source` / `hq_registered` column queries OR view JOIN for live
   observation stats.

## 7. WHAT'S NOT CHANGED

- `bcct_rows` schema unchanged (except prior mig 035-041).
- `code_mappings` schema unchanged.
- `bom_artifacts.product_code`, `bom_edges.parent_code/child_code/root_code`
  unchanged.
- API endpoints (`/v1/hub/*`) URLs unchanged. Only response-body field
  names changed.
- Auth, JWT, service tokens unchanged.

## 8. CONTACT

Brief: `data-hub/.ai/features/2026-05-08-catalog-multi-source/brief.md`
Predecessor brief (mig 035-041): `.ai/features/2026-05-08-configurable-bcct-parsing/brief.md`
Memory entries (Data Hub repo):
- `feedback_no_derived_in_source.md`
- `feedback_naming_discipline.md`
- `reference_terminology_client.md`
