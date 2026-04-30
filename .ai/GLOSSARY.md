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
