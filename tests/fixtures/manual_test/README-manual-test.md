# Manual Upload Test Files

Use these files from the web app. The runtime stores were reset to seeded state for a predictable run.

## Suggested Order

### Growatt catalog
1. `01-growatt-ds-nvl-full-missing-demo-npl-003.xlsx` with catalog type `DS NVL` and scope `Full catalog`. Expect `DEMO-NPL-003` to become `inactive_pending_review`.
2. `02-growatt-ds-nvl-partial-edit-demo-npl-001.xlsx` with catalog type `DS NVL` and scope `Partial update`. Expect `DEMO-NPL-001` name to change and other material codes to remain.
3. `03-growatt-ds-sp-full-products.xlsx` with catalog type `DS SP` and scope `Full catalog`. Expect no material changes and product catalog versioning to stay stable unless edited.

### Do Thanh BCCT
4. `10-do-thanh-bcct-import-tk001-pcs.xlsx`. Expect one import row and one C/O stock row.
5. `11-do-thanh-bcct-overlap-add-tk002.xlsx`. Expect TK-001 to remain and TK-002 to be added.
6. `12-do-thanh-bcct-reupload-tk001-pce-alias.xlsx`. Expect no-op because PCE normalizes to PCS.
7. `13-do-thanh-bcct-reupload-tk001-kg-conflict.xlsx`. Expect `correction_candidate`.
8. `14-do-thanh-bcct-reupload-tk001-qty-conflict.xlsx`. Expect another `correction_candidate`.
9. `15-do-thanh-bcct-mixed-import-export.xlsx`. Expect only the import row to create C/O stock.

### Growatt BOM
10. `20-growatt-bom-direct-no-change.xlsx` as `Direct BOM`. Expect no new version.
11. `21-growatt-bom-direct-changed-qty.xlsx` as `Direct BOM`. Expect aggregate BOM v2 and product `PV00.0048500` v2.
12. `22-growatt-bom-direct-full-retire-pv01.xlsx` as `Direct BOM`, full scope. Use only on a fresh/reset run if you specifically want to check retired missing products.
13. `23-growatt-bom-direct-partial-pv00-only.xlsx` as `Direct BOM` with `Partial product` scope. Use only on a fresh/reset run if you specifically want to check preserving missing products.
14. `24-growatt-bom-duplicate-row.xlsx` as `Direct BOM`. Expect validation error for duplicate BOM key.
15. `25-growatt-technical-needs-flatten-review.xlsx` as `Technical BOM` without accepting review. Expect review-required warning, no published version.
16. `26-growatt-technical-accept-as-flat.xlsx` as `Technical BOM` with accept-review checkbox enabled. Expect a new version.

### Johnson BOM
17. `30-johnson-technical-sap-leaf-only.xlsx` on Johnson as `Technical BOM`. Expect only leaf rows `004426-00` and `1000461274`; parent `ASM-001` should not publish as material.

### C/O case workbook
18. `00-growatt-demo-input.xlsx` on Growatt C/O Case upload. Expect the seeded C/O case to parse and evaluate.
