# Session 2026-05-10 — Mã chờ duyệt + cross-source warnings + UoM standards

Single-commit session: `d734918` on `main`. 71 files changed, 7089 insertions, 928 deletions. Tests 644 → 772.

## What Was Done

### 1. Mã chờ duyệt (passive candidate feed)

Replaced the deferred `catalog_derive` wizard. State machine on new
`hub.catalog_candidates` table (pending/accepted/rejected, sticky
across refresh). Watches BCCT + BOM + code_mappings continuously.

- **Schema (mig 047)**: drop `catalog_derive_configs`; create
  `catalog_candidates`; add `materials.code_kind` + Phase 2 manual
  fields (production_source, supplier_hint, uom).
- **Per-row 4-case classification** in `app/parsers/catalog_candidates.py`:
  dual (NB ≠ HQ) / unified-overlap (NB == HQ same row) / HQ-only
  (no paren) / NB-only (customs_code='.').
- **Post-aggregation collapse** — same string code with no co_occurrence
  evidence collapses to unified (avoids 3-row noise from per-source
  classification).
- **Refresh** rebuilds stats from truth (deletes auto-decrement); status
  sticky (no clobber).
- **Bidirectional auto-mapping on Accept** — scans BCCT pairs, inserts
  `code_mappings` for existing materials only. Idempotent ON CONFLICT.
- **Routes** (`/catalog/candidates/...`): page (filter + search +
  pagination), candidate detail, accept, reject, unreject.
- **Toast consistency**: accept/reject/unreject all show `<code>` +
  link to relevant detail.

### 2. Candidate richness (mig 048 + 049)

Iteration after user feedback ("code+kind+sources alone — what can
staff do with that?"):
- mig 048: import_count, export_count, decl_count, bom_role,
  bom_sample, co_occurrence_count.
- mig 049: hs_code (most common), hs_alternates_count, uom (canonical),
  origin, inferred_production_source.
- BOM role classification: tp_root (artifact.product_code) / btp_sx
  (parent in edges, not tp_root) / nvl_leaf (only as child).
- BCCT cross-ref backfill for sample_text (any BOM-only candidate
  whose code appears as customs_code → pull goods_name).

### 3. Multi-kind collapse + classification fixes

User flagged: code `001.0069500` should be unified, not 'nb'. Three
candidate rows for same string due to per-source classification.

Fix: `_collapse_unaffiliated_kinds` post-aggregation. Same string with
multiple kinds AND empty co_occurrences (never paired with different
code) → collapse to unified. Mig 050 also re-runs materials backfill
with smarter logic (code_mappings self-loop OR same-string
customs/paren overlap → unified). Reclassified 122 Growatt materials
correctly.

### 4. Material detail enhancements

- **Cross-source warnings panel** (`app/stores/catalog_warnings.py`):
  hs_drift, uom_drift, origin_drift, direction_drift, mapping_drift.
  Severity-sorted with evidence drilldown.
- **Audit history elegant** (`app/stores/catalog_audit.py`): replaces
  raw jsonb pre-block with field-level diff (`field: old → new` red
  strikethrough → green). Skips noisy fields (created/updated_at).
- **Inline edit panel**: collapsible form on detail page (separate
  `/edit` page kept).
- **NB↔HQ mapping panel**: redesigned from technical "1 liên kết
  PV01.X" into narrative ("Mã HQ DIENTRO bao gồm 131 mã nội bộ:" +
  visual flow with badges). Self-loop detection separate banner.
- **Loại mã row** in state table.

### 5. Candidate detail view

`/clients/<id>/catalog/candidates/<id>` (new). Shows full info per
candidate: signals, suggestions, co-occurrences, BCCT samples (linked
to bcct/history), BOM artifacts (linked to catalog/bom detail),
inline accept/reject form.

### 6. UoM standardization (mig 051 + admin UI)

Reused existing `hub.uom_canonical` + `hub.uom_aliases` (mig 021).
Mig 051 extends with 10 new packaging canonicals (roll/pair/box/
sheet/bottle/bag/cay/thanh/vien/thung) + ~50 aliases for real BCCT
data (PIECES, METRES, KILO-GRAMMES, ROLL, PAIR, METRIC-TONS, ...).

`app/stores/uom_standards.py`:
- `resolve_canonical(alias)` / `dimension_of(uom)` / `convert(value,
  from, to)` / `are_equivalent(a, b)`.
- CRUD: `list_canonicals_with_alias_count`, `list_aliases`,
  `create_canonical`, `create_alias`, `delete_alias`.
- In-process cache, cleared on mutation.

Wired into:
- `_uom_drift` warning de-noise (synonyms PCS/PIECE/ST → 1 canonical
  → no warning).
- Candidate refresh (canonical UoM picked, e.g. 2432 Growatt
  candidates resolve to `pcs`).

Admin UI at `/admin/uom` — list + add canonical/alias + delete alias.
Permission: `can_manage_users` (admin/dev).

### 7. Cross-link audit + click-to-detail consistency

User: "trong các view, rà soát lại xem cái nào có thể link được đến
view detail của cái khác, thì bổ sung link ngay".

- Catalog list: code cell now links to detail (was 🔍 icon at row end).
- Rejected candidates: code links to candidate detail.
- Co-occurrences in candidate detail: code links to catalog detail
  + sublink "tìm trong feed" via search.
- BCCT samples in candidate detail: declaration_no links to bcct/history.
- BOM artifacts in candidate detail: product_code links to catalog
  detail; artifact link kept.

### 8. Catalog list polish

User: "Loại mã viết tắt cho tiết kiệm chiều ngang; tên truncate; bỏ
cột Chi tiết cuối cùng đi".

- Loại mã: NB / HQ / TN abbreviations + tooltip with full label.
- Name: truncated at ~28ch + ellipsis + title hover.
- Removed Chi tiết column (rely on click-to-detail on code).
- Vertical-center alignment on 4 badge columns (Khai báo, Vai trò,
  Nguồn, Trạng thái).
- Removed dead `catalog/derive` link, replaced with `catalog/candidates`.

### 9. Workaround for v_material_roles paren-blindness

`app/stores/material_observations.py` — request-time recompute for
material detail page. View JOINs by `bcct_rows.customs_code` only,
misses Growatt NB codes via paren extract. Workaround uses
`load_rules` per client; generic, not Growatt-specific.

Captured proper fix in BACKLOG with removal trigger.

## Decisions Made

### D1 — Mig 047 backfill regex-only was a mistake; fix via mig 050

Initial backfill matched material_code against parser-rule patterns
to assign `code_kind='nb'`. But `001.0069500` matches paren pattern
yet has self-loop in `code_mappings` (NB == HQ for that material)
→ should be 'unified'. Mig 050 fixes via 2 priority rules:
1. self-loop in code_mappings → unified
2. same-string customs/paren overlap in BCCT → unified

User insight: backfill is data fix; live ingest classification was
already correct (Case 2: NB == HQ overlap returns 'unified').

### D2 — Multi-kind collapse logic uses co_occurrences as signal

Same string code can be classified as different kinds across
different BCCT rows. Without collapse, agg ends up with 2-3 candidate
rows for same string (PV01.0116400 had 3: nb/hq/unified from 3
sources). Decision: collapse if no kind has co_occurrences (paired
with DIFFERENT code in BCCT). Real bucket-style HQ codes (DIENTRO)
have many paired NBs → keep separate kinds.

### D3 — BOM leaf does NOT auto-suggest 'nvl'

Per `project_bom_3_shapes.md` — shallow BOMs stop at first leaf
(BTP OR NVL). A "leaf" might be a purchased BTP_NM. Decision:
`_suggest_category` doesn't auto-pin 'nvl' for `bom_role='nvl_leaf'`
when no BCCT direction signal — leaves None for staff.

### D4 — material_observations.py is a workaround, not architecture

Inline supplement in route handler was ugly (50 lines string-concat
SQL + duplicate paren-extract). Refactored to clean module + 5 unit
tests. Acknowledged as workaround in module comment + BACKLOG entry
with 3 proper-fix options + removal trigger.

User: "fix tạm thời kia có phải làm xấu code và too growatt-specific
không?" → confirmed not Growatt-specific (uses configurable rules)
but ugly inline. Refactored.

### D5 — Reuse existing uom_canonical/uom_aliases (mig 021)

Initial mig 051 tried to recreate the table with my own schema
(canonical_code/dimension/uom_conversions). Then discovered existing
schema (uom_code/family/base_factor + uom_aliases). Pivoted to
extend existing tables — `base_factor` model is cleaner anyway
(implicit conversions within family).

### D6 — UoM admin permission = can_manage_users

UoM standards are agency-wide, not per-client. Used same permission
gate as declaration_types and client_type_presets (admin/dev only).
Per-client `client_uom_aliases` deferred until first conflict.

### D7 — UX consistency deferred

User raised inconsistency in UI (search box position, sortable
headers, action column shapes). I captured 4 options via
AskUserQuestion. User said "thôi bỏ qua cái này đi, later". Captured
as soft backlog (not added to file). Will surface again next time.

### D8 — Big single commit instead of multiple feature commits

71 files in d734918. Considered splitting (mig 047 chunk, mig 048
richness, mig 049 enrichment, mig 050 backfill fix, mig 051 UoM,
admin UI). Decided single commit because:
- All driven by same feature evolution (Mã chờ duyệt iterations)
- Each migration depends on prior in same session
- Body of commit message lists all changes clearly
- User explicitly asked "commit di"

## What Didn't Work

### Mig 047 with NOT NULL + no DEFAULT on materials.code_kind

Initial mig dropped the default after column add. Existing INSERT
sites didn't pass code_kind → broke 60+ tests. Reverted: keep
`default 'unified'`. Constraint protects via CHECK.

### SQL `(col1, col2) NOT IN (subquery)` with tuple-of-tuples binding

psycopg doesn't support binding tuple-of-tuples directly to
multi-column IN. Switched to `WHERE NOT EXISTS (SELECT 1 FROM
unnest(%s::text[], %s::text[]) AS t(c, k) WHERE ...)` with separate
arrays.

### Mig 047 SQL backfill was too aggressive

Pattern-only regex (`material_code ~ '\d{3}\.\w+'` → 'nb') misclassified
122 Growatt materials that had self-loops in code_mappings. Fixed in
mig 050 with smarter rules (see D1).

### Initial v_material_roles supplement inline in route

Crammed ~50 lines of SQL string-concat + Python re-extract directly
into the detail handler. User correctly called it out as code smell.
Refactored to `app/stores/material_observations.py` with 5 tests.

### Initial mapping panel UI was technical noise

"Quy đổi mã (code_mappings) 1 liên kết / Mã này là NB → các HQ
buckets (1) / PV01.0105100" — confusing technical labels especially
for self-loop case. User said "không hiểu gì cả". Redesigned with
narrative + visual flow.

### Auto-detect direction labels for self-mapping table query

Initial SQL had direction tags swapped: `where internal_code=X` was
labeled `'as_hq'` (meant "this material is HQ") when it actually
means material is NB. Caught when verifying DIENTRO showed wrong
narrative. Fixed by swapping labels.

### NB/HQ/TN abbreviations vs full Vietnamese names

First implementation used full names ("Nội bộ" / "Hải quan" / "Thống
nhất"). User: "Badge Thống Nhất viết đầy đủ, HQ với NB lại viết tắt
→ inconsistent". Switched to all abbreviations + tooltip.

User next: "view danh mục: Loại mã viết tắt cho tiết kiệm chiều
ngang" → confirmed direction.

### UoM standardization initial schema collision

Created mig 051 with my own `uom_canonical` (canonical_code/dimension)
without realizing mig 021 already has `uom_canonical` (uom_code/
family/base_factor) + `uom_aliases` already populated for the flatten
engine. Pivoted to extend existing.

### Admin UoM view T2 screenshot showed notification panel popup

Notifications popup interfered with screenshot. Page underneath
visible enough to verify but not clean. Acceptable, didn't re-shoot.

## Open Items

### UoM admin UI polish (user explicit defer)

User: "chưa hài lòng lắm, sẽ quay lại sau". Specific items captured
in BACKLOG entry:
- Edit canonical (family / base_factor) inline.
- Delete canonical with FK protection.
- Conversion factor explorer.
- Group aliases per canonical visually.
- Per-client `client_uom_aliases` override + UI.
- Tooltip / docs for `base_factor` model.

### v_material_roles paren-aware (proper fix)

`material_observations.py` workaround in place. BACKLOG entry has 3
options + recommendation (option 2: generated column on bcct_rows
via trigger). 1-1.5d effort. Removal trigger documented.

### UI consistency normalization (deferred)

User raised: search box position, sortable headers on candidate feed,
action column shapes. 4 options captured but user said "thôi bỏ qua,
later".

### Manual UI tests not all completed

User tested A1-C1 from checklist + accepted multiple changes
verbally based on programmatic verification + screenshots. Full
tests F1-F2 (permission), C3 (auto-mapping verify in DB), some
others not visually confirmed by user — acceptable since unit tests
cover.

### Compound UoM aliases not normalized

"Kiện/Hộp/Bao/Gói" (multi-unit string) doesn't resolve via
`resolve_canonical`. 3 such cases in Growatt. Acceptable — staff
hand-classify on Accept. If becomes pattern, add splitter helper.

### candidate_richness Phase 2 (BACKLOG)

User: "mỗi candidate phải có các trường thông tin gần như 1 row
trong catalog". v3 added 6 columns (hs/uom/origin/etc); Phase 2 in
BACKLOG would surface deeper data (e.g., BCCT row link evidence
under HS code badge for click-thru).

### BCCT presence of `001.0001100` not via customs_code

Diagnosis: 0 via customs_code, 68 via paren extract. View
v_material_roles missed → workaround supplements. After proper view
fix, list page (`/catalog`) "Quan sát BCCT" column also gets correct
counts for paren-extract NB materials.
