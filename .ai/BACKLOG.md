# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

---

## BOM dependency staleness / invalidation

**Captured 2026-05-10** trong session BOM vocab + 3-shape audit
(`.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md`,
Track D). Splits-off vì scope >> tracks A+B+C tổng cộng.

**Vấn đề:** BOM artifact (shallow + full_flat materialized) chứa derived
fields phụ thuộc external state. Khi external thay đổi, artifact stale
silently. 0 centralized tracking.

**8 chiều staleness đã xác định:**

1. Catalog category change (nvl → btp_sx → walking stop set khác)
2. BTP BOM xuất hiện sau (was-leaf BTP → decomposable)
3. Catalog Accept (mã chờ duyệt → previously-unknown classified)
4. Code mappings update (NB↔HQ resolution shift)
5. Parser rules edit (`client_parser_rules` → derived internal_code shift)
6. UoM standards/aliases mở rộng (alias mới resolve canonical)
7. `materials.uom` edit (flatten convert factor change)
8. `btp_sourcing` decision flip (preset sourcing override change)

**Current state — partial mitigation:**

- `scripts/materialize_shallow_and_full_flat.py` — manual.
- `derive_btp_shallows.py` (BACKLOG "Phase 3c follow-ups") — manual.
- `post_ingest_hooks` adapter contract scaffolded, chưa wire vào
  confirm flow.
- `material_observations.py` — request-time recompute (workaround
  per BACKLOG "v_material_roles paren-aware").
- `catalog_candidates` refresh — manual button click.

**Design options (chưa pick — discovery cần thêm 1-2d):**

1. Staleness flag + manual refresh button (`is_stale` + `stale_reason`
   columns + triggers + UI badge). Pros: simple, transparent. Cons:
   noisy với churn cao; mỗi dependency cần trigger.
2. Eager invalidation cascade (write tới catalog/mappings/parser_rules
   trigger materialize() async). Pros: artifact luôn fresh. Cons:
   complex job infra; thrash; opaque.
3. Lazy compute on read (bỏ materialized, on-demand). Pros: simple
   correctness. Cons: latency BCQT/CO consumer reads (Johnson 246 TP
   × 3 shape × ~10s = 2h batch).
4. Event-sourced staleness ledger (`hub.dependency_invalidations`
   table; triggers append; refresh = job dequeue). Pros: full audit
   trail, aligns "aggregate-data git-history" principle. Cons: thêm
   table + job runner; design overhead lớn.

**Preliminary recommendation:** Option 1 MVP-mode → option 4 khi
bandwidth có. Option 2 quá tham; option 3 quá chậm.

**Why deferred:**
- Scope >> tracks vocab+group+UoM-gate combined. Riêng discovery
  ~1-2d.
- Cần audit dependency edges trước khi pick option.
- Phụ thuộc track B (lineage_root_id) nếu invalidate group-wise.
- Không block MVP demo — current manual re-run + view-time recompute
  đủ cho pre-customer.

**Cross-links** (overlap dimension):
- "Modular BOM ingest adapters (per supplier shape)" — `post_ingest_hooks`
  contract sẽ là vehicle cho option 1/2.
- "Aggregate-data git-history" — option 4 là implementation cụ thể của
  principle này cho BOM dimension.
- "v_material_roles paren-aware" — view-time recompute pattern, kéo
  dài hoài là dấu hiệu cần option 4.
- "Phase 3c follow-ups" → "Auto-trigger derive_btp_shallows from upload
  confirm flow" là 1 fragment của option 1.

**Bring back when:**
- A+B+C ship.
- User signal "có customer thật, cần fresh artifacts khi churn".
- Hoặc khi 1 incident xảy ra (catalog edit không trigger materialize,
  consumer read stale data → khiếu nại).

**Effort khi scope:**
- 1-2d discovery + design.
- 2-4d implement option 1 (flag + 8 triggers + UI badge + refresh
  route).
- 1-2 week implement option 4.

---

## BOM UoM conversion engine (ingest-time + refresh-time)

**Captured 2026-05-11** trong session test Track D Phase 1 trên
real Johnson data (`0000082212` PIECES → KG → PIECES). Phát hiện
gap fundamental: stale flag đánh dấu đúng nhưng Refresh KHÔNG
convert UoM thực sự — chỉ re-derive với raw SQL bypass flatten
engine.

**Vấn đề gốc:**

Hiện tại 3 layer xử lý UoM khác nhau, **không nhất quán**:

1. **`bom_edges` raw layer** — fidelity tuyệt đối, lưu nguyên UoM
   user upload. Không bao giờ convert. Đúng theo principle
   immutable.
2. **`bom_artifact_rows` derived layer (shallow + full_flat)** —
   `materialize_shallow_and_full_flat.py` SQL chỉ multiply qty qua
   chain, copy `e.uom` từ raw edges. **Không consult `materials.uom`,
   không gọi `uom_conversions`.** Output luôn cùng UoM với raw —
   ngay cả khi catalog có UoM khác.
3. **Flatten engine `app/flatten/uom.py`** — DOES handle UoM
   conversion qua `uom_conversions` (same-family) + emits
   unresolved decision (cross-family). Nhưng chỉ dùng trong flatten
   preview flow, KHÔNG dùng trong materialize_shallow_and_full_flat.

→ Catalog UoM = "UoM canonical mà downstream nên dùng" về mặt
intent, nhưng derived layer hiện tại không respect catalog UoM.

**Insight key từ user (2026-05-11):**

> "Convert phải làm từ lúc ingest, không phải chỉ refresh."

Ingest preview phải:
- Detect drift giữa file UoM và catalog UoM.
- **Hiển thị rõ** rows nào sẽ convert, factor được dùng (từ
  `uom_conversions` hay `material_uom_factors` — xem dưới), nguồn
  factor (auto / staff manual / supplier data).
- Staff actions:
  - Confirm convert as-shown → ingest với UoM = catalog.
  - Edit factor inline (one-shot cho upload này).
  - Edit conversion table (admin route, persist).
  - Skip convert (giữ UoM file, mark stale flag để track).

Tương tự tại refresh-time: hiển thị conversion plan, cho staff
edit factor trước khi commit re-derive.

**Cross-family case có business demand thật** (per user feedback):

Ví dụ: BOM ghi 1000 PIECES, catalog ghi KG. Không có universal
factor — phụ thuộc vật chất. Cần `hub.material_uom_factors` table
+ UI prompt khi factor missing.

```sql
create table hub.material_uom_factors (
  factor_id text primary key,
  client_id text not null,
  material_code text not null,
  from_uom text not null,        -- canonical
  to_uom text not null,          -- canonical
  factor numeric not null check (factor > 0),
  source text not null check (source in (
    'staff_manual', 'supplier_data', 'packaging_spec',
    'derived_average', 'imported'
  )),
  set_by text not null,
  set_at timestamptz default now(),
  notes text,
  unique (client_id, material_code, from_uom, to_uom)
);
```

**Scope Phase 2 (estimated discovery 1-2d, implement 1-2 weeks):**

A. **Ingest-time conversion preview**
   - Enhance `compute_uom_drifts` → emit conversion plan per row.
   - BOM upload preview UI: table show "row X: file=1000 gam,
     catalog=kg, factor=0.001 (uom_conversions), result=1 kg
     [confirm | edit factor | edit table]".
   - BCCT upload preview: tương tự.
   - Cross-family + factor missing → block confirm hoặc require
     ack + flag.

B. **Refresh-time conversion (rewire)**
   - `_rederive_shape` thay raw SQL bằng `flatten_engine.flatten()`.
   - Engine tự lookup `uom_conversions` (same-family) +
     `material_uom_factors` (cross-family) + `client_uom_overrides`.
   - Output rows với target UoM = catalog UoM.
   - Same hash → dedup → no change. Different hash → mint new
     artifact, tombstone old.

C. **`material_uom_factors` table + admin UI**
   - Mig 054+ adds table.
   - Catalog detail page: section "Conversion factors to other
     UoMs" + add/edit/delete buttons.
   - When staff edit catalog UoM cross-family → dialog prompt
     "factor để convert PIECES → KG?" → save vào table → refresh.
   - Bulk import factors từ supplier sheet (nice-to-have).

D. **Conversion audit trail**
   - Every materialize/refresh logs which factors were used.
   - `bom_artifact_rows` stores `source_uom` + `applied_factor_id`
     nullable cho derived rows (forensics).

**Cross-app impact:**
- BCQT consumer reads BOM expecting catalog UoM. Currently gets
  raw UoM → wrong settlement calculations. Phase 2 fix this.
- CO consumer similar.
- Sister apps cần update khi behavior thay đổi (artifact rows UoM
  switches từ raw to catalog).

**Why Phase 2 (defer not skip):**
- Phase 1 ship được vì stale flag đã đúng semantic ("cảnh báo
  staff", "manual review").
- Conversion logic phức tạp, đặc biệt UI staff-facing cho factor
  management.
- Cross-family case cần per-material data thực tế từ customer —
  blind defaults sai.
- Cross-app coordination cần (BCQT/CO consumer behavior expects
  current shape).

**Bring back when:**
- Có customer thật ingest BOM với UoM khác catalog quy định.
- Hoặc khi 1 incident xảy ra (settlement Mẫu 15a output sai vì
  UoM lệch).
- Hoặc khi cross-family factor data có sẵn từ supplier.

**Cross-links:**
- "BOM dependency staleness" (above) — Phase 1 staleness flag đã
  ship; Phase 2 conversion là partner natural.
- "UoM standardization table" (below, SHIPPED) — `uom_conversions`
  + `uom_aliases` đã có same-family logic; chỉ cần wire vào
  refresh + preview.
- Track C (UoM ingest gate, shipped 2026-05-10) — mới surface
  drift, không mutate. Phase 2 promote thành mutate-with-confirm.

**Effort khi scope (rough):**
- A (ingest-time): 3-4d. Enhance compute_uom_drifts + 2 preview
  UIs + tests.
- B (refresh wire flatten engine): 1-1.5d.
- C (factor table + admin UI + edit dialog): 3-4d.
- D (audit trail): 1d.
- **Total: 1.5-2 weeks** + 1-2d discovery.

### Phase 3 follow-ups (sau khi Phase 2 UoM conversion ship)

Captured 2026-05-11 user feedback. Phase 3 unblocks chỉ sau khi
Phase 2 (UoM conversion engine) đã ship — vì 2 cái đầu rely on
"refresh = thực sự re-derive với conversion".

**E. Manual_flat artifacts cũng cần signal UoM mâu thuẫn**

Track D Phase 1 cố ý exclude `manual_flat_as_provided` khỏi
trigger filter (lý do: source artifact, immutable, không re-derive
được). Nhưng manual_flat vẫn có thể **mâu thuẫn semantic** với
catalog: file ghi 5 kg, catalog ghi PIECES → BCQT consumer đọc 5
kg mà mong đợi PIECES → settlement sai.

Cần signal riêng cho manual_flat (không dùng `is_stale` vì semantic
khác — không re-derive được, chỉ "có drift cần staff giải quyết").
Options:
- Cột mới `has_uom_drift boolean` riêng cho source artifacts.
- Trigger D7 (materials_uom) extend sang manual_flat strategy với
  dim mới `manual_flat_uom_drift`.
- UI badge khác badge "lỗi thời" — màu khác, action "Re-upload BOM"
  thay vì "Refresh".
- API expose `has_uom_drift` cho consumer (BCQT/CO) tự decide
  reject hay convert.

Effort: ~1d (extend trigger + badge + API).

**F. Refresh = mint new artifact + supersede old, không mutate**

Hiện tại refresh:
- Re-derive shape → call `create_artifact` (idempotent qua hash).
- Same hash → return existing artifact_id, clear `is_stale` trên
  artifact GỐC.
- Different hash → create new artifact, **OLD artifact stays alive,
  is_stale cleared trên cả 2**.

Mâu thuẫn với BOM immutable principle: stale artifact = "data đã
sai do dependency thay đổi", clearing flag mà không tombstone =
"giả vờ data vẫn đúng".

Đúng phải là: stale artifact giữ stale flag (hoặc thay bằng
`superseded_by_artifact_id`); new artifact mint với fresh data;
old tombstoned với `tombstone_reason='superseded_by_refresh:<new_id>'`.
Lineage chain stays cho audit (downstream BCQT/CO biết "đây là
phiên bản đã thay thế").

Phụ thuộc Phase 2 vì hiện tại same-hash dedup là majority case.
Sau Phase 2 (refresh thực sự convert), different-hash sẽ phổ biến.

Effort: ~1-2d (refresh logic rewrite + tombstone trigger update +
lineage UI).

**G. Transparency tại ingest + refresh — staff confirm action**

User reinforce: cả 2 flow phải show UI "system sẽ convert những
gì + dùng factor nào + nguồn factor". Staff actions:
- Confirm as-shown.
- Edit factor inline (per-row, persist vào `material_uom_factors`).
- Edit conversion table (admin route).
- Skip convert (giữ raw, mark drift flag).

Đã capture trong scope A của Phase 2 nhưng cần emphasize: **không
auto-apply silent**. Staff phải approve mỗi conversion event.
Tránh case "system converted PIECES → KG sai factor, staff không
biết, settlement Mẫu 15a sai số".

Effort: bao gồm trong scope A (3-4d ingest UI). Refresh-time
transparency: ~1-2d UI extension.

---

## Johnson programmatic bulk re-ingest plan

**Captured 2026-05-11**. Memory `project_reingest_pending.md` ghi
"Wipe + ingest fresh queued — pre-MVP reset" cho Growatt + Johnson.
User request lên kế hoạch concrete cho Johnson (programmatic, không
click UI hàng trăm sản phẩm).

**Mục tiêu:** sau khi Phase 2 UoM conversion + Phase 3 follow-ups
ship, wipe Johnson hoàn toàn rồi re-ingest từ source XLSX qua
script tự động. Lý do wipe: 246 TP × 3 shape × tích lũy stale flag
+ legacy edits → cleaner restart.

**Scope script `scripts/bulk_reingest_johnson.py`:**

1. **Wipe phase** (transactional, dry-run by default):
   - Identify all `bom_artifacts` + `bom_edges` + `bom_artifact_rows`
     + `bom_audit_events` + `bom_presets` for `client_id='johnson-vn'`.
   - Optional: keep `materials` + `code_mappings` + `client_parser_rules`
     (HQ-data tier, manually curated).
   - Print counts before delete (`--commit` to actually run).
   - Tombstone-delete vs hard-delete: hard-delete nếu pre-MVP, tombstone
     nếu đã có customer expecting history.

2. **Ingest phase** (idempotent, retry-safe):
   - Walk source directory (e.g. `~/data/johnson/bom_xlsx/`).
   - Per file: detect adapter (likely `multi_sheet_per_root` cho
     Johnson 246 TP), parse, ingest qua programmatic call (bypass
     upload UI, dùng store directly hoặc internal API endpoint).
   - Run post_ingest_hooks (derive_btp_shallows) ngay sau mỗi raw
     ingest.
   - Materialize shallow + full_flat per product (qua flatten engine
     post-Phase 2 — KHÔNG dùng raw SQL bypass).
   - Apply UoM conversion với confirmed factors từ
     `material_uom_factors` table (đã setup pre-bulk).
   - Log mỗi product: ingested artifact_id, factors used, drift
     warnings, conversion events.

3. **Verification phase**:
   - Compare `n_artifacts` per product trước/sau (expect 3 per phiên
     bản: raw + shallow + full_flat).
   - Compare lineage_root_id distinct count.
   - Run smoke queries (e.g. random product → expect bom_artifact_rows
     non-empty với UoM = catalog UoM).
   - Generate diff report: pre-wipe vs post-ingest qty totals
     (should match within UoM-conversion tolerance).

**Pre-requisites:**
- Phase 2 UoM conversion engine đã ship (script call flatten engine).
- `material_uom_factors` table populated với factor cho cross-family
  cases (cần data từ Johnson supplier sheet).
- Source XLSX inventory complete (xác định bao nhiêu file, structure).
- Backup hiện tại trước khi wipe (pg_dump + bom_edges export).

**Cross-impact:**
- BCQT projects pointing to Johnson — check no in-flight settlement
  references soon-to-be-wiped artifact_ids.
- CO certificates referencing Johnson BOMs — same.

**Effort estimate:**
- Script: 2-3d (wipe + ingest + verify).
- Source XLSX inventory + factor data prep: 1-2d (manual).
- Pre-wipe coordination với BCQT/CO consumers: 0.5d.
- Run + verify: 0.5d (1 dry-run + 1 commit).
- **Total: ~1 week** (heavily dependent on Phase 2 done first).

**Pattern reusable:** sau Johnson, apply same script template cho
Growatt + future clients. Generalize qua `--client` argument.

---

## v_material_roles paren-aware (replace material_observations workaround)

**Captured 2026-05-09** (Mã chờ duyệt v3 review). Issue surfaced when
Growatt's NB material `001.0001100` showed `observed_count=0` on detail
page despite 68 BCCT references via paren-extract.

**Root cause**: `hub.v_material_roles` view JOINs by
`bcct_rows.customs_code` only. NB codes that live inside `goods_name`
parens (Growatt-shape) are invisible to the view. Affected fields:
`has_imports`, `has_exports`, `observed_count`, `observed_first_at`,
`observed_last_at`, `observed_directions`, `is_multi_role`,
`declared_observed_conflict`.

**Current workaround** (ships now, MUST be replaced):
- `app/stores/material_observations.py::compute_observations` —
  per-client (rules-driven, generic), recomputes signals from BCCT at
  request time using parser rules paren-extract.
- Wired into `/catalog/<code>/detail` only. **Not** wired into list
  page (`/catalog`), so the table still shows 0 for affected rows.
- 5 tests (`tests/test_material_observations.py`) cover the helper.
- Per-row Python work — fine for 1 detail page, NOT scalable to list
  view with hundreds of rows.

**Proper fix — 3 options:**

1. **Rebuild view as materialized view with re2-aware resolution.**
   Refresh on BCCT confirm + on parser_rules edit. Pros: fast reads,
   matches existing API. Cons: needs Postgres plpython3u extension OR
   external Python refresher script + materialized view.

2. **Generated/cached column on `bcct_rows`.** Add
   `bcct_rows.internal_code` (was dropped in mig 038), populated by a
   trigger on insert/update that runs the parser rules. View JOINs
   `b.customs_code = m.material_code OR b.internal_code = m.material_code`.
   Pros: SQL-only, no plpython. Cons: reintroduces dropped column;
   trigger must fire whenever rules change (re-derive existing rows).

3. **Replace view entirely with Python-computed materialization.**
   Cron job + a real `hub.material_observations` table refreshed on
   every BCCT/BOM change (post-ingest hook). Pros: fully decouple from
   SQL constraints. Cons: another batch job to maintain.

**Recommendation**: option 2 (generated column). Most surgical, no new
infrastructure, and aligns with the "data graph is truth" principle —
internal_code becomes part of the row's identity once parser rules
stabilize per client.

**Removal trigger** for the workaround:
- View returns correct signals on `001.0001100` directly (no Python
  override needed).
- `material_observations.py` deleted; route handler skips supplement.
- List page `/catalog` "Quan sát BCCT" column shows correct counts
  for paren-extract NB materials.

**Effort**: 1-1.5 days for option 2 (mig + trigger + view rebuild +
cross-cut tests + delete workaround). Reapply trigger on every
existing BCCT row at mig time (one-time backfill).

---

## UoM standardization table (equivalents + conversions) — SHIPPED 2026-05-10

**Captured 2026-05-09** (Mã chờ duyệt v3 review). User: *"Xây dựng bảng tiêu
chuẩn để quy đổi đơn vị tính, có lựa chọn thêm vào từ agency."*

**Shipped 2026-05-10** via mig 051 + `app/stores/uom_standards.py`:
- Reused existing `hub.uom_canonical (uom_code, family, base_factor)` +
  `hub.uom_aliases (alias_norm, uom_code)` (mig 021).
- Mig 051 extends with 10 new canonicals (roll/pair/box/sheet/bottle/bag/
  cay/thanh/vien/thung) + ~50 aliases covering real BCCT data (PIECES,
  SETS, METRES, KILO-GRAMMES, ROLL, PAIR, METRIC-TONS, etc).
- `resolve_canonical(alias)` / `dimension_of(uom)` / `convert(value, from, to)`
  / `are_equivalent(a, b)` helpers with in-process cache.
- Wired into `_uom_drift` warning: only fires when distinct canonical
  codes (real semantic conflict). Synonyms (PCS/PIECE/ST) no longer
  trigger noise.
- Wired into candidate refresh: most-common UoM picked on canonical
  buckets, not raw alias counts. Real Growatt data: 2432 candidates
  with canonical `pcs` (was scattered across PIECES/PCS/ST aliases).
- 17 helper tests + 2 warning de-noise tests + 2 candidate-refresh
  normalization tests.

**Per-agency override (`client_uom_aliases`)**: NOT shipped — deferred.
Only needed when an agency uses an alias that conflicts with another
client's canonical mapping.

**Admin UI polish — DEFERRED 2026-05-10** (user: "chưa hài lòng lắm,
sẽ quay lại sau"). Current `/admin/uom` view (2 tables + 2 add forms)
ships bare-minimum CRUD. Pending improvements:
- Edit canonical (family / base_factor) inline.
- Delete canonical with FK protection (refuse if aliases still point).
- Conversion factor explorer: input value + from + to → instant result.
- Group aliases under their canonical visually (collapsible per family).
- Per-client `client_uom_aliases` override table + UI.
- Better empty-state when canonical has 0 aliases (encourage adding).
- Tooltip / docs explaining `base_factor` model with example.

---

## Candidate richness — match catalog row fields

**Captured 2026-05-09** (Mã chờ duyệt v2 review). User: *"Mỗi candidate phải có
các trường thông tin gần như 1 row trong catalog. Nếu quá thiếu thông tin thì
cho vào catalog chỉ làm noise."*

Candidate hiện có: code, kind, sources, observed_count, dates, sample_text,
suggested_category, multi_direction, import/export counts, decl_count,
bom_role, co_occurrence_count.

Materials có thêm (currently blank when Accept):
- **HS code** — query BCCT rows for distinct hs_code values. Surface most-common +
  inconsistency warning if multiple.
- **UoM** — query BCCT.unit / bom_edges.uom. Surface most-common.
- **production_source** inference: import-only BCCT → `nk`; BOM parent + no import
  → `sx`; both → `mixed`.
- **Origin** (xuất xứ) — most-common BCCT.origin per code.
- **Customs hs_classified** signal — multiple HS codes for same code = warning.

Render these in feed row (tooltip / extra column) AND prefill into Accept form
so staff Accept doesn't drop a sparse material into catalog.

**Effort**: ~3-4h (refresh logic enrichment + Accept form + UI tooltip).

---

## Catalog edit permission (per-role configurable)

**Captured 2026-05-09**. User: *"cho user quyền edit (configurable trong giao
diện phân quyền)"*.

Today catalog UI has Accept/Promote/Tombstone but no general "edit row" form
for an existing material. Add:

- `/clients/<id>/catalog/<material_code>/edit` — form to edit name, category,
  uom, production_source, supplier_hint, hq_registration_*.
- Permission gate via existing role system. New permission key
  `catalog:edit_material` exposed in role-management UI.
- Audit captures every edit (mig 045 trigger already in place).
- "no DELETE" rule — edits stay versioned in audit table.

**Effort**: ~1 day (form + permission UI + tests + screenshots).

---

## Catalog material detail page — cross-source inconsistency warnings

**Captured 2026-05-09**. User: *"Trong view của mỗi mã vật tư, cần query chéo
các thông tin ở các nơi, cảnh báo bất nhất nếu có. Ví dụ các dòng trong BCCT
dùng mã đó nhưng lại khác mã HScode, etc."*

Existing detail page (`/clients/<id>/catalog/<material_code>/detail`) currently
shows: provenance, observed signals (from v_material_roles), audit history,
recent BCCT refs, recent BOM artifacts.

Add **cross-source inconsistency panel**:

- **HS code drift**: same material_code declared with multiple `hs_code` values
  in BCCT → warn "Mã HQ này đã khai 3 mã HS khác nhau: X (47 lần), Y (3 lần),
  Z (1 lần)".
- **UoM drift**: BCCT.unit vs BOM.uom vs materials.uom mismatch.
- **Origin drift**: BCCT.origin variation across declarations for same code.
- **Direction drift**: code declared as both import + export (multi-role hint).
- **Sourcing drift** (mig 046 sourcing_confirmation_conflict): catalog says
  btp_nm but BCCT shows is_consumed_in_bom + is_in_own_bom_root → inconsistent.
- **Code mappings drift**: 1 NB code mapped to multiple HQ buckets, vice versa.

Each warning has: severity, evidence count, link to drilldown.

**Effort**: ~1 day (detail-page section + 5-6 warning queries + tests).

---

## BOM parser — extract "Object description" column

**Captured 2026-05-09** during Mã chờ duyệt v2 review. Johnson BOM xlsx files
have "Object description" column (item names) but `sap_indented_walk.py` parser
discards it — only structural info (parent/child/qty/uom) survives into
`bom_edges`. Result: BOM-only candidates (3711+ codes for Johnson) show blank
sample_text in catalog candidate feed; staff must fill name manually on Accept.

**Fix:** enhance `sap_indented_walk.py` to capture description column into
`bom_edges.payload->>'description'` (or add `description text` column via mig).
Update `app/stores/catalog_candidates.py::refresh_candidates` to pull
description as `sample_text` for BOM-only candidates.

**Effort**: ~2-3h (parser change + payload migration helper + refresh update +
tests). Then re-ingest Johnson BOM to backfill descriptions for existing rows.

---

## Mã chờ duyệt — passive candidate feed (deferred 2026-05-09)

**Captured 2026-05-09** during catalog multi-source session. User
pivoted from initial `catalog_derive` rule-form design (commits
mig 042/043 + `catalog_derive.py` + `catalog_derive.html` shipped)
to a passive candidate feed:

> "Phần catalog candidate này sẽ theo dõi BOM và BCCT, recommend các
> candidate để user quyết định có cho vào Catalog hay không. Rules đã
> có sẵn trong config của từng khách hàng rồi, đâu cần enter thêm rule
> ở catalog?"

**Architecture:**
- DROP `catalog_derive_configs` table + `app/routes/catalog_derive.py` + template
- NEW `app/routes/catalog_candidates.py` — page `/clients/<id>/catalog/candidates`
- NEW table `hub.catalog_candidate_rejections` (client_id, source, code, rejected_at, rejected_by, reason)
- Source data: 2 streams merged
  - **BCCT stream**: chạy existing `client_parser_rules` (output_field='internal_code')
    over BCCT rows → extract codes → anti-join materials + rejections
  - **BOM stream**: distinct codes từ `bom_edges.parent_code/child_code`
    → anti-join materials + rejections
- **Reject persistence**: separate table per user decision 2026-05-09 (not ghost rows)
- **Suggested category** (per user-confirmed logic):
  - import in BCCT + matching parser rule → `nvl`
  - export in BCCT → `tp`
  - parent_code in BOM (TP root) → `tp`
  - child_code in BOM → `nvl` (default; staff edit if btp)
  - Default fallback → `nvl`
- VN page name: "Mã chờ duyệt"
- UI: feed-style — code + source (BCCT/BOM) + observed_count + sample_text
  + suggested category + [Accept] [Reject] per row. No regex form for staff.

**Phase 2 (after candidate feed ships):**
- Conflict detection page `/clients/<id>/catalog/conflicts` using
  existing `v_material_roles.declared_observed_conflict` boolean +
  the sourcing-conflict logic (mig 046 + Python in catalog.py).
  Surface "catalog says X is NVL but BCCT shows X is exported as TP" cases.

**Effort estimate**: ~1-1.5 days (single mig, single route module,
single template, replaces existing catalog_derive). Includes test
coverage + screenshots.

**State of `catalog_derive_configs` + UI**: shipped in mig 043 +
catalog_derive.html as a wizard form, but user explicitly redesigned
post-shipping. Either drop in mig 047 OR repurpose. Brief should
explicitly cover the migration path (existing rows in
catalog_derive_configs are throwaway test data, no production).

---

## Phase 2 catalog — multi-role roles[] + manual fields (deferred 2026-05-09)

**Captured 2026-05-09**. After mig 042-046 shipped Phase 1 (provenance
+ state + audit + dual-source via observed_roles), Phase 2 is the
remaining schema enrichment:

1. **`materials.roles[] text[]`** — multi-role first-class.
   Memory `project_bom_code_multirole.md` ("a code can be TP+BTP+NVL
   simultaneously"). Currently `category` is single-value;
   `category_override` patches one case but doesn't scale.
   Plan:
   - Add `roles[]` column with check constraint `roles <@
     array['nvl','tp','btp_sx','btp_nm','ccdc']`
   - Backfill `roles = array[category]` for existing rows.
   - Update consumer queries: `m.category = 'X'` → `'X' = ANY(m.roles)`.
   - Drop `category` AFTER all consumers migrate.
   - Drop `category_override` (becomes redundant).
2. **Manual fields**: `production_source` (nk/sx/mixed/unknown),
   `hq_registration_no` text, `hq_registration_date` date,
   `supplier_hint` text, `name_source` enum, `uom` text (separate
   from `client_uom_overrides`).
3. **Cross-cut refactor**: ~30-50 file touches expected. Critic
   round 2 flagged dual-source-of-truth trap if `category` + `roles[]`
   coexist long-term — commit to drop `category` in same release OR
   defer `roles[]` until ready to drop.

**Effort**: ~2-3 days (schema mig + cross-cut refactor + sister-app
note for CO/BCQT).

**Status** of related work shipped: dual-source pattern via
observed_roles[btp_sx + btp_nm] (mig 046) + sourcing-confirmation
conflict (Python in catalog.py route + UI badge in catalog.html).
Multi-role array on materials still pending.

---

## Catalog conflicts page (deferred 2026-05-09)

**Captured 2026-05-09** (originally Phase 3 of catalog multi-source).
Surface mismatches between catalog declarations and observed data
graph:

- `v_material_roles.declared_observed_conflict` already computed
  (boolean per row). Drives "⚠ Xét lại" badge in catalog list.
- Missing: dedicated page listing all conflict rows for staff review.
- Page `/clients/<id>/catalog/conflicts`: table of conflicts +
  details + actions (update declared_kind, override, suppress).
- Sourcing-confirmation conflict (mig 046 logic): catalog list has
  inline badge but no dedicated review queue. Same page can host both.

**Effort**: ~0.5-1 day (read-only view + actions reuse existing endpoints).

---

## Parser-rules infra polish (deferred 2026-05-08)

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
4. **CI workflow: soft-fail LLM `/models` smoke step**. Currently
   `Smoke LLM /models (best effort)` uses `bash -e` which propagates
   curl exit 22 (401 from upstream `codex-lb-demo.sgnai.dev`).
   Fix in `.github/workflows/<workflow>.yml`: add
   `continue-on-error: true` OR rewrite the step to gracefully
   handle non-2xx without exit. Today the workflow shows red on
   GitHub even when actual deploy + tests + API smoke pass.
5. **Memory updates** — pending verification across sessions:
   - `internal_code` + `material_identity` columns gone; live via
     runtime helpers.
     - Hardcoded growatt regex replaced by `hub.client_parser_rules`.
   - BCCT field semantic split: FX (`*_nt`) vs VND domains.
   - Resolver Stage 2 (paren-extract) wins over Stage 1 (customs).
   - Payload jsonb sparse; typed columns are source of truth.

---

## Scripts that lost SQL `material_identity` access (deferred 2026-05-08)

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
queries. Defer until performance pain emerges.

---

## Phase 3 review follow-ups (deferred 2026-05-07)

Captured during /rev of commits `5fb814a..dadbd0f`. Four Minor
findings deferred — low value individually, batch when convenient.

1. **Catalog matching column ≠ classifier matching column.**
   *Superseded 2026-05-09 by "v_material_roles paren-aware" entry
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

---

## Phase 3c follow-ups (deferred 2026-05-07)

Phase 3c shipped the foundational pieces: `derive_btp_shallows.py`
(closes Johnson decomposability gap), `post_ingest_hooks` adapter
contract, multi-role catalog warning. The brief's UI upload v3
items remain open — high effort, lower value than 3a/3b core.

1. **Auto-trigger `derive_btp_shallows` from upload confirm flow.**
   Current state: hook registry + runner exist but nothing in
   `app/routes/bom.py::_confirm_*` invokes them. Add a call after
   raw artifact commit; respect `clients.auto_derive_shallow_from_raw`
   policy. ~1-2h.
2. **`bom_variant_id` form field on upload page.** Today every UI
   upload collapses to `'default'`. Add an optional text input so
   staff can label multi-supplier batches. Auto-derive default from
   filename or upload date if blank. ~2h.
3. **Auto-materialize raw → shallow + full_flat post-confirm.** Wire
   `materialize_shallow_and_full_flat.py` as a second post-ingest
   hook for raw_graph artifacts. Gate by `auto_derive_shallow_from_raw`
   (already exists). ~2-3h.
4. **Auto-bootstrap BTP roster.** Re-run `bootstrap_btp_roster.py`
   logic on parent_codes after raw ingest so newly-introduced
   intermediate codes land as `btp_sx`. ~1h.
5. **Shape badge in upload preview.** Show `raw_graph` / `shallow` /
   `full_flat` banner using `bom_shape()` helper. ~30min.
6. **Multi-role warning at upload.** When confirming an upload that
   would create btp_sx rows, check if any code already appears in
   bcct_rows direction='export' — surface a confirmation dialog.
   Catalog-page badge already lives (`is_multi_role`). ~1h.
7. **Playwright E2E for upload → mapping → parse → preview → confirm.**
   ~2-3h.

Drop these into a feature brief when the user wants to schedule
post-MVP polish work.

---

## Drop BOM vocab v1 aliases

**Captured 2026-05-07** as part of mig-031 rename pass (see
`.ai/features/2026-05-07-bom-vocab-rename/brief.md`). The rename
ships with a one-release grace period of 308 redirects from old URLs
to new URLs:

- `/clients/{c}/bom/version/{id}` → 308 → `/clients/{c}/bom/artifact/{id}`
- `/clients/{c}/bom/{p}/versions` → 308 → `/clients/{c}/bom/{p}/artifacts`
- `/v1/hub/products/{p}/bom/versions` → 308 → `/v1/hub/products/{p}/bom/artifacts`

Aliases live as `_alias_*` route handlers in `app/routes/bom.py` +
`app/routes/api.py`. Tests guarding the 308 behavior are in
`tests/test_bom_vocab_rename.py` under "URL alias — 308 redirect".

**Removal trigger:**
1. CO and BCQT confirm migration to new URLs (CO has 28 refs to old
   names per sister-app note; BCQT has 0 refs).
2. Server logs show zero alias hits over a 24h window.
3. Any external bookmarks confirmed migrated.

**Removal procedure** (small commit):
1. Delete `_alias_*` route handlers in routes/bom.py + routes/api.py.
2. Delete URL alias tests in tests/test_bom_vocab_rename.py
   (keep schema + ID-prefix tests forever).
3. Update API_CONTRACT.md to remove alias section.

---

## UI BOM upload — wire up v3 concepts

**Captured 2026-05-05** after session shipped v3 schema (raw_graph /
shallow / full_flat shapes), supplier-batch ingest scripts, BTP
roster, and provenance UI on BOM list/detail pages. The upload route
itself (`app/routes/bom.py`) was not updated; it still uses the
unified-mapping-flow from commit `b278ff5` and treats every upload
as `bom_variant_id='default'` with no post-upload hooks.

**Gaps to close:**

1. **`bom_variant_id` field in upload form** — staff should pick a
   batch label (e.g. `agency_2026-05-05` or freetext) when uploading
   multiple supplier batches per product. Auto-derive default from
   filename or upload date if blank. Without this, multi-batch
   uploads via UI collide on `(product_code, default)` and trigger
   version-bump idempotency dedup.
2. **Auto-materialize post-upload** — when `technical_raw` confirms,
   trigger `materialize_shallow_and_full_flat` for the new
   `bom_artifacts` row inline (or async). Without this, shallow +
   full_flat versions only exist after a manual script run, which
   leaves the freshly-uploaded raw_graph orphan from BCQT/CO consumer
   queries.
3. **Auto-bootstrap BTP roster** — same trigger should re-run BTP
   detection (rule: parent_code in bom_edges + not a tp_root).
   Catalog `btp_sx` entries for newly-introduced intermediate codes
   land without a separate command.
4. **Shape badge in preview** — preview page currently shows flat
   rows. Add a header banner showing "This upload will create a
   `raw_graph` BOM" / "`shallow`" / "`full_flat`" so staff confirm
   with intent. Use the `bom_shape()` helper.
5. **Multi-role warning** — if any code in the upload also appears
   in `bcct_rows.direction='export'` for this client AND the upload
   would categorize the code as `btp_sx`, surface a warning: "Code
   PV01.0104300 has been exported in BCCT — adding it as BTP here
   creates a multi-role situation. Confirm intent." Reference
   `project_bom_code_multirole.md` memory for context.
6. **Per-client policy gate** — `clients.auto_derive_shallow_from_raw`
   (`disabled` / `draft_only` / `publish`) should gate auto-materialize
   step. UI upload should respect the value: in `draft_only`, derived
   shallow/full_flat insert as `status='draft'` not `published`.
7. **Tests + docs** — Playwright E2E that drives upload → mapping →
   parse → preview → confirm and asserts shape + materialize side
   effects. Unit tests for the new auto-trigger functions.

**Why deferred to Phase 3 / a dedicated session:**

The UI integration naturally couples with Phase 3 resolver +
profiles work — both need shape-aware UX, and shipping them
together avoids two rounds of UI churn. Pre-MVP scope is covered by
direct-ingest scripts (`scripts/ingest_technical_raw_batch.py`,
`scripts/ingest_curated_xlsx_direct.py`) + manual UI for ad-hoc
single uploads, which is acceptable until first real customer.

Estimated effort: 4-6h for items 1-5, +2-3h for tests + docs (item 7).

---

## Aggregate-data git-history

**Captured 2026-05-05** as a hard product principle from user.

**Principle (already enforced for BOMs, generalize to other aggregates):**

- Never physically `DELETE` rows from any aggregate-data table (BOMs,
  materials, code_mappings, client_config, parser_mappings, etc.).
- Edits = INSERT a new version with lineage back to the previous one.
- "Removal" is via tombstone / deactivation flag on the row, not row
  deletion.
- All aggregate data must support **git-like history**: who added what,
  who removed what, when, with revert / undo capability.

**Current state (HEAD as of 2026-05-05):**

| Table | History tracking | Gap |
|---|---|---|
| `bom_artifacts` + children | ✅ tombstone + parent_artifact_id lineage (mig 006/029) | Uses migration 027 cleanup pattern. Already conformant. |
| `bcct_rows` | ✅ `bcct_row_history` audit table + AFTER UPDATE/DELETE trigger (mig 013) | OK, but no UI for revert. |
| `materials` | ⚠️ `provenance` jsonb merge-on-conflict only | No history table. UPDATE overwrites name/category/unit/etc. |
| `code_mappings` | ❌ Plain table, UPDATE in place. | No history. |
| `client_config`, `parser_mappings`, `bom_flatten_decisions`, `client_uom_overrides`, `client_type_presets` | ❌ Plain tables. | No history. |
| `clients`, `users` | ❌ Plain tables. | No history (probably OK for users, debatable for clients). |

**Work units (each its own PR):**

1. **`materials_history` audit table + trigger** mirroring the
   `bcct_row_history` pattern. Capture full row before any UPDATE
   or DELETE, with `changed_at`, `changed_by` (read from
   `app.user_id` GUC), `change_kind ∈ {insert, update, delete}`.
2. **`code_mappings_history`** same pattern.
3. **`client_config_history`** + **`parser_mappings_history`** same.
4. **`/v1/hub/{table}/{key}/history` endpoints** — paginated audit
   timeline per entity.
5. **`/v1/hub/{table}/{key}/revert?to=<changed_at>`** — revert one
   row to a prior state. Implemented as INSERT-from-history (still
   append-only); audit captures it as a new change with
   `change_kind='revert'`.
6. **UI: history page per entity.** Reuse `bcct_row_history` page
   pattern. Diff view showing what changed.
7. **Document the "no DELETE" rule in `AGENTS.md` + standards repo.**
   Add a CI lint that scans for `DELETE FROM hub.<aggregate-table>`
   and fails on match unless explicitly tagged
   `-- ALLOW-DELETE: <reason>`.

**Why this matters:**

- Customs audit (TT 39/2018) requires 5-10 year retention of source
  data underlying settlement / origin certificates.
- Disputes between agency and customs auditor often hinge on "which
  version of the catalog/BOM/mapping was active when this transaction
  was filed?" — without history, the answer is "current state"
  which may not be the truth-of-record.
- Staff confidence: undo / revert lowers the cost of accidental
  destructive edits, which lowers the activation energy for staff
  to actually fix bad data.

**Out of scope for this backlog item:**

- BOM versioning is already done — don't redo it. The new history
  tables are for non-BOM aggregates.
- Operational tables (sessions, llm_usage, notifications,
  upload_pending) don't need this — they're transient.

---

## Sprint D — parser/data architectural follow-ups (post-Sprints A/B/C)

**Captured 2026-05-03 PM** after Sprints A/B/C closed the immediate
correctness gaps. Each item below is its own PR (per plan-review
critic: "uncoupled changes — don't bundle"). No fixed order; ship in
parallel as bandwidth allows.

- **D1: `hub.declaration_types` lookup table.** Replace the hardcoded
  `IMPORT_TYPES` / `EXPORT_TYPES` Python sets in `app/parsers/bcct.py`
  with a DB-seeded table sourced from Decision 1357/QĐ-TCHQ. Direction
  becomes a SQL JOIN; future schedule revisions are a seed-INSERT
  migration not a code release.

- **D2: `transaction_key` GENERATED ALWAYS AS column.** Make
  `transaction_key = '{declaration_no}-{line_no}'` a stored generated
  column on `hub.bcct_rows` so the invariant cannot drift. Migration
  touches every BCCT insert path; ship as its own PR.

- **D3: `normalized_hash` Decimal end-to-end + dual-version migration.**
  `app/stores/bom.py:normalized_hash` currently does
  `round(float(...), 9)` — float arithmetic drift undermines
  idempotency. Switching to Decimal changes every existing version's
  hash. Need a phase-in plan: compute v2 hash on writes, store both
  v1 + v2 during transition, dual-check on insert until backfill.

- **D4: Idempotency canonical-projection re-design.** Critic flagged
  that re-uploading the same Excel after fixing an unrelated catalog
  row currently silently dedup's because `normalized_hash` doesn't
  cover the upload-context dimension. Discovery doc first, then
  decide: log audit event on dedup-hit, OR widen the canonical
  projection, OR both.

- **D5: SAP indented-walk level-skip handling.** Reject (or pad with
  sentinel parents) BOM workbooks where indent levels skip
  non-contiguously (e.g. L2 → L4 missing L3). Need a real Johnson SAP
  sample exhibiting the case to reproduce — fixture
  `johnson_sap_english_headers.xlsx` may already cover it; verify
  before writing speculative code.

- **D6: BOM idempotency unique index audit.** Same
  uq_bom_idempotent_v2 design — verify the (`actor`, `intent`)
  column tuple is the right granularity vs upload identity.

- **D7: Fixture-pinned regression test for BOM-vs-CO compare.**
  Replace the gitignored `data/screenshots/_compare_report.md` with
  `tests/regression/test_real_bom_compare.py` env-gated, pinning
  per-file leaf-set match thresholds against checked-in fixture
  corpus.

- **D8: Cross-table `hub.integrity_findings` materialized view.**
  Surface every catalog-vs-BOM-vs-BCCT inconsistency in one place
  (orphan BTP_SX, UOM mismatches, ghost codes, etc.). Defer until 3+
  consumers want the same data — currently the per-page badges from
  Sprint B cover MVP need.

- **D9: `bcct_rows.artifact_id` point-of-use binding.** Already
  designed in `.ai/features/2026-04-30-data-hub-mvp.md` (BCQT-side).
  Implement when BCQT migration sprint lands.

---

## CO + BCQT — adopt service-account JWTs

**Captured 2026-05-02 PM.** Ship-blocking dependency for "API auth strict
promotion" below. No hard deadline — coexistence works fine.

Service-account JWTs are live in Data Hub (migration 020 + CLI). Sister
apps still call with permissive bearer / user JWT. To adopt:

1. **Mint tokens** (Data Hub admin):
   ```bash
   uv run python scripts/mint_service_token.py create \
     --name co --scopes hub:read,bom:propose \
     --client-ids growatt-vn,dke-vietnam-d0e3,johnson-vn,do-thanh-vietnam-2614 \
     --created-by <admin-email>

   uv run python scripts/mint_service_token.py create \
     --name bcqt --scopes hub:read \
     --created-by <admin-email>
   ```
2. **CO repo** (`barry-CO-main`): inject `DATA_HUB_SERVICE_TOKEN` env
   into `app/data_hub_client.py` Bearer header on every call. If CO
   verifies tokens locally, branch on `claims["typ"] == "service"` —
   service tokens have no email/role/name; `sub` is `svc:co`.
3. **BCQT repo**: same pattern, `hub:read` scope only.

Full instructions: `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`.
Design rationale: `.ai/features/2026-05-02-service-account-jwts.md`.

**Pull this out of backlog when:** ready to coordinate the sister-repo
PRs, or when about to flip `api_auth_strict=true` (then it becomes
ship-blocking).

---

## API auth — flip dev-permissive reads to strict by default

**Captured 2026-05-02.** **Unblocked 2026-05-02 PM** — service-account
JWTs shipped (migration 020). Now waiting on sister-app cutover (item
above).

Today the read API on `/v1/hub/*` accepts non-empty legacy bearer strings
when `api_auth_strict=false` (default). Writes (BOM proposal POST) always
require a valid Data Hub JWT regardless of the flag. The trade-off was
chosen deliberately: prioritize dev/integration ergonomics today,
prioritize corruption prevention on writes.

**Promote when:**
- CO and BCQT have switched to service-account JWTs (per
  `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`).
- We have a staging environment where strict mode can be soak-tested
  before flipping prod.

**Steps when promoting:**
1. Default `api_auth_strict=true` in fresh installs; add a one-time
   migration to flip existing installs after CO/BCQT confirm readiness.
2. Remove the legacy bearer fallback path in `_require_token`; keep only
   the JWT validation branch.
3. Update `docs/API_CONTRACT.md` to drop the dev-permissive mode section.
4. Update CO/BCQT consumer code to send real JWT on every read call.

---

## Manual mapping UI when LLM disabled

When LLM is unavailable AND a file fails rigid parse, the upload errors
with no recovery besides edit-in-DB. Add a "Manual mapping" link on the
parser-mapping preview when LLM is unavailable, surfacing the same
header→logical-field grid the LLM-confirmed flow uses. Reuses
`parser_mappings` cache once confirmed.

---

## BOM/BQD/Catalog parse-error UX

**Partial.** Phase 2 universal preview-confirm pattern surfaces parsed
rows nicely when parsing succeeds. But when the parser rejects the file
outright (no LLM available, or LLM also fails), `app/routes/bom.py:145`
still raises `HTTPException(400, ...)` which the browser renders as raw
FastAPI JSON `{"detail": "..."}`.

Compare BCCT's `parse-mapping` error path which renders a proper
template with recovery options.

**Fix:** catch the final parse-error path and render an error template
or redirect with a `?error=...` toast (matching the post-upload toast
pattern from `c77da85`).

---

## Modular BOM ingest adapters (per supplier shape)

**Captured 2026-05-06.** Two distinct supplier-file shapes have
shipped so far:

- **Growatt-shape** — agency provides one file per code (TP and BTP
  separately). Ingest yields per-code `raw_graph` directly. Result:
  144/147 BTP shallow leaves are decomposable from their own
  `bom_artifacts` rows.
- **Johnson-shape** — agency provides one deep-tree file per TP.
  Ingest yields TP-level `raw_graph` only; intermediate BTPs have
  edges (in `hub.bom_edges`) but no `bom_artifacts` row keyed to them.
  Result: 0/342 BTP shallow leaves decomposable until a derive step
  runs.

Both shapes converge on the same in-DB model (raw_graph / shallow /
full_flat per `project_bom_3_shapes.md`), so the divergence lives
entirely in the **parse + post-ingest** path. Treat each supplier
shape as a pluggable adapter / add-on.

**Goals:**

1. **Adapter interface** — formalize the contract: `detect(file) →
   match_score`, `parse(file) → list[bom_version_payload]`,
   `post_ingest_hooks → [...]`. New supplier shapes drop in as a
   registered adapter under `app/parsers/bom/adapters/` with no
   core-code changes.
2. **`derive_btp_shallows.py`** — post-ingest hook for Johnson-shape
   adapter (and any future deep-tree shape). For each intermediate
   `parent_code` in `bom_edges` that is classified `btp_sx`,
   materialize a `bom_artifacts` row keyed to that code with
   `flatten_status='flattened'`,
   `flatten_strategy='purchased_btp_as_leaf'`, walking from that node
   down to first BTP/NVL leaves. After this runs, Johnson reaches
   Growatt-level decomposability and resolver Phase 3 can compose
   shallow → full_flat without knowing supplier shape.
3. **Canonical adapter registry** — extract current ingest scripts
   (`ingest_technical_raw_batch.py`, `ingest_curated_xlsx_direct.py`)
   into adapter classes: `growatt.py`, `johnson.py`, plus a
   `default.py` fallback. Selection by `client_id` + filename
   heuristics; UI override per upload.
4. **Phase 3 readiness** — resolver should rely only on the unified
   in-DB model, never on adapter-specific quirks. Divergence ends at
   parse-time, not propagated downstream.

**Why now:** v3 model has settled and we have two real shapes to
abstract from — one is enough to risk over-fitting, three risks
under-fitting, two is the sweet spot. Future shapes to expect: SAP
multi-sheet exports, ERP-CSV row-keyed BOMs, WeChat-pasted CSVs,
agency emails with mixed structure.

**Note (2026-05-08):** the **BCCT-side configurable parsing rules**
(originally captured here as item 5) are now in-flight as
`.ai/features/2026-05-08-configurable-bcct-parsing/brief.md`. That
brief introduces `hub.client_parser_rules` table + UI + test panel.
The BOM-side adapter work (items 1-4 above) can reuse the same
table shape with `output_field='bom_*'` once BCCT side ships,
unifying both into a single per-client rule infra.

**Estimate (BOM-side only):** ~10-15h to formalize the registry +
extract scripts + write `derive_btp_shallows.py` + tests. Bundle
with Phase 3 resolver work since they share the "uniform in-DB
model" assumption.

---

## /rev cross-cuts (still open)

- **CSRF protection** on POST endpoints (pre-existing project gap).
- **`set_config('app.user_id', ..., false)`** — switch to `true`
  (LOCAL) if connection pooling lands. Today every `connect(user_id=...)`
  call gets a fresh connection, so SESSION-scoped GUC is fine.
- **Migration numbering gap** (010 → 012, no 011) — cosmetic; renaming
  applied migrations would diverge `schema_migrations` rows across
  environments.

---

## Notes

The previously-tracked items below have all shipped (verified in HEAD as
of 2026-05-02 PM):

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
