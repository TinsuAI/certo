# Prompt for next CO session — Data Hub product_identity migration

**Date:** 2026-05-07
**Source:** Data Hub team (cross-repo handoff)
**Status:** Awaiting CO session to act

---

Data Hub vừa ship 2 features liên quan tới CO. Cần migrate CO consumer
để sử dụng contract mới + remove legacy code-mappings BOM resolution.

## Context

Đọc 2 sister-app notes mới từ Data Hub:

1. `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-07-bcct-product-identity-shipped.md`
   — `product_identity` field thêm vào `/v1/hub/bcct` + `/v1/hub/bcct/invoice-matches`

2. `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-07-catalog-roles-shipped.md`
   — `observed_roles[]` + atomic signals + `is_multi_role` + `declared_observed_conflict`
   thêm vào `/v1/hub/materials*` + `product_identity` response

## Yêu cầu

Đọc 2 notes trên + scope CO migration cho 2 features:

### Feature 1 — BCCT BOM product resolution (CORE — replace legacy)

- Original CO API request (đã được Data Hub fulfill):
  `.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md`
- Mục tiêu: CO origin sheet calc dùng `product_identity.bom_product_code`
  thay vì parse goods_name hay dùng code-mappings.
- Steps:
  - Update `app/data_hub_client.py`: surface `product_identity` field
    trên `list_bcct()` + `invoice_matches()` adapter normalization.
  - Update CO origin workflow: filter
    `product_kind == 'tp' AND bom_product_code` để load BOM artifacts.
  - **Remove** CO's temporary code-mappings-based BOM resolution
    (legacy code in case_origin or wherever CO currently parses).
  - Update `co_case.html` để surface `ambiguous` / `missing` /
    `unverified` states cho operator action.

### Feature 2 — Catalog roles (OPTIONAL — additive, non-breaking)

- `observed_roles[]` + `is_multi_role` có thể useful cho CO origin sheet
  để cảnh báo operator về rework codes:
  ```python
  if pid["is_multi_role"]:
      warn("multi-role TP — verify rework context before locking sheet")
  ```
- Optional: log `declared_observed_conflict` to integrity dashboard cho
  staff review.
- Có thể defer nếu Feature 1 đủ scope cho sprint.

## Bắt đầu

`/discover` cho 2 migrations. Output brief duy nhất tại:

```
.ai/features/2026-05-07-data-hub-product-identity-consumer/brief.md
```

**Không code yet.** Brief xong, ping Data Hub team để review trước khi `/tdd`.

## Live test endpoints

Data Hub đang chạy ở `http://127.0.0.1:8754` (auth dev-permissive — bất kỳ
bearer string nào cũng được trong dev mode):

```
GET /v1/hub/bcct?client_id=growatt-vn&direction=export&include_product_identity=true&limit=3
GET /v1/hub/bcct/invoice-matches?client_id=growatt-vn&invoice_no=...&declaration_types=E42
GET /v1/hub/materials?client_id=growatt-vn&category=btp_sx&limit=5
GET /v1/hub/materials/PV01.0104300?client_id=growatt-vn   # the rework golden case
```

Auth header: `Authorization: Bearer dev`.

## Real-data evidence

- **Spec golden case** (BIENTAN.17 → PV01.0117500): Growatt BCCT export
  rows với `goods_name` chứa `(PV01.0117500)` resolve về `bom_product_code = "PV01.0117500"`.
- **Multi-role rework**: `PV01.0104300` (Growatt) — declared `btp_sx`,
  observed `["tp", "btp_sx"]`, `is_multi_role=true`. Verify ở Data Hub
  catalog UI: `http://127.0.0.1:8754/clients/growatt-vn/catalog?q=PV01.0104300`.
- **Resolution rates** (Data Hub real-data dry-run):
  - Growatt: 22,200 / 23,080 = 96% (gồm cả imports — Stage 1 hits)
  - Johnson: 52,172 / 52,224 = 99.9%

## Coordination

Sau khi CO migrate xong:
- Update `~/workspace/client/data-hub/.ai/sister-app-notes/` với note ngược
  `2026-05-XX-co-product-identity-consumer-shipped.md`.
- Coordinate test parity: CO origin sheet output before/after migration
  should be byte-identical for Growatt sample case.
