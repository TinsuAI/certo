# Sister-app notes — index

Cross-repo coordination notes from Data Hub to CO + BCQT. Read these
**in chronological order** if you're starting sister-app integration
fresh; jump to the matching dated note if you're following a specific
shipment.

Each note is self-contained but later notes occasionally amend or
correct earlier claims — always read amendments noted in each file's
header.

| Date | File | What changed | Migrations |
|---|---|---|---|
| 2026-05-02 | `2026-05-02-bcqt-client-config-available.md` | `client_type_presets` available for BCQT settlement profiles | 019 |
| 2026-05-02 | `2026-05-02-co-migrate-to-client-config.md` | CO should adopt `client_config` for declaration-type filters | 019 |
| 2026-05-02 | `2026-05-02-service-account-jwts-available.md` | Service-account JWT minting CLI shipped; CO + BCQT can request tokens | 020 |
| 2026-05-03 | `2026-05-03-bcct-key-shape-cleanup.md` | BCCT row PK + duplicate cleanup | 024-027 |
| 2026-05-03 | `2026-05-03-bcct-typed-column-semantics-corrected.md` | FX (`*_nt`) vs VND domain split corrected | 026 |
| 2026-05-03 | `2026-05-03-bcct-invoice-market-fields-shipped.md` | Invoice / market fields exposed on BCCT API | — |
| 2026-05-03 | `2026-05-03-bom-flatten-shipped.md` | BOM flatten engine + raw_graph / shallow / full_flat shapes | 029 |
| 2026-05-07 | `2026-05-07-bcct-product-identity-shipped.md` | `product_identity` resolver on BCCT API; 5-stage logic | 032 |
| 2026-05-07 | `2026-05-07-catalog-roles-shipped.md` | `v_material_roles` view + observed_roles signal in API | 033 |
| 2026-05-08 | `2026-05-08-material-identity-rename-and-internal-code-drop.md` | `product_identity` → `material_identity` rename; `bcct_rows.internal_code` dropped; configurable parser rules; 666 Growatt resolves fixed | 035-038 + `client_parser_rules` table |
| 2026-05-09 | `2026-05-09-catalog-multi-source-and-vocab.md` | `materials.customs_code` → `material_code` rename; `internal_code` dropped; provenance jsonb keys → typed columns; `v_material_roles` extended | 042-043 |
| 2026-05-12 | `2026-05-12-uom-conversion-cutover.md` ⭐ | Phase 2 UoM conversion engine + Phase 3 G refresh-preview (amended 2026-05-13). **BREAKING for derived BOM consumers — derived rows now in catalog UoM, not raw.** | 053-058 |
| 2026-05-13 | `2026-05-13-catalog-candidates-shipped.md` | Mã chờ duyệt feed + `materials.production_source` enum (covers gap in 2026-05-09 note for mig 047-049) | 047-049 |
| 2026-05-28 | `2026-05-28-bcct-incremental-since-available.md` | `since` + `tombstones` on `GET /v1/hub/bcct` for CO incremental refresh; `transaction_key` stability confirmed | — |
| 2026-05-28 | `2026-05-28-bcct-declarations-download-bearer-available.md` | Bearer mirror of `/clients/{c}/declarations/download.zip` at `/v1/hub/clients/{c}/declarations/download.zip` for CO dossier builder | — |
| 2026-05-28 | `2026-05-28-bom-artifacts-picker-filter-available.md` | `lifecycle`/`shape`/`intents`/`latest_per_variant`/`case_id` filters on `/bom/artifacts` for CO picker; `filter_applied` echo for support detection | — |
| 2026-05-28 | `2026-05-28-bom-vocab-v1-aliases-removed.md` | **Breaking.** BOM vocab v1 URL aliases (`/bom/version/{id}`, `/bom/{p}/versions`, `/v1/hub/.../bom/versions`) now return 404 instead of 308. Canonical `/artifact*` URLs unchanged | — |
| 2026-05-29 | `2026-05-29-service-account-admin-ui-and-1y-tokens.md` | Service-account admin UI (`/admin/service-accounts`); default token TTL 30d → 1y; **CO action: set `DATA_HUB_SERVICE_TOKEN` (not `DATA_HUB_API_TOKEN`)**. Non-breaking | 073-074 |

## Read order if starting fresh today (2026-05-13)

If a sister-app dev is starting integration from scratch and needs to
know "what's the current state to build against", read in this order:

1. **2026-05-12-uom-conversion-cutover.md** ⭐ (most recent + most
   impactful — read the Phase 3 G addendum at bottom).
2. **2026-05-09-catalog-multi-source-and-vocab.md** + the
   **2026-05-13-catalog-candidates-shipped.md** addendum.
3. **2026-05-08-material-identity-rename-and-internal-code-drop.md**
   (the `material_identity` API surface).
4. **2026-05-07-catalog-roles-shipped.md** (multi-role observed_roles).
5. Older notes only if your code has dependencies that pre-date them
   (BCCT key shape, invoice fields, original BOM flatten).

## Open coordination items (per current BACKLOG theme C)

- **C.1 Service-account JWT adoption** — sister apps still pass
  legacy bearer / user JWTs. Adopt before C.2.
- **C.2 API auth strict** — Data Hub reads still permissive in dev.
  Sister apps need C.1 done first.
- **C.3 Drop BOM vocab v1 aliases** — SHIPPED 2026-05-28. See
  `2026-05-28-bom-vocab-v1-aliases-removed.md`.

See `.ai/BACKLOG.md` § C for details.
