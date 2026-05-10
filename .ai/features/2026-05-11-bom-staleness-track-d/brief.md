# Feature: Track D — BOM dependency staleness (MVP, option 1)

Captured 2026-05-11 sau discovery sprint. Track D từ session
2026-05-10 PM (xem `.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/
brief.md` Track D). Defer reason: scope >> A+B+C combined; cần audit
dependency edges trước khi pick design option.

Discovery output: option 1 (staleness flag + manual refresh)
confirmed cho MVP, scoped xuống "easy 4 dimensions" với refined
design. 4 dimensions còn lại defer Phase 2 với rationale rõ ràng.

## Scope

### In (MVP — ship 1 commit set)

**Schema (mig 053):**
- `hub.bom_artifacts.is_stale BOOLEAN NOT NULL DEFAULT false`
- `hub.bom_artifacts.stale_reasons JSONB NOT NULL DEFAULT '[]'::jsonb`
  — list of `{dim, source_table, source_pk, observed_at}`
- `hub.bom_artifacts.stale_first_at TIMESTAMPTZ` (NULL khi never-stale)
- `hub.bom_artifacts.stale_resolved_at TIMESTAMPTZ` (NULL khi current)
- Index `(client_id, is_stale) WHERE is_stale = true` (partial,
  list-page filter cheap).

**Triggers (4 dimensions, Phase 1):**

1. **D1 catalog category change** — AFTER UPDATE on
   `hub.materials(category)` → mark all `bom_artifacts` referencing
   `materials.material_code` via `bom_artifact_rows.material_code`
   as stale với `dim='catalog_category'`.
2. **D7 materials.uom change** — AFTER UPDATE on
   `hub.materials(uom)` → cùng pattern, `dim='materials_uom'`.
3. **D8 btp_sourcing flip** — AFTER UPDATE on
   `hub.materials(btp_sourcing)` → cùng pattern,
   `dim='btp_sourcing'`.
4. **D2 BTP BOM xuất hiện sau** — AFTER INSERT on
   `hub.bom_artifacts` WHERE `source_bom_kind = 'technical_raw'`
   AND product_code matches a `material_code` của `category =
   'btp_sx'` → tìm parent artifacts có `material_code = NEW.product_code`
   trong `bom_artifact_rows`, mark stale với `dim='btp_bom_added'`.

Triggers SCOPE bằng `client_id` để tránh cross-tenant ripple.
Chỉ mark **derived** artifacts stale (`flatten_strategy IN
('technical_exploded', 'purchased_btp_as_leaf', 'self_produced_btp_exploded',
'mixed_confirmed')` — NOT `manual_flat_as_provided` hay `no_strategy`).

**Refresh flow:**
- Per-artifact route: `POST /clients/{client_id}/bom/artifact/{id}/refresh`
  → invoke materializer cho artifact's product (single product, 3 shapes
  ~30s). Sync; staff click button → spinner → reload page.
- Per-product (group) route: `POST /clients/{client_id}/bom/{product_code}/refresh`
  → re-materialize entire lineage. Sync.
- Bulk route: `POST /clients/{client_id}/bom/refresh-all-stale` →
  enqueue + redirect with toast (background — could be 100s of artifacts).
  *Phase 2 nếu chưa có job runner; MVP có thể loop sync với progress page.*

**Wire post_ingest_hooks** (existing scaffold,
`app/parsers/bom_adapters/__init__.py:206-223` — already has Protocol,
HOOKS map, runner; just not invoked):
- Call `run_post_ingest_hooks(adapter_name, artifact_id, client_id)`
  từ `app/routes/bom.py:486` (sau `create_artifact`) trong confirm flow.
- Auto re-materialize derived shapes ngay khi raw_graph artifact mới
  ingest → giảm staleness window cho dim 2.

**UI surface:**
- `bom.html` (list page) — column "Trạng thái phiên bản latest" thêm
  badge "⚠ stale (N)" khi any artifact của phiên bản latest stale.
- `bom_artifacts.html` — row level "⚠ stale" badge + tooltip hover
  show `stale_reasons[].dim` translated. Refresh button per row.
- `bom_artifact_detail.html` — Provenance section thêm "Trạng thái:
  stale (lý do: ...)" + "Refresh now" button.
- i18n keys: `bom.stale.badge`, `bom.stale.refresh`, `bom.stale.dim.*`
  (4 dim keys).

**API surface (BCQT/CO consumer):**
- `GET /api/v1/bom/artifact/{id}` response thêm `is_stale: bool`,
  `stale_reasons: list[dict]`. Consumers tự decide; Data Hub
  KHÔNG block stale reads.

**Tests:**
- Mig forward + backward (3 tests).
- Trigger D1/D7/D8 unit (3 tests — UPDATE materials, assert is_stale).
- Trigger D2 unit (1 test — INSERT child raw_graph, assert parent stale).
- Trigger client_id scoping (1 test — cross-tenant isolation).
- Refresh route integration (3 tests — per-artifact, per-product,
  stale_resolved_at populated).
- post_ingest_hooks wiring (1 test — confirm flow invokes hook +
  derived shapes minted).
- API response `is_stale` field (1 test).
- ~13 tests total.

### Out — Phase 2 conversion engine (separate BACKLOG entry)

**Captured 2026-05-11 sau real-data test:** Refresh button hiện tại
**KHÔNG convert UoM**. Re-derive dùng raw SQL bypass flatten engine
→ output rows luôn cùng UoM với raw upload, không respect catalog
UoM. Stale flag đúng semantic "cảnh báo", nhưng action "Refresh"
chỉ clear flag, không transform data.

User feedback (2026-05-11): conversion phải xảy ra **TỪ INGEST**,
không chỉ refresh. Staff phải thấy rõ rows nào convert, factor
nào dùng, có quyền edit factor inline hoặc edit conversion table.
Cross-family case (PIECES → KG) có business demand thật → cần
`material_uom_factors` table per-material.

→ Full scope captured trong BACKLOG.md entry "BOM UoM conversion
engine (ingest-time + refresh-time)". Estimate 1.5-2 tuần + 1-2d
discovery. Phase 1 ship được độc lập vì semantic flag đúng; Phase 2
là partner work để conversion thực sự work.

### Out (other Phase 2 — explicit defer)

- **D3 catalog accept (mã chờ duyệt)** — promote_material trigger
  scope cần thinking thêm: accept thay đổi `status` từ `pending` →
  `active`, ảnh hưởng candidate refresh + observation signals NHƯNG
  không trực tiếp ảnh hưởng flatten output. Defer until staff
  pattern observed.
- **D4 code_mappings update** — indirect (BCCT ingest layer). Stale
  affects observation signals on catalog detail page, NOT flatten
  output. Defer.
- **D5 parser_rules edit** — indirect (BCCT re-derive). Cascading
  re-ingest cần job runner. Defer until parser rule churn observed.
- **D6 UoM aliases expansion** — global table, ripple cross-client.
  Cần broader design (mark-all-with-this-uom or scope-by-client?).
  Defer.
- **Auto-refresh job queue** (option 2 elements) — không có job
  runner trong infra. Manual refresh đủ MVP.
- **Event-sourced ledger** (option 4) — defer hoàn toàn; option 1
  flag-based sufficient cho pre-customer demo.
- **Staleness expiry** (auto-clear after N days) — không cần.
- **Per-row staleness** (chỉ artifact-level granularity).
- **Bulk refresh background job** — MVP có thể sync-loop với progress
  page nếu list nhỏ; promote thành async khi >50 artifacts.

## Decisions

1. **Option 1 confirmed.** Audit không tìm ra blocker. Existing
   `material_audit_events` (mig 045) trigger pattern proves Postgres
   triggers comfortable trên `materials` updates. Existing
   `bom_artifacts` idempotency via `normalized_hash` makes re-materialize
   safe (no dup, same artifact_id returned).

2. **Phase 1 = 4 dimensions only (D1, D2, D7, D8).** Discovery split:
   - **Easy** (single table `hub.materials`, single column): D1, D7,
     D8.
   - **Medium** (BOM ingest path, scope-able): D2.
   - **Hard / indirect** (cross-table cascading, ripple cross-client):
     D3, D4, D5, D6.
   Phase 1 ships easy + medium. Hard defer with explicit rationale
   per dimension trong "Out" section.

3. **Mark only derived artifacts stale.** Source raw_graph +
   manual_flat are immutable per "BOM immutable principle"
   (`project_bom_immutable_principle.md`). Marking source stale
   confuses semantic — source isn't stale, its derived projection is.
   Trigger filter: `flatten_strategy IN (4 derived strategies)`.

4. **`stale_reasons` is JSONB list, not single column.** Multiple
   dim hits accumulate (catalog UoM change + btp_sourcing flip cùng
   1 artifact). Each entry = `{dim, source_table, source_pk,
   observed_at}` — full audit. Refresh resolves ALL reasons; clears
   list + sets `stale_resolved_at`.

5. **Wire post_ingest_hooks ngay trong feature này.** Scaffold đã
   tồn tại (audit confirmed `app/parsers/bom_adapters/__init__.py:
   47-223`), defer wiring lâu hơn = ăn lại context cost. Wire +
   manual refresh button cho phép verify hook fires correctly.

6. **API exposes is_stale, không block.** Data Hub là source-of-truth
   cho HQ-data; consumer (BCQT/CO) tự decide tolerance. Block-on-stale
   sẽ break BCQT khi staff edit catalog at runtime — unacceptable
   coupling.

7. **`is_stale` violate `feedback_no_derived_in_source.md`?** Đúng
   trên paper — `is_stale` derive được từ `stale_reasons` non-empty.
   Nhưng đây là **invalidation cache** chứ không phải derived value.
   Trigger sets it eagerly; alternative (compute via JOIN to
   audit log on every read) thrash. Acceptable carve-out, document
   trong column comment.

8. **Refresh = sync per-artifact, sync per-product, async TBD bulk.**
   Per-artifact ~10s (1 product × 1 shape derive); per-product ~30s
   (3 shapes); per-client could be 100s artifacts × 30s = >1h —
   needs async. MVP ship per-artifact + per-product sync; bulk gate
   behind feature flag if needed.

9. **No new module name conflict.** Existing `app/stores/staleness.py`
   handles tab-freshness (last upload vs last data). Track D goes
   into NEW module `app/stores/bom_staleness.py` — different concern.

## Risks

- **Trigger overhead on materials updates.** Mig 045 already triggers
  on `materials` writes. Adding 1 more trigger (writing to `bom_artifacts`)
  doubles work per UPDATE. Risk: catalog bulk-edit slow. Mitigation:
  trigger does single UPDATE statement với indexed JOIN; benchmark
  on Johnson catalog (246 materials × 4 cols touchable).
- **D2 trigger ripple.** Khi BTP `A` được ingest BOM lần đầu, all
  parents có `A` trong `bom_artifact_rows` get marked stale. Growatt
  has up to ~30 parents per BTP → manageable; Johnson similar. Single
  UPDATE statement với indexed JOIN.
- **post_ingest_hooks failure isolation.** Hook fails → confirm flow
  fails? Or hook fails → log + continue? Decision: log + continue.
  Hook failure marks new artifact `is_stale=true` với
  `dim='derive_hook_failed'` so staff sees + manually refreshes.
- **False positives.** Trigger fires on EVERY `materials.uom` UPDATE,
  even when new value = old value (no-op edit). Mitigation: trigger
  WHEN clause `OLD.uom IS DISTINCT FROM NEW.uom`.
- **Backfill on mig 053.** Existing 852 artifacts default `is_stale=false`,
  `stale_reasons=[]`. No retroactive scan — staff manually refreshes
  if known-stale (current state pre-mig). Acceptable; documented.
- **API contract churn.** Adding `is_stale` to `/api/v1/bom/artifact/{id}`
  is additive (consumers ignore unknown fields). Document trong
  `docs/API_CONTRACT.md`.
- **Sister apps unaware.** BCQT + CO won't render stale badges
  initially. Cross-link decision trong DECISIONS.md để sister-app
  team biết khi nào pick up.

## Open Questions

1. **Refresh button placement on bom.html?** Per-row refresh hay
   header "Refresh all stale" button? Recommendation: per-product
   refresh in row actions menu (kebab); header button = "Refresh
   all stale" với count badge.

2. **`stale_reasons` retention?** Resolve = clear list, hay archive
   để audit? Recommendation: clear (current `bom_audit_events`
   captures the refresh event with timestamp; double-storage waste).
   Defer ledger to option 4 if/when needed.

3. **Should D2 trigger also catch BTP BOM tombstone (delete)?** Yes
   — tombstoning a BTP's BOM means parents revert to "missing_child_bom"
   semantics. Add AFTER UPDATE on `bom_artifacts(tombstoned_at)`
   trigger that's symmetric to D2 INSERT.

4. **Cross-shape refresh atomicity?** Per-product refresh produces 3
   shapes (raw_graph stays, shallow + full_flat re-mint). Should
   refresh be transactional? Recommendation: yes — one transaction
   for the per-product refresh, all-or-nothing. Per-artifact refresh
   is single shape, no atomicity concern.

5. **Should trigger fire on `materials` INSERT?** New material doesn't
   affect existing artifacts (no row in `bom_artifact_rows` references
   it yet). NO — INSERT is no-op for staleness purposes. Trigger
   only on UPDATE.

## Manual test plan

### Schema + triggers (D1, D7, D8 — single-table)

1. Apply mig 053 trên local Johnson DB. Confirm:
   - `\d hub.bom_artifacts` shows new columns + index.
   - 4 trigger functions registered.
   - Existing 852 artifacts: `is_stale=false`, `stale_reasons=[]`.

2. **D1 test**: pick a Johnson `nvl` material referenced trong some
   parent's `bom_artifact_rows`. UPDATE category to `btp_sx`.
   Confirm: parent artifacts marked stale với `dim='catalog_category'`.

3. **D7 test**: UPDATE `materials.uom` cho 1 material referenced.
   Confirm: parent stale với `dim='materials_uom'`.

4. **D8 test**: UPDATE `materials.btp_sourcing` cho 1 BTP referenced.
   Confirm: parent stale với `dim='btp_sourcing'`.

5. **No-op test**: UPDATE `materials.uom` set = current value.
   Confirm: no stale flag (WHEN clause works).

6. **Cross-tenant isolation**: UPDATE Johnson material; confirm
   Growatt artifacts unaffected.

### D2 test (BTP BOM appears later)

7. Pick a Johnson BTP (`btp_sx`) currently `missing_child_bom` trong
   parent artifacts. Ingest BOM cho BTP đó qua upload flow. Confirm
   parent artifacts marked stale với `dim='btp_bom_added'`.

8. Tombstone the BTP BOM. Confirm parents marked stale lại với
   `dim='btp_bom_tombstoned'` (symmetric trigger).

### Refresh flow

9. Pick stale artifact. Click "Refresh now" trên detail page. Confirm:
   spinner, page reloads, `is_stale=false`, `stale_resolved_at`
   populated, `stale_reasons` cleared.

10. Per-product refresh trên list page. Confirm cả 3 shape re-minted,
    timing <60s cho Johnson.

### post_ingest_hooks wiring

11. Upload BOM file Johnson `multi_sheet_per_root` shape. Confirm
    derived BTP shallows minted automatically (count tăng), no manual
    `derive_btp_shallows.py` cần run.

12. Force hook failure (temporarily raise trong `_derive_btp_shallows_hook`).
    Confirm: artifact created với `is_stale=true`,
    `dim='derive_hook_failed'`, no exception bubbles to user.

### UI

13. Stale artifact: bom_artifacts.html row shows "⚠ stale" badge,
    tooltip lists dim VN translation.

14. bom.html list: phiên bản latest có stale → row shows "⚠ stale (N)"
    in trạng thái column.

15. EN switch: stale labels translate.

### API

16. `GET /api/v1/bom/artifact/<stale_id>` returns
    `{"is_stale": true, "stale_reasons": [{dim,source_table,...}], ...}`.

## Done criteria

- [ ] Mig 053 applied. Backward mig drops columns + triggers cleanly.
- [ ] 4 triggers wired (D1/D7/D8 on `materials`, D2 on
      `bom_artifacts INSERT`, D2-symmetric on
      `bom_artifacts UPDATE WHERE tombstoned_at`).
- [ ] post_ingest_hooks wired vào confirm flow tại
      `app/routes/bom.py:486` (hoặc nearest equivalent).
- [ ] Refresh routes: per-artifact + per-product. Bulk gated behind
      flag if scope tăng.
- [ ] UI badges trong 3 templates (bom.html, bom_artifacts.html,
      bom_artifact_detail.html). i18n VN+EN.
- [ ] API exposes `is_stale` + `stale_reasons` trong artifact
      endpoint. `docs/API_CONTRACT.md` updated.
- [ ] ~13 tests pass. Total suite green (820 + 13 ≈ 833).
- [ ] Screenshots: ~5 (stale badge list, stale badge artifacts,
      detail with refresh button, post-refresh state, API response
      JSON). Commit vào
      `.ai/features/2026-05-11-bom-staleness-track-d/screenshots/`.
- [ ] Memory updates:
  - NEW `project_bom_staleness.md` — 4 dim coverage, schema columns,
    refresh routes, Phase 2 deferred dims rationale.
  - Update `project_bom_immutable_principle.md` — note `is_stale`
    is invalidation cache (not violation; documented carve-out).
- [ ] STATUS.md + commit message reflect: "Track D Phase 1 — 4
      dimensions option-1 staleness flag + post_ingest_hooks wired".
- [ ] BACKLOG.md "BOM dependency staleness" entry updated: Phase 1
      shipped, Phase 2 (D3/D4/D5/D6 + ledger upgrade path) carry-over.

## Effort estimate

- Mig 053 + triggers: ~3-4h.
- post_ingest_hooks wiring: ~1h (scaffold exists).
- Refresh routes + UI + i18n: ~3-4h.
- Tests: ~2-3h.
- Screenshots + docs + memory: ~1h.
- **Total: ~10-13h** (~1.5d). Matches BACKLOG estimate.

Recommendation: ship as 1 commit (or 2 — schema mig commit +
routes/UI/wire commit) trong same session. Sequential `/tdd → /rev →
commit`.
