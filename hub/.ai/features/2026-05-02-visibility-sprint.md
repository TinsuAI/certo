# Visibility sprint — catalog provenance + staleness + LLM-gate cement

**Date:** 2026-05-02 | **Status:** in-progress (autopilot)

Three coupled bits, all about making hidden state visible to staff:

1. **A2 — BCCT LLM-confirm gate cement.** Already shipped via Phase 2's `_ingest_rows` universal stash (commit `359ebec`); STATUS follow-up #1 is stale. Lock with a regression test asserting `parse_mapping_confirm` redirects to `/upload/preview/{pending}`.
2. **A3 — Staleness metadata bar.** Two-line strip at top of BCCT/Catalog/BQD/BOM tabs: `Lần upload cuối: …` + `Dữ liệu gần nhất: …`. Two `MAX()` queries per tab, no caching needed at current scale.
3. **A4 — Catalog multi-source provenance.** `hub.materials.provenance jsonb` capturing per-source first-seen + last-seen. Auto-derive from `bcct_rows` on every BCCT upload. Visual badges + filter + audit alarm "X codes on declarations but unregistered."

## Why

Phase 1+2+3 made parsers safe and confirmable. Next gap: staff still can't easily see *what's stale, what's missing, what arrived from where*. A2/A3/A4 surface those signals without changing core behaviour.

## A2 — Gate cement

Verify with a route-level integration test (or, if TestClient pattern is too invasive for this codebase, an SQL+helper-call test exercising `parse_mapping_confirm` semantics directly). Update STATUS + BACKLOG to remove stale follow-up #1.

## A3 — Staleness metadata

**Schema:** none. Pure read.

**Helper:** `app/stores/staleness.py:tab_freshness(client_id, module) -> {last_upload_at, last_data_at}`.

| Module  | last_upload_at                                                                  | last_data_at                                       |
|---------|---------------------------------------------------------------------------------|----------------------------------------------------|
| bcct    | `MAX(parsed_at)` on `file_uploads WHERE module='bcct' AND parse_status='done'` | `MAX(registration_date)` on `bcct_rows`            |
| catalog | same with `module='catalog'`                                                   | `MAX(updated_at)` on `materials`                   |
| bqd     | same with `module='bqd'`                                                       | `MAX(updated_at)` on `code_mappings` (or first-seen) |
| bom     | same with `module='bom'`                                                       | `MAX(created_at)` on `bom_versions`                |

**Template:** new `clients/_staleness_bar.html` partial; included at top of each tab template; renders bilingual labels + relative-time ("2 ngày trước") via existing i18n.

**Done criteria:** all 4 tabs show 2-line bar with non-null values where data exists; gracefully shows `—` when empty.

## A4 — Catalog provenance

### Schema

Migration `014_catalog_provenance.sql`:

```sql
alter table hub.materials
  add column if not exists provenance jsonb not null default '{}'::jsonb;

create index if not exists idx_materials_provenance_seen_bcct
  on hub.materials ((provenance ? 'seen_in_bcct'));
```

`provenance` shape (per row):
```json
{
  "registered_with_hq": {"first_seen": "...", "source_upload_id": "..."},
  "seen_in_bcct":       {"first_seen": "...", "last_seen": "...", "decl_count": 3},
  "user_added":         {"first_seen": "...", "added_by": "u_..."}
}
```

Each key optional. Presence = signal. Boolean badges derived in template:
- ✓ HQ-registered = key `registered_with_hq` present
- ⚠ Seen on declaration but not registered = `seen_in_bcct` present AND `registered_with_hq` absent
- 📥 User-added = `user_added` present AND others absent

### Auto-derive from BCCT

After every successful BCCT confirm (in `_apply_bcct_rows`), enqueue (or run inline — it's a single SQL aggregate):

```sql
insert into hub.materials (dncx_id, customs_code, name, category, status, provenance)
select %(client_id)s, customs_code, max(goods_name), 'nvl', 'active',
       jsonb_build_object('seen_in_bcct',
         jsonb_build_object('first_seen', min(registration_date),
                            'last_seen',  max(registration_date),
                            'decl_count', count(distinct declaration_no)))
from hub.bcct_rows
where client_id = %(client_id)s
  and customs_code is not null and customs_code <> ''
  and customs_code = any(%(touched_codes)s)
group by customs_code
on conflict (dncx_id, customs_code) do update set
  provenance = hub.materials.provenance ||
               jsonb_build_object('seen_in_bcct', excluded.provenance->'seen_in_bcct');
```

`touched_codes` = distinct customs_codes from the just-applied BCCT batch. Scoped to avoid re-scanning the table.

**Default category** for auto-derived rows = `'nvl'` (Nguyên Vật Liệu — most common). Staff can re-categorize in catalog UI later.

### Existing catalog upload + provenance

Upload-via-Excel sets `registered_with_hq` provenance:

```python
provenance = {"registered_with_hq": {"first_seen": now, "source_upload_id": upload_id}}
```

User-added (manual entry, deferred — not in MVP):
```python
provenance = {"user_added": {"first_seen": now, "added_by": user_id}}
```

### UI

`templates/clients/catalog.html`:
- Per-row badge column (or inline beside name)
- Filter dropdown: all / registered / unregistered-but-seen / user-added
- Top-of-page alert IF `count(unregistered-but-seen) > 0`:
  `⚠ N mã có trên tờ khai nhưng chưa đăng ký HQ` linking to filtered view

### Done criteria

- Upload BCCT row with new customs_code X → catalog gets row X with `seen_in_bcct` provenance.
- Upload catalog Excel containing X → catalog row X gains `registered_with_hq` provenance (existing keys preserved).
- Catalog page shows correct badges + filter works.
- Audit alarm shows non-zero count when applicable.

## Risks

- **A4 auto-derive on every BCCT upload could slow large batches.** Mitigated by `customs_code = any(touched_codes)` scoping to upload batch. Worst case ≤ ~5k codes per batch.
- **Backfill for existing data.** All current `materials` rows have `provenance = '{}'`. Migration backfills rows that have any `bcct_rows` reference (single one-shot UPDATE … FROM bcct_rows GROUP BY).
- **Default category 'nvl' is wrong for some codes.** Acceptable — staff re-categorizes in catalog UI; provenance signal is independent of category.
- **Race on concurrent upload + catalog upload of same code.** Both go through `ON CONFLICT DO UPDATE` with `||` jsonb merge. Last-write-wins per provenance key, but keys are independent → no data loss.

## Manual test plan

1. Fresh BCCT upload to growatt-vn → confirm gate → ingest. Visit catalog. New customs_code rows show ⚠ badge.
2. Upload catalog Excel with one of those codes. Refresh catalog. Code now shows ✓ badge.
3. Filter by "unregistered-but-seen" → only ⚠ rows.
4. Visit BCCT tab → top bar shows last-upload + last-data dates.
5. Visit BOM tab → similar bar.

## Test plan (pytest)

- `test_visibility_sprint.py`:
  - `test_parse_mapping_confirm_routes_through_preview_gate` (A2 cement)
  - `test_tab_freshness_returns_max_dates` (A3 helper)
  - `test_tab_freshness_handles_empty_module` (A3 edge)
  - `test_provenance_seen_in_bcct_after_apply` (A4)
  - `test_provenance_registered_after_catalog_upload` (A4)
  - `test_provenance_merge_preserves_existing_keys` (A4)
  - `test_provenance_index_used_for_filter` (A4 perf, optional)

## Out of scope

- Notification system + chat-agent (those are Sprint B if runway permits)
- Cross-app SSO (Sprint B)
- BACKLOG cross-cut items (header_row unit tests, normalize_header cache, expires_at GET guard, CSRF)
