# Feature brief — Mẫu 16/ĐMTT/GSQL ingest for Johnson 2025

**Date:** 2026-05-13
**Owner:** dennis (this session)
**Status:** Drafted — awaiting confirm-to-proceed

## Why

Source-of-truth BOM nộp hải quan cho Johnson năm 2025 (`Mẫu 16/ĐMTT/GSQL`,
kỳ 01/01/2025–31/12/2025). Hiện hệ thống chỉ có technical BOM SAP cho 106
sản phẩm; Mẫu 16 cover 517 sản phẩm — coverage tăng ~4.9× cho CO dossier.

Mẫu 16 là BOM **filed-with-customs**, authoritative cho hồ sơ CO. Cần
song song với SAP technical (làm reference), CO-side default chọn Mẫu 16.

## Source file

`/mnt/p/Downloads/BCDM_TT39 Dinh muc 2025 johnson.xls` (5.8M, OLE legacy
.xls, WPS Spreadsheets, lập 28/02/2026)

- Sheet `BCTT39`: 42,301 rows × 9 cols (header 11 rows, data 42,287
  rows, footer 3 rows incl. chữ ký)
- Sheet `Sheet1`: 47 rows × 3 cols (metadata phụ, ignore)
- Shape: flat 2-level TP → NVL trực tiếp
- Cột Stt/Mã SP/Tên SP/ĐVT SP **forward-fill required** (chỉ điền ở dòng
  đầu mỗi block)

## Data audit (explore output)

| Check | Result |
|---|---|
| TP distinct | **517** (all `category='tp'` in catalog, 0 missing) |
| NVL distinct | **4,053** (3,830 nvl + 223 btp_sx, 0 missing) |
| Pair rows | 42,289 |
| Zero qty | 0 |
| Negative qty | 0 |
| Non-numeric qty | 0 |
| UoM tokens covered by `hub.uom_aliases` | 8/9 |
| UoM token NOT covered | `Chai/ Lọ/ Tuýp` — 26 rows = 0.06% |
| TP overlap with existing `technical_raw` artifacts | 49/517 |

## Decisions (chốt với user 2026-05-13, revised)

1. **BOM kind**: `source_bom_kind='manual_flat'` (reuse existing kind) +
   `flatten_status='flattened'` + `context = {regulatory: 'm16_2025',
   filed_with: 'customs', period_from: '2025-01-01', period_to:
   '2025-12-31'}`.
2. **Naming**: thêm column `bom_artifacts.human_label TEXT NULL` (mig 065).
   - Mẫu 16 ingest → `human_label='Mẫu 16/2025'`
   - Backfill existing technical_flattened → `human_label='BOM kỹ thuật SAP'`
   - API responses surface human_label, fallback display_label
3. **Mở rộng enum (mig 066)** — pre-fix: round-1 ingest dùng
   `actor='erp_pipeline'` và `intent='asserted_technical'` chỉ vì
   constraint cũ không có giá trị fit. Mig 066 thêm:
   - `actor='customs_filing'` cho regulatory filings (Mẫu 15/15a/16…)
   - `intent='customs_declared'` cho BOM khai báo với hải quan
4. **bom_variant_id='m16_<year>'** — Mẫu 16 mỗi năm là 1 variant đặc
   trưng (vd `m16_2025`). Bỏ post-filter hack "manual_flat thắng
   technical_flattened"; variant_id partition tự nhiên phân biệt.
5. **Dual-BOM (49 TP)**: CO view list cả 2 variants, CO repo handle
   dropdown + default-pick. /v1/hub/products/{p}/bom/latest trả về 409
   dual_source với cả manual_flat (m16_<year>) lẫn technical_flattened
   ('default') variants, mỗi variant có human_label để CO disambiguate.
6. **Exec path**: script-only, no Web UI gate. Backlog: surface trong
   Web UI sau (catalog/upload form chọn shape='manual_flat_customs').

## Scope of THIS session (Data Hub repo)

### In-scope

1. **Migration 065** — `bom_artifacts.human_label TEXT NULL`
2. **Backfill SQL** — set `human_label` cho existing technical_flattened
   của Johnson
3. **Preprocess script** `scripts/preprocess_mau16_to_xlsx.py`:
   - read .xls (xlrd), forward-fill cột TP, skip header/footer
   - emit clean .xlsx for `manual_flat` adapter
4. **Ingest script** `scripts/ingest_mau16_johnson.py`:
   - call `manual_flat.parse()` on preprocessed blob
   - create 517 artifacts qua `app.stores.bom.create_artifact()` với:
     - `source_bom_kind='manual_flat'`
     - `flatten_status='flattened'`
     - `flatten_strategy='no_strategy'` (flat input = flat output)
     - `intent='asserted_technical'` (filed-with-customs counts as
       asserted)
     - `actor='system:ingest_mau16'`
     - `human_label='Mẫu 16/2025'`
     - `context.regulatory='m16_2025'`, `context.filed_with='customs'`,
       `context.period_from='2025-01-01'`, `context.period_to='2025-12-31'`,
       `context.source_file='BCDM_TT39 Dinh muc 2025 johnson.xls'`
   - UoM gate: `Chai/ Lọ/ Tuýp` (26 rows) → drift gate ack với evidence
     tag `mau16_phase2_pending`. Không block ingest (other rows pass).
5. **API change** — `latest_flattened_versions()` partition by
   `(bom_variant_id, flatten_strategy, source_bom_kind)` để 49 TP overlap
   trả về 2 variants (dual-source). Response include `human_label`.
6. **API change** — `list_artifacts_for_product()` include `human_label`
   in response.
7. **Tests**:
   - Unit: preprocess forward-fill + footer skip
   - Integration: ingest script → 517 artifacts created với expected
     context/labels
   - Integration: `latest_flattened_versions` trả 2 variants cho 1 TP
     overlap, trả 1 cho TP-only-m16, trả 1 cho TP-only-technical
   - Backfill SQL idempotent

### Out-of-scope (separate work)

- **CO repo (`~/workspace/client/barry-CO-main`)** — handle 409 dual_source,
  show dropdown with human_label, default Mẫu 16. Cross-repo coordination
  ticket. Until CO ships, /bom/latest will return 409 cho 49 TP overlap;
  consumers MUST call /bom?artifact_id=... or /bom/artifacts.
- **Web UI Mẫu 16 upload form** — script-only this session. Web UI follow-up:
  extend unified upload mapping flow để recognize Mẫu 16 layout (header
  pattern + 4-col forward-fill auto-detect).
- **UoM phase 2 — `Chai/Lọ/Tuýp` alias** — already queued in
  `2026-05-12-bom-uom-conversion-phase-2/factor_inventory.md`. Ack inline
  for this ingest; permanent resolution per that ticket.

## Done criteria

- [ ] Mig 065 applied to local + tested rollback
- [ ] 517 artifacts với `source_bom_kind='manual_flat'`, all `published`
- [ ] `SELECT count(*) FROM hub.bom_artifacts WHERE client_id='johnson-vn'
      AND source_bom_kind='manual_flat'` returns **517**
- [ ] `SELECT count(*) FROM hub.bom_artifact_rows ar JOIN hub.bom_artifacts a
      USING(artifact_id) WHERE a.client_id='johnson-vn' AND
      a.source_bom_kind='manual_flat'` returns **42,289**
- [ ] `human_label='Mẫu 16/2025'` on all 517 new artifacts
- [ ] `human_label='BOM kỹ thuật SAP'` on existing 6,274 technical_flattened
- [ ] `latest_flattened_versions` smoke for 3 cases:
  - TP overlap (e.g. one of the 49) → 2 rows
  - TP only-Mẫu-16 → 1 row, source_bom_kind='manual_flat'
  - TP only-technical → 1 row, source_bom_kind='technical_flattened'
- [ ] All 219+ existing tests still pass (no regression)
- [ ] New tests for ingest + dual-source variant query pass

## Manual test plan

1. `psql -U vp -d data_hub -c "\\d hub.bom_artifacts"` → confirm
   `human_label` column present
2. `uv run python scripts/preprocess_mau16_to_xlsx.py /mnt/p/Downloads/BCDM_TT39\ Dinh\ muc\ 2025\ johnson.xls /tmp/m16_flat.xlsx`
3. `uv run python scripts/ingest_mau16_johnson.py /tmp/m16_flat.xlsx` →
   should print "517 artifacts created, 42,289 rows inserted, 26 UoM
   drift acked"
4. `psql -U vp -d data_hub` — run the 4 SELECT done-criteria checks
5. `curl -s http://127.0.0.1:8754/v1/hub/products/<one_of_49>/bom/latest?client_id=johnson-vn`
   with bearer → expect 409 dual_source response with 2 variants, both
   with human_label set
6. `curl -s http://127.0.0.1:8754/v1/hub/products/MAS1213-00KM/bom/latest?client_id=johnson-vn`
   (TP only in Mẫu 16) → expect 200, artifact has human_label='Mẫu 16/2025'

## Risks + mitigations

- **R1: Breaking `/bom/latest` for 49 CO-overlap TPs (200 → 409)** —
  **Reversed decision after round-2 audit**: variant_id partition is
  semantically correct (m16_<year> ≠ technical 'default'), so 49 overlap
  TPs SHOULD return 409 with both variants surfaced. CO must handle
  dropdown using `human_label` + `bom_variant_id`. CO-side rollout
  needed before this lands in production — local dev / demo can ship
  immediately since CO consumer is read-only and Data Hub releases
  independently.
  - Pre-condition for prod: CO repo (`~/workspace/client/barry-CO-main`)
    must handle dual_source 409 with new variant shape (m16_<year>).
    Already coordinated as out-of-scope per decision 5.
- **R2: `Chai/Lọ/Tuýp` UoM 26 rows unresolved**
  - Mitigation: ack drift inline with marker, don't block. Permanent
    fix in Phase 2 alias ticket.
- **R3: Existing 6,274 technical_flattened artifacts get human_label
  backfill** — pure metadata, no data risk. Idempotent UPDATE.
- **R4: Forward-fill bug** — if Stt is set on a row where Mã SP is
  empty (sentinel rows), script must skip. Empirical 2 occurrences in
  file (footer signature lines) — explicit skip.

## Backlog (post-this-session)

- Web UI Mẫu 16 upload form (auto-detect layout, header pattern,
  forward-fill in mapping page preview)
- CO repo dropdown + default Mẫu 16
- UoM Phase 2: `Chai/Lọ/Tuýp` permanent alias
- Periodic ingest cadence: Mẫu 16 nộp hàng năm, một artifact set / năm.
  Subsequent ingests should tombstone prior `m16_2024` artifacts? Or
  keep historical? — TBD, low priority.
