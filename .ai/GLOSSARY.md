# Glossary

Domain-specific terms for customs compliance + this product's architecture.

## Customs compliance domain

- **HQ** — Hải quan (customs authority).
- **DNCX** — Doanh nghiệp chế xuất (export-processing enterprise). Manufacturing factories with bonded import-for-export status under Vietnam customs law. Customers of agencies (not direct system users).
- **BCQT** — Báo Cáo Quyết Toán (annual customs settlement report). Required of every DNCX. Aggregates a year of customs declarations + ERP material movement into Mẫu 15 / 15a / 16 forms.
- **CO** — Certificate of Origin / Giấy chứng nhận xuất xứ. Per-shipment customs document attesting goods origin for trade-agreement preferential tariff.
- **BCCT** — Báo Cáo Cập Nhật Tờ khai (customs declaration registry). Excel listing of all import/export declarations for a DNCX in a year. Critical input for both BCQT settlement + CO origin verification.
- **NXT** — Nhập Xuất Tồn (input/output/balance). ERP-side inventory movement summary by material code. Used for cross-checking customs declarations against actual material flow.
- **Danh Mục** — Material registry / catalog. List of NVL/SP/BTP (raw materials / finished products / semi-finished products) used by a DNCX, with HS codes + customs codes mapped.
  - **NVL** — Nguyên Vật Liệu (raw materials).
  - **SP** — Sản Phẩm (finished products).
  - **BTP** — Bán Thành Phẩm (semi-finished products / WIP). Subdivided: BTP_SX (self-produced), BTP_NM (purchased + declared as import).
- **BOM** — Bill of Materials. Product structure showing what raw materials/sub-assemblies go into each finished product. Required for Mẫu 16.
- **Mẫu 15 / 15a / 16** — Settlement report forms per Thông tư 39/2018/TT-BTC. Mẫu 15 = raw materials. Mẫu 15a = finished products. Mẫu 16 = norms / consumption rates per product.
- **TT 39/2018** — Thông tư 39/2018/TT-BTC, regulatory basis for BCQT format.
- **TT 121/2025** — Thông tư 121/2025 (newer regulation), introduces Mẫu 15a column split + Mẫu 16 separate norms for re-imported products.
- **Tờ khai** — Customs declaration. Each import/export shipment files one. Identified by `declaration_no`.

## BOM model — canonical vocabulary

Chốt 2026-05-07 trong đợt review terminology Phase 3. Đây là tên gọi
duy nhất nên dùng trong code, doc, UI, conversation. Tên cột DB hiện
tại lệch với vocab này — rename pass sẽ đồng bộ trước Phase 3a.

### Khái niệm chính

- **Phiên bản BOM** *(logical)* — 1 đơn vị BOM cho 1 product, gắn với
  1 lineage track (hoặc 1 case CO). Là "phiên bản" mà staff nghĩ
  trong đầu khi nói "BOM của TP-001 sau lần upload tháng 4". Không có
  cột DB riêng; identity = tuple `(client, product, variant,
  lineage_root_id, case_id)`.
- **Bản lưu** *(artifact, storage row)* — 1 cách lưu cụ thể của 1
  phiên bản. Mỗi phiên bản đẻ 1-N bản lưu, mỗi cái khác nhau ở
  *shape × strategy*. Tương ứng 1 row trong bảng `bom_artifacts`
  (sau rename) / `bom_versions` (hiện tại).
  - Phiên bản thông thường: 3 bản lưu (raw_graph + shallow + full_flat).
  - Có ≥1 BTP dual-source: 4 bản lưu (raw_graph + shallow + 2 full_flat
    variants).
- **Preset** *(saved interpretation)* — 1 row trong `bom_presets` (sau
  rename) / `bom_resolution_profiles` (hiện tại). Pin 1 bản lưu làm
  *anchor* + sourcing override per-BTP. Consumer (CO/BCQT) gọi BOM qua
  tên preset thay vì pin artifact_id trần.

### Thuộc tính của bản lưu

- **Shape** *(hình dạng)* — `raw_graph` | `shallow` | `full_flat`.
  Derive từ `flatten_status × flatten_strategy` qua helper
  `bom_shape()`. Định nghĩa chi tiết: memory `project_bom_3_shapes.md`.
- **Strategy** *(chiến lược flatten BTP)* — TP-level enum:
  `purchased_btp_as_leaf`, `self_produced_btp_exploded`,
  `technical_exploded`, `manual_flat_as_provided`, `mixed_confirmed`,
  `no_strategy`, `not_applicable`. **TP-level**, không per-BTP. Đây là
  nguồn của giới hạn "tối đa 2 full_flat artifacts" — mọi mix per-BTP
  resolve bằng `preset.sourcing_choices` lúc query, không materialize.

### Khái niệm phụ

- **Sourcing** — quyết định "BTP X mua hay tự sản". Sống ở 2 chỗ:
  catalog default (`materials.btp_sourcing`) + preset override
  (`presets.sourcing_choices` jsonb).
- **Lineage** — chain parent-child giữa các bản lưu qua
  `parent_artifact_id`. CO sửa BOM = bản lưu mới có lineage trỏ về
  bản lưu nguồn.
- **Upload** — sự kiện upload 1 file qua UI hoặc CLI script. 1 file =
  1 upload event. Nhiều bản lưu có thể chia sẻ cùng `source_upload_id`.
- **Case** *(lô hàng CO)* — 1 đơn vị nghiệp vụ CO, identified bởi
  `case_id`. CO modification cho 1 case sinh ra 1 phiên bản BOM riêng.

### Đợt *(legacy variant label)*

Cột `bom_variant_id` là **legacy artifact** từ bulk-load Growatt-shape
(2 file TP + BTP cùng đợt nghiệp vụ, cần "snapshot binding" chéo file).
Production UI hiện tại upload 1 file/lần → variant tự collapse về
`'default'`. Reasoning thiết kế:

- *By-name binding* (hiện tại): rows lưu child theo `material_code` +
  scope BTP lookup theo variant lúc flatten. Loose binding,
  late-resolved.
- *By-reference binding* (alternative): rows pin `child_artifact_id`
  trực tiếp. Tight binding, no variant needed. Migration ~15-20h, đẩy
  BACKLOG.md.

UI: **ẩn variant khi `default`**, chỉ hiện cho row có value khác. Không
expose trong upload form mới.

### Mapping rename DB ↔ vocab

| Vocab | DB cũ | DB mới (rename pass trước 3a) |
|---|---|---|
| Bản lưu (table) | `hub.bom_versions` | `hub.bom_artifacts` |
| Bản lưu rows | `hub.bom_version_rows` | `hub.bom_artifact_rows` |
| Preset (table) | `hub.bom_resolution_profiles` | `hub.bom_presets` |
| ID bản lưu | `version_id` | `artifact_id` |
| Số thứ tự bản lưu | `version_no` | `artifact_no` |
| Lineage parent | `parent_version_id` | `parent_artifact_id` |
| Materialized FK | `materialized_version_id` | `materialized_artifact_id` |
| FK trong preset | `bom_version_id` | `artifact_id` |
| FK trong bcct_rows | `bom_version_id` | `artifact_id` |
| Preset ID | `profile_id` | `preset_id` |
| Code class | `BomVersion` | `BomArtifact` |
| Code class | `Profile`, `profile_*` | `Preset`, `preset_*` |
| Variant label | `bom_variant_id` | giữ (legacy, comment internal) |

Quy tắc đọc nhanh:

- Nghe **"phiên bản"** → logical, không có cột riêng, là tuple.
- Nghe **"bản lưu"** → 1 row trong `bom_artifacts`.
- Nghe **"preset"** → 1 row trong `bom_presets`.
- Nghe **"shape"** → 1 trong 3 hình dạng.
- Nghe **"strategy"** → cách materialize BTP của TP đó.

## Architecture (Tinsu AI 3-product portfolio)

- **Data Hub** *(this repo, provisional name)* — master records management. Owns shared HQ-data tier (BCCT + Danh Mục + BOM). MVP-phase-2: file snapshots.
- **BCQT-System** *(`~/workspace/client/BCQT-System`)* — annual settlement reports. Read-only consumer of Data Hub.
- **CO-System** *(`~/workspace/client/barry-CO-main`)* — origin certificates per-shipment. Read-only consumer of Data Hub for HQ-data; writes per-shipment BCCT to Data Hub via API.
- **Hub schema** — Postgres schema owned by Data Hub. Other apps read-only.
- **App schema** — each consumer app's private schema (`bcqt`, `co`). Each app writes only to its own.
- **Per-project SQLite** — BCQT-only pattern. One `.db` file per BCQT project (DNCX + year). Holds project-truly-local data (settlement output, findings, pipeline runs).

## Tinsu AI roles

- **Tinsu AI** — vendor. Builds + maintains the 3 products. Internal: developers (adapter authoring + investigation).
- **Agency** *(đại lý hải quan)* — customer of Tinsu AI. Runs the system. Each agency typically handles 10-20 DNCX clients per year. Internal: staff users.
- **DNCX** — customer of agency. Provides raw data, answers clarifying questions. Not a system user.
