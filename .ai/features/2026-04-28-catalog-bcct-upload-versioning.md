# Feature: Catalog And BCCT Upload Versioning

## Scope

Build upload, parse, compare, version, and audit management for three client data modules:

- DS NVL DK HQ: customs-registered material/input catalog.
- DS SP DK HQ: customs-registered finished-product catalog.
- BCCT: detailed customs declaration transaction report.

This extends the same operating principle as BOM Builder, but not the same semantics:

- Catalogs are reference master evidence.
- BCCT is transaction evidence.
- BOM remains product-structure evidence.

The feature should make the current read-only views interactive:

- `GET /clients/{client_id}/catalog` currently renders `client.product_catalog` and `client.material_catalog`.
- `GET /clients/{client_id}/bcct` currently renders `client.bcct_rows`.
- Both should support workbook template download, upload, parse result, version history, diff summary, upload log, and audit trail.

Explicitly out of scope for the first implementation:

- Production database migration.
- Final HQ/internal code mapping workflow.
- Automatic correction of customs registration mistakes.
- Treating BCCT as a canonical catalog source.
- Full CO-stock allocation engine rewrite.

## Decisions

Use a shared source-module store instead of copying `bom_store.py` three more times.

The BOM store has useful infrastructure that should be extracted or mirrored cleanly:

- per-client file-backed root under `data/local/...`
- raw upload retention
- immutable parsed snapshots
- normalized hash comparison
- version records
- upload log
- audit events
- file lock
- atomic JSON write
- UUID-based IDs

Recommended storage shape:

```text
data/local/source-modules/
  clients/{client_id}/
    material-catalog/
    product-catalog/
    bcct/
```

Each module should keep:

- `state.json`
- `uploads/{upload_id}/raw/{filename}`
- `snapshots/{snapshot_id}/snapshot.json`
- `snapshots/{snapshot_id}/rows.json`
- `versions/v{version_no}/version.json`
- `versions/v{version_no}/rows.json`
- `versions/v{version_no}/diff.json`

Versioning model:

- Material catalog has one published aggregate version per client.
- Product catalog has one published aggregate version per client.
- BCCT is a transaction ledger built from arbitrary report uploads. Upload coverage dates are metadata, not row identity.
- BCCT published state should be keyed by stable transaction rows and must keep immutable source-line IDs for later CO-stock allocation.

Default upload scope:

- Catalog upload should default to `full_catalog`, because ECUS/customs catalog exports are usually a complete registration list snapshot.
- BCCT upload should default to `append_or_review_by_transaction_key`, because exports can be arbitrary and can overlap existing uploads.
- Allow `partial_update` only as an explicit advanced option for catalog maintenance.

Initial parser targets:

- Direct flat Excel for DS NVL with columns equivalent to: customs code, internal code, description, HS, unit, role/status.
- Direct flat Excel for DS SP with columns equivalent to: product code, description, HS, origin rule/status.
- Direct flat Excel for BCCT with columns equivalent to: coverage period if present, declaration number, declaration date, direction, line number, item code, description, HS, quantity, unit, customs value, customs office, declaration type, invoice/reference fields.

Canonical row keys:

- DS NVL: `customs_code` for single-code clients; later add mapping key when `customs_code != internal_code`.
- DS SP: `product_code`.
- BCCT primary transaction key: `direction + declaration_no + line_no + item_code`.
- BCCT collision-check fields: `declaration_date`, `customs_office`, `declaration_type`, `hs_code`, `unit`, quantity, and customs value.
- Every BCCT import row must also receive an immutable `import_row_id`; CO stock allocation must reference this ID, not only material code or upload batch.

Validation and reconciliation should be separate from version publishing:

- BCCT import item codes should be checked against DS NVL, but missing codes should be warnings.
- BCCT export item codes should be checked against DS SP, but missing codes should be warnings.
- BOM material codes should be checked against DS NVL only as reconciliation evidence.
- Catalog rows should not be silently created from BCCT.
- A BCCT row with a new transaction key should be added.
- A BCCT row with an existing key and identical normalized fields should be a no-op.
- A BCCT row with an existing key and changed quantity, value, HS, unit, or declaration metadata should become a `correction_candidate`; keep both old and new rows until reviewed.
- Existing BCCT rows missing from a new upload must not be deleted because uploads may be arbitrary or partially overlapping.
- A full catalog upload that omits an existing code should mark that code as `inactive_pending_review`, not retire or delete it automatically.

CO case integration:

- C/O case should snapshot catalog versions and reviewed BCCT row sets used, similar to BOM snapshot.
- First pass can surface selected versions in the case view without recalculating all allocation logic.
- Later, CO stock allocation should consume BCCT import rows and prior allocation ledgers, not raw catalog rows.
- CO stock has no source other than import rows. Aggregated material balance is only a rollup over import-row balances.
- A C/O case must not consume unreviewed `correction_candidate` rows.

## Risks

The biggest design risk is collapsing source semantics:

- DS NVL and DS SP are reference catalogs.
- BCCT is transaction evidence.
- BOM is engineering evidence.

If one generic "item table" is used too early, the system will lose the ability to explain whether a code came from registration, transaction, or technical structure.

BCCT versioning is not the same as catalog versioning.

- Catalog snapshots can be replaced as "current registration list".
- BCCT rows are historical transactions and should accumulate by transaction key.
- Report coverage can overlap; it must not drive deletion or replacement.
- Re-uploading a corrected BCCT row should create a reviewable correction candidate, not overwrite history automatically.

Duplicate handling differs per module:

- Catalog duplicate key should fail unless duplicate rows are exactly identical and explicitly accepted.
- BCCT duplicate transaction key with identical normalized fields should be a no-op.
- BCCT duplicate transaction key with conflicting normalized fields should become a correction candidate.
- A repeated item code across many BCCT declarations is normal and must not be rejected.

Field typing is risky:

- Customs codes, HS codes, declaration numbers, and line numbers must be preserved as text.
- Excel numeric coercion can corrupt leading zeros.
- Quantity/value fields need decimal normalization but raw cell values must still be preserved.

Reconciliation must not block operational use too aggressively.

- Real BCCT can contain codes missing from DS NVL/DS SP.
- Those should become review warnings and exception buckets, not parser failures by default.

Current app data source is mixed:

- `app/demo_data.py` still seeds catalogs and BCCT in memory.
- BOM now has a file-backed store.
- Catalog/BCCT upload should either create file-backed module stores and merge into `client_context`, or the views will keep showing stale seed data.

## Open Questions

What is the exact workbook schema for DS NVL DK HQ, DS SP DK HQ, and BCCT exports from ECUS/customs?

Confirmed: BCCT uploads are arbitrary filtered exports from customs.
Their coverage can overlap existing system data fully, partially, or not at all.

Confirmed: when a full catalog upload omits an existing code, mark it `inactive_pending_review` and require operator confirmation before retiring it.

For Growatt-like clients, when should `internal_code` become mandatory in DS NVL?

Which BCCT fields are required for CO stock ledger generation beyond the current seed fields:

- declaration number,
- line number,
- item code,
- quantity,
- unit,
- import/export direction,
- customs value,
- declaration date,
- customs office,
- declaration type,
- invoice number,
- origin/country?

Confirmed: CO stock has no source other than import rows.

Confirmed: BCCT corrections should not overwrite an existing transaction key automatically. Create a correction candidate with both old and new retained until reviewed.

Confirmed: clear unit aliases may be normalized, for example `PCS` and `PCE`. A real unit change under the same transaction key must become a correction candidate and cannot be auto-merged into CO stock.

Pending domain confirmation:

- Is `declaration_no` globally unique, or only unique together with `customs_office`, `declaration_type`, and year/date?
- Is `line_no` stable across amendment, cancellation, or re-export workflows?
- If a correction is approved after the old import row was already allocated to an issued C/O, should the ledger create an adjustment, lock the issued allocation, or require manual exception handling?

## Suggested Next Step

Use TDD and implement in this order:

1. Extract shared source-store utilities from BOM store: lock, atomic write, IDs, upload/snapshot/version/audit helpers.
2. Build material catalog upload/versioning with template and duplicate-key rejection.
3. Build product catalog upload/versioning with the same pattern.
4. Build BCCT upload/versioning with arbitrary upload batches, transaction-key diff, correction candidates, and immutable import-row IDs.
5. Add reconciliation warnings between BCCT and catalog versions.
6. Update C/O case snapshot to record selected catalog versions and reviewed BCCT row sets.

Do not start with BCCT allocation logic. First make the source evidence uploadable, versioned, auditable, and selectable.
