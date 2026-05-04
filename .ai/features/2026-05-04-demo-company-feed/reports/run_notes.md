# Demo Feed Run Notes

Client: `demo-precision-manufactu-480e` (`Demo Precision Manufacturing VN`)

Final DB state:
- Catalog: 50 rows (`34 nvl`, `7 btp_sx`, `8 tp`, `1 ccdc`)
- BQD: 50 identity pairs
- BCCT: 1,000 rows (`650 import`, `350 export`)
- BOM: 15 flattened products (`8 TP`, `7 BTP`), 97 flattened rows, 0 unresolved nodes

API smoke:
- `/v1/hub/dncxs/demo-precision-manufactu-480e/client-config`: 200
- `/v1/hub/materials?client_id=demo-precision-manufactu-480e&limit=5`: 200
- `/v1/hub/bcct?client_id=demo-precision-manufactu-480e&direction=import&limit=5`: 200
- `/v1/hub/products?client_id=demo-precision-manufactu-480e`: 200, 15 products
- `/v1/hub/products/TP-001/bom/latest?client_id=demo-precision-manufactu-480e`: 200, 10 BOM rows

One correction happened during the run: the first BQD file used catalog category
`btp_sx`, but `hub.code_mappings` still has the legacy category enum
`nvl|tp|ccdc`. That confirm hit a 500 and left one pending upload. The input
generator was corrected so BTP codes map to `tp` for BQD only, the stale
pending was rejected through the UI, and the corrected BQD was uploaded and
confirmed successfully.
