# BOM Builder Implementation Plan

This plan defines how to implement BOM Builder inside the CO app.
It is scoped to client-level BOM evidence management, versioning, comparison, and traceability.

## Goal

BOM Builder should let agency staff manage BOM evidence per company and per product:

- configure which BOM importer a company uses
- upload BOM files directly from staff-maintained Excel sheets
- upload technical BOM files from client/factory systems
- parse uploaded files without losing source fidelity
- compare a new upload against the latest accepted BOM version
- avoid creating a new version when nothing materially changed
- create the next version when there are material changes
- preserve raw files, parsed rows, diffs, decisions, and published versions for audit

BOM Builder does not decide C/O origin qualification.
The C/O case module consumes a reviewed or published BOM version and combines it with CO stock, BCCT, customs catalogs, and origin rules.

## Core Concepts

### Company BOM Configuration

Each company needs a BOM configuration record.

Fields:

- `client_id`
- `bom_profile`: `manual_flat`, `growatt_multi_workbook`, `johnson_sap_exploded`
- `default_import_mode`: `direct_bom` or `technical_bom`
- `code_system_mode`: `single_code`, `customs_internal_mapping_required`
- `published_version_policy`: currently one published version per product/BOM family
- `diff_policy_id`
- `created_at`, `updated_at`

Initial profiles:

- `manual_flat`: staff-maintained Excel shaped like current workbook DM/BOM sheets.
- `growatt_multi_workbook`: finished-product workbook plus BTP workbook graph, flattened to leaf components.
- `johnson_sap_exploded`: SAP WebAS exploded BOM export with hierarchy levels and cumulative component quantity.

### BOM Family

A BOM family groups versions that represent the same product/BOM identity.

Fields:

- `bom_family_id`
- `client_id`
- `export_product_code`
- `bom_code`
- `bom_variant_id`
- `profile`
- `status`: `active`, `archived`, `needs_review`
- `created_at`, `updated_at`

Important rule:
Do not assume `one product code = one BOM`.
Keep `export_product_code`, `bom_code`, and `bom_variant_id` separate.

### BOM Upload

Every upload must be kept even if it does not create a new version.

Fields:

- `bom_upload_id`
- `client_id`
- `uploaded_by`
- `original_filename`
- `content_sha256`
- `file_size`
- `storage_path`
- `profile_used`
- `upload_mode`: `direct_bom`, `technical_bom`
- `parse_status`: `pending`, `parsed`, `failed`
- `parse_error`
- `created_at`

If `content_sha256` matches an existing upload for the same client, mark it as duplicate upload and do not parse again unless forced.

### Parsed BOM Snapshot

Parsed snapshot is immutable output from an upload.
It preserves source rows and source identities.

Fields:

- `bom_snapshot_id`
- `bom_upload_id`
- `client_id`
- `profile`
- `parser_version`
- `normalized_hash`
- `row_count`
- `leaf_row_count`
- `material_candidate_row_count`
- `validation_summary`
- `created_at`

Snapshot rows should preserve:

- raw source row payload
- source workbook / sheet / row number
- source path or hierarchy path
- parent code
- component code
- component description
- quantity
- unit
- branch/leaf classification
- material-candidate classification
- parser warnings

### BOM Version

A BOM version is the accepted curated version for a BOM family.

Fields:

- `bom_version_id`
- `bom_family_id`
- `client_id`
- `version_no`
- `source_snapshot_id`
- `previous_version_id`
- `status`: `draft`, `reviewed`, `published`, `superseded`, `rejected`
- `version_hash`
- `effective_from`
- `effective_to`
- `created_by`
- `reviewed_by`
- `published_by`
- `created_at`, `reviewed_at`, `published_at`

Publishing a new version supersedes the previous published version for the same BOM family.
The old version remains immutable and traceable.

### BOM Diff

Diff compares the new parsed snapshot against the latest accepted version for the same BOM family.

Diff buckets:

- `unchanged`
- `added_component`
- `removed_component`
- `quantity_changed`
- `unit_changed`
- `description_changed`
- `path_changed`
- `source_only_change`
- `classification_changed`
- `needs_review`

Diff identity key should be profile-aware.
Default comparison key:

- `export_product_code`
- `bom_code`
- `leaf_component_code`
- `normalized_unit`

Johnson may include `source_workbook` in the comparison key because each workbook is currently a practical product identity.
Growatt may need graph-derived leaf identity plus source path metadata because BTP expansion can change paths without changing final leaf consumption.

## Upload Flow

### Direct BOM Upload

Use this for staff-maintained flat BOM Excel, similar to the DM/BOM sheets in the current workbook.

Flow:

1. User opens `Company -> BOM -> Upload`.
2. User chooses `Direct BOM`.
3. System stores raw file and computes `content_sha256`.
4. Parser reads configured flat-BOM columns.
5. System creates immutable parsed snapshot.
6. System resolves or creates BOM families by product/BOM code.
7. System compares snapshot rows against latest accepted version.
8. If no material change exists, upload is marked `parsed_no_change`; no new version is created.
9. If material change exists, system creates draft version candidate.
10. User reviews diff and accepts or rejects.
11. Accepted candidate becomes next version and can be published.

### Technical BOM Upload

Use this for supplier/factory technical BOM files.

Flow:

1. User opens `Company -> BOM -> Upload`.
2. User chooses `Technical BOM`.
3. System selects importer from company BOM config.
4. System stores raw file and computes `content_sha256`.
5. Parser creates immutable snapshot with source rows and hierarchy metadata.
6. Profile-specific normalization creates flattened/material-candidate rows.
7. System compares normalized output against latest accepted version.
8. If no material change exists, upload is retained as evidence but does not create a new version.
9. If material changes exist, system creates a draft version candidate with diff report.
10. User reviews validation warnings, row diffs, and source paths.
11. User accepts, rejects, or marks rows for manual resolution.
12. Accepted candidate becomes next version and can be published.

## Profile-Specific Parsing

### Manual Flat BOM

Expected input:

- one workbook or sheet containing product/BOM/material rows
- product code
- material code
- material description
- quantity
- unit
- optional waste/scrap rate
- optional effective date/version label

Parser behavior:

- preserve raw cells as text
- do not coerce material codes into numbers
- flag missing product/material/quantity/unit
- aggregate only after preserving source rows
- treat duplicate rows as review signals

### Growatt Multi-Workbook BOM

Expected input:

- finished-product BOM workbook family
- BTP/semi-finished BOM workbook family
- Chinese SAP/ERP-style headers

Parser behavior:

- build parent/component graph
- choose exact-code BTP workbook candidates where available
- detect cycles and fail fast
- flatten recursively to leaf components
- aggregate repeated leaf components per product/component/unit/source profile
- preserve sample paths and path counts
- compare against DS NVL DK HQ as reconciliation evidence, not as absolute truth

Review signals:

- unresolved parent components
- only-in-technical-BOM components
- only-in-DS-NVL components
- quantity deltas against registered/customs list
- alternate component groups and priority fields

### Johnson SAP Exploded BOM

Expected input:

- SAP WebAS exported workbook
- one `Sheet1`
- SAP-style columns including `Level`, `Explosion level`, `Component number`, `Component quantity`, `Comp. Qty (CUn)`, `Revision Level`, `Change Number`

Parser behavior:

- reconstruct hierarchy from row order and level fields
- validate `Level` against `Explosion level`
- fail on invalid hierarchy jumps
- use `Comp. Qty (CUn)` as default flattened quantity when present
- compute hierarchy-multiplied quantity as validation
- classify structural leaves separately from material-candidate leaves
- preserve line-level `Revision Level` and `Change Number`

Review signals:

- quantity deltas over tolerance
- bulk material rows
- base-unit/component-unit mismatch
- duplicate display paths
- document-like leaves filtered out of material candidates

## Versioning Rules

### No-Change Upload

If normalized new snapshot hash equals latest accepted version hash:

- keep upload record
- keep parsed snapshot if not already present
- mark comparison result as `no_material_change`
- do not create a new BOM version
- show user: "File parsed successfully. No material BOM change detected."

### New Version Candidate

Create draft version candidate when:

- leaf component added or removed
- normalized quantity changed beyond tolerance
- unit changed
- product/BOM family changed
- importer profile changed output materially
- operator explicitly requests new version despite low-level source-only change

### Source-Only Change

Do not automatically create a new BOM version when only these change:

- uploaded file name
- source row order with identical normalized output
- workbook metadata without normalized row change
- formatting-only spreadsheet changes

Keep these as upload/audit events.

### Manual Override

Operator can force:

- create version despite `no_material_change`
- reject candidate despite material diff
- mark a row diff as accepted exception
- map unresolved component to registered material code

Every override must write audit log with actor, timestamp, reason, and affected rows.

## Audit And Traceability

Audit must answer:

- Who uploaded the file?
- Which raw file was uploaded?
- Which parser/profile processed it?
- What rows were parsed?
- What changed versus previous version?
- Who accepted or rejected the diff?
- Which BOM version was published?
- Which C/O case consumed which BOM version?

Audit events:

- `bom.uploaded`
- `bom.upload.duplicate_detected`
- `bom.parse.started`
- `bom.parse.failed`
- `bom.parse.completed`
- `bom.diff.completed`
- `bom.version_candidate.created`
- `bom.version_candidate.rejected`
- `bom.version.reviewed`
- `bom.version.published`
- `bom.version.superseded`
- `bom.row.override_applied`
- `bom.mapping.updated`
- `co_case.bom_version_attached`

## UI Plan

### Company BOM Config View

Location:
`/clients/{client_id}/bom/config`

Controls:

- BOM profile selector
- default upload mode
- code system mode
- diff tolerance
- importer-specific options

Initial profiles:

- Manual flat BOM
- Growatt multi-workbook BOM
- Johnson SAP exploded BOM

### BOM Versions View

Location:
`/clients/{client_id}/bom`

Sections:

- active published versions by product/BOM family
- latest uploads and parse status
- draft candidates pending review
- source profile summary

### Upload View

Location:
`/clients/{client_id}/bom/upload`

Controls:

- upload mode: direct BOM or technical BOM
- file upload
- optional product/BOM family hint
- parse button

Result states:

- parse failed
- duplicate file
- no material change
- draft version candidate created

### Diff Review View

Location:
`/clients/{client_id}/bom/uploads/{upload_id}/diff`

Sections:

- summary counts by diff bucket
- added/removed/changed rows
- source row evidence
- validation warnings
- accept/reject/force-version actions

### Version Detail View

Location:
`/clients/{client_id}/bom/versions/{version_id}`

Sections:

- version metadata
- source upload and snapshot
- published rows
- source row lineage
- audit timeline
- C/O cases consuming this version

## API/Route Plan

Initial server-rendered routes:

- `GET /clients/{client_id}/bom`
- `GET /clients/{client_id}/bom/config`
- `POST /clients/{client_id}/bom/config`
- `GET /clients/{client_id}/bom/upload`
- `POST /clients/{client_id}/bom/upload`
- `GET /clients/{client_id}/bom/uploads/{upload_id}`
- `GET /clients/{client_id}/bom/uploads/{upload_id}/diff`
- `POST /clients/{client_id}/bom/uploads/{upload_id}/accept`
- `POST /clients/{client_id}/bom/uploads/{upload_id}/reject`
- `GET /clients/{client_id}/bom/versions/{version_id}`
- `POST /clients/{client_id}/bom/versions/{version_id}/publish`

Later API routes can mirror these for asynchronous parsing.

## Storage Plan

V1 can stay file-backed while the app is still demo/prototype:

```text
data/local/bom-builder/
  clients/{client_id}/
    uploads/{upload_id}/raw/{original_filename}
    uploads/{upload_id}/upload.json
    snapshots/{snapshot_id}/snapshot.json
    snapshots/{snapshot_id}/rows.jsonl
    diffs/{diff_id}/diff.json
    versions/{bom_family_id}/v{version_no}/version.json
    versions/{bom_family_id}/v{version_no}/rows.jsonl
    audit/audit.jsonl
```

Database migration can later map directly from these artifacts:

- `bom_company_config`
- `bom_family`
- `bom_upload`
- `bom_snapshot`
- `bom_snapshot_row`
- `bom_diff`
- `bom_diff_row`
- `bom_version`
- `bom_version_row`
- `bom_audit_event`
- `co_case_bom_version`

## Implementation Phases

### Phase 1: File-Backed Foundation

Build:

- local artifact store
- upload record with SHA-256 fingerprint
- manual flat BOM parser
- normalized hash comparison
- no-change detection
- draft version creation
- audit event writer
- basic BOM versions screen

Acceptance:

- uploading the same file twice does not create a new version
- uploading a changed flat BOM creates `v2` candidate
- accepted candidate is traceable to raw upload and previous version

### Phase 2: Technical BOM Profiles

Build:

- company BOM config UI
- Growatt parser profile from existing BOM Builder logic
- Johnson parser profile from existing BOM Builder logic
- validation summary storage
- source path lineage display

Acceptance:

- Growatt upload can flatten across finished/BTP BOM sources
- Johnson upload can parse SAP hierarchy and material-candidate leaves
- validation warnings are visible before acceptance

### Phase 3: Diff Review Workflow

Build:

- row-level diff buckets
- grouped diff review screen
- accept/reject/force-version actions
- manual row override reasons
- version publish/supersede workflow

Acceptance:

- operator can explain every new version from a diff report
- rejected upload remains visible but does not affect published version
- published version is immutable

### Phase 4: C/O Case Integration

Build:

- attach BOM version to C/O case product
- snapshot BOM version into case evidence
- show version lineage in C/O case
- prevent silent mutation of case BOM after filing/export

Acceptance:

- C/O case references exact BOM version ID
- if company BOM changes after case creation, existing case remains tied to old version unless user explicitly updates it
- export evidence includes BOM version metadata

## Immediate Next Slice

Implement the smallest useful vertical slice:

1. Add file-backed `bom_store`.
2. Add manual flat BOM upload route.
3. Parse direct BOM sheet into normalized rows.
4. Compare normalized hash against latest accepted version.
5. Show `no change` or `version candidate created`.
6. Accept candidate into `v1`, `v2`, etc.
7. Show audit timeline on BOM version detail.

Do this before porting the full Growatt/Johnson parsers into the app.
That keeps the versioning and audit contract stable before source-specific parser complexity arrives.
