# BOM Builder Foundation

This note extracts the reusable BOM lessons from the active Growatt case so the first BOM Builder module can start before that case is fully closed.

It is intentionally narrow.
The goal is to capture what is already stable enough to design and build now, while keeping Growatt-specific CO execution logic out of BOM Builder v1.

## Purpose

The BOM Builder should own the product-evidence side of the workflow:
- ingest client-provided technical BOMs
- preserve source rows and identifiers
- support operator review and curation
- publish a stable BOM version that later CO workflows can consume

It should not own shipment allocation, stock deduction, replacement optimization, or origin pass/fail decisions.

## Delivery Shape

The first implementation should separate the BOM engine from the eventual web UI:
- a file-backed import and normalization core
- operator review and publish workflow on top of that core

This split matters because the hard problem is source fidelity, versioning, and review semantics, not the initial UI shell.

The module should preserve at least these artifact layers:
- raw uploaded file
- parsed BOM snapshot
- reviewed or published BOM version

Flattened or rollup outputs can be derived from a published BOM version, but they should not replace the raw and parsed layers.

## Stable Common Rules

### 1. BOM identity is not `one product code = one BOM`
- Keep these layers separate:
  - `export_product_code`
  - `bom_code`
  - `bom_variant_id`
- Preserve suffix BOM codes exactly as observed.
- Treat each contiguous BOM block as a separate `bom_variant_id`.
- Do not collapse repeated exact-code blocks into one BOM unless an operator explicitly confirms they are the same.

### 2. Preserve source fidelity end to end
- Keep imported codes and identifiers in text form.
- Do not allow spreadsheet parsing to silently coerce codes into numeric values.
- Preserve raw imported rows alongside normalized rows.
- Keep an audit trail for every normalization or operator edit.

### 3. Duplicate rows are a review problem, not an auto-merge problem
- Repeated material rows inside one BOM block must stay visible.
- Repeated BOM blocks for the same product code must stay visible.
- BOM Builder should surface these situations for operator review instead of silently deduplicating them.

### 4. Review and publish are first-class workflow steps
- The module should follow:
  - import
  - normalize
  - review
  - publish
- Operators need explicit review actions before a BOM becomes reusable evidence.
- Published BOMs should become stable versions, not mutable spreadsheet snapshots.

### 5. Technical BOM is the safe v1 source
- Start with client/factory technical BOM files as the primary source.
- ERP movement data can later enrich or reconcile the BOM, but it should not be the first dependency for v1.
- When multiple source files disagree, BOM Builder should support curated resolution rather than pretending one automatic merge is trustworthy.

### 6. BOM evidence is separate from stock and allocation
- BOM Builder owns product structure and curated material evidence.
- CO stock, import admissibility, allocation history, and shipment consumption belong to downstream CO logic.
- Physical inventory and CO-eligible stock should remain separate concepts.

### 7. Raw-file identity is separate from BOM-family identity
- The system should detect binary-identical uploads and avoid creating fake new versions.
- The system should still allow different files to belong to the same BOM family.
- File fingerprinting, parsed BOM identity, and published BOM version should remain separate concepts.

## Growatt-Specific Or Downstream Logic

The following lessons came from Growatt, but they should stay out of BOM Builder v1:

- shipment order and cross-shipment stock effects
- stock-age admissibility rules
- import-line confirmation and shared normalized stock ledgers
- replacement optimization and substitute-material ranking
- stop-after-pass logic such as “stop using substitute stock once a product first reaches stock sufficient + RVC threshold”
- shipment-level scenario search and product-order optimization
- RVC, CTSH, PSR, or other origin-rule pass/fail evaluation

These are valid CO engine concerns, but they should consume published BOM versions rather than live inside the BOM Builder itself.

## V1 Implementation Boundary

BOM Builder v1 should do:
- import Excel or CSV technical BOMs
- preserve raw rows and exact codes
- fingerprint uploaded files
- generate normalized review rows
- flag duplicate rows, duplicate blocks, missing codes, and unit mismatches
- let operators curate and publish a BOM version

BOM Builder v1 should not do:
- synthesize BOM from ERP transactions
- allocate stock to shipments
- infer origin status
- run replacement planning
- optimize across products or shipments

## Why This Split Matters

The active Growatt case showed two kinds of failure that the future module should avoid:
- false certainty from auto-merging duplicate or conflicting BOM inputs
- accidental coupling between BOM curation and downstream shipment-calculation logic

Starting with this narrower boundary allows the BOM Builder to ship now, while the Growatt case continues to refine the later CO engine layers.

## Current Source Assumptions

- `JOHNSON` currently looks like a stable SAP-export family and is a good first importer target.
- `GROWATT` is still a mixed-source family and should be modeled as curated BOM evidence, not as one automatically trusted workbook.
- Technical BOM import is the correct v1 source lane.
  SAP movement-derived BOM remains a later reconciliation or enrichment path.

See `docs/company-bom-source-lessons.md` for the current source profiles and aggregate findings from the BOM Builder worktree.
