# Feature: Shared Company Portfolio For BCQT And C/O

## Scope

Build a shared company-portfolio system that manages reusable client evidence used by both BCQT-System and the C/O workflow.

The portfolio owns:

- Clients and company profile metadata.
- Registered customs catalogs:
  - materials / NVL,
  - finished products / SP / TP,
  - semi-finished products / BTP, needed by BCQT and ignored by C/O unless a product BOM references it.
- BCCT / customs declaration line evidence.
- BOM evidence, including technical uploads, product-level versions, and aggregate BOM versions.
- Client processing config for shared source interpretation:
  - declaration type inclusion,
  - allocation-code strategy,
  - code-system mode,
  - parser/source profile.
- Shared derived read models:
  - BCCT invoice index,
  - C/O stock candidate lots,
  - portfolio summaries and counts,
  - version metadata for snapshotting.

The portfolio does not own:

- C/O dossiers, shipment workflow, supporting case files, form selection, PSR/legal-rule decisions, or origin evaluation output.
- BCQT settlement runs, Mẫu 15/15a/16 output, findings produced by BCQT-specific checks, or NXT/ERP project computation.
- Final stock reservation/consumption ledgers until the C/O allocation workflow is explicitly designed.

Both C/O and BCQT should call the portfolio for source evidence and snapshot references, then keep their own workflow state and outputs.

## Current-System Findings

BCQT-System is stronger for operational shell and catalog governance:

- It already has `clients` and yearly `projects` in SQLite app/project DBs.
- `material_registry` is the canonical catalog with `nvl`, `btp_sx`, `btp_nm`, `tp`, and `ccdc` categories.
- DS NPL/SP/BTP upload has preview/confirm, conflict resolution, soft discontinue/restore, inheritance from prior year, and CSV/XLSX export.
- BCCT is parsed into `customs_declarations`; resolution treats BCCT `material_code` as customs code and validates it against the registry.
- BOM is not implemented yet; M7 plans `bom_entries`, `settlement_norms`, BOM upload/flattening, and Mẫu 16.

C/O is stronger for source evidence versioning and BOM concepts:

- `source_store.py` keeps file-backed source modules for material catalog, product catalog, and BCCT with raw uploads, immutable parsed snapshots, published versions, and correction candidates.
- `bom_store.py` already models BOM config, upload profiles, product-level BOM versions, aggregate BOM versions, snapshots, raw files, and diffs.
- Client config already has version/hash semantics for declaration-type filters, C/O stock lot policy, and allocation-code extraction.
- C/O stock is correctly derived from BCCT import rows plus client config; it is not a standalone source file.
- Postgres exists as a read-model/index for BCCT, invoice matching, C/O stock, and source metadata, while JSON remains the current source of truth.

The two systems are complementary. The shared portfolio should not copy one implementation wholesale.

## Decisions

- Treat this as a separate bounded context: `Company Portfolio` or `Source Portfolio`.
- Use `client` as the common top-level term. BCQT yearly projects and C/O dossiers are consumer workspaces under a client.
- Preserve source semantics. Do not collapse DS NVL, DS SP, BTP, BCCT, and BOM into one generic item table:
  - catalogs are reference/master evidence,
  - BCCT is transaction evidence,
  - BOM is product-structure evidence.
- Use PostgreSQL as the portfolio system of record when the portfolio becomes a shared service. Large BCCT tables and two consumers make file JSON or per-project SQLite the wrong long-term source of truth.
- Keep raw uploaded files outside relational rows but store immutable metadata, hashes, source row references, and parsed snapshots.
- Every upload creates an audit trail even if it produces no new published version.
- BCCT identity should be a stable transaction key, at minimum: `direction + declaration_no + line_no + item_code`. Corrections create review candidates, not silent overwrites.
- Catalog identity should be explicit by source type:
  - material/NVL: customs code plus optional internal/allocation mapping,
  - product/SP/TP: product customs code,
  - BTP: catalog category plus product-structure use.
- BOM identity should keep product code, BOM code, BOM variant, product-version ID, and aggregate-version ID separate. Do not assume one product code has exactly one BOM.
- C/O and BCQT consumers must snapshot portfolio versions/config hashes when they start a meaningful workflow:
  - C/O dossier snapshots catalog versions, BCCT reviewed row set, BOM version, and client config hash.
  - BCQT settlement run snapshots catalog, BCCT, BOM/NXT inputs, config, and run parameters.
- Postgres read models should remain query-oriented and rebuildable. Promote hot query fields to columns and keep full row payloads only where it supports audit or compatibility.

## Portfolio API / Contract Shape

Initial contracts should be written before implementation:

- `Clients`
  - create/update/list client profiles,
  - expose profile fields needed by both apps.
- `Source uploads`
  - upload raw file,
  - parse preview,
  - confirm/cancel,
  - expose upload, snapshot, version, and diff metadata.
- `Catalogs`
  - list/search/page material/product/BTP rows,
  - upload DS files,
  - resolve conflicts,
  - soft discontinue/restore,
  - expose current and historical versions.
- `BCCT`
  - upload and parse customs declaration rows,
  - query by declaration, line, item, invoice, HS, declaration type, direction,
  - expose correction candidates and reviewed row sets.
- `BOM`
  - configure source profile per client,
  - upload technical/direct BOM files,
  - publish product versions and aggregate BOM versions,
  - query BOM by product and effective version.
- `Client config`
  - read/write source-processing config with `config_version` and `config_hash`.
- `Derived views`
  - invoice-to-export-BCCT lookup for C/O,
  - C/O stock candidate lots,
  - BCQT material/product universe views,
  - source summary counts/version metadata.
- `Snapshots`
  - create immutable `portfolio_snapshot_id` containing selected module versions and config hashes for a consumer workflow.

## Risks

- A shared portfolio can become a dumping ground if it absorbs C/O or BCQT workflow state. Keep source evidence and workflow outputs separate.
- Moving to a service too early can slow the demo if API contracts are not stable. Start with a written contract and a thin adapter layer before rewriting both apps.
- BCQT currently uses per-project SQLite. If it keeps computed settlement state in SQLite while portfolio uses Postgres, the integration boundary must be explicit and snapshot-based.
- CO currently has file-backed JSON source modules. A direct migration to Postgres source-of-truth must preserve raw uploads, parsed snapshots, version history, and fallback/export artifacts.
- BOM is not mature in BCQT-System and only demo-grade in C/O. The portfolio schema should support BOM versions, but final BOM flattening rules should evolve behind parser profiles.
- BTP is BCQT-critical but C/O-optional. The data model must allow C/O consumers to ignore BTP without losing BOM graph integrity.
- C/O stock is a derived eligibility view, not physical inventory. It must not be confused with BCQT balances or ERP/NXT stock.
- Corrections after a C/O dossier or BCQT settlement has been issued create audit-adjustment questions. Snapshot immutability is mandatory.

## Open Questions

- Should the portfolio be a standalone repo/service immediately, or first a shared package/module with a service-shaped interface?
- Should BCQT-System migrate catalog/BCCT data out of per-project SQLite, or keep local project DB snapshots copied from portfolio?
- What is the canonical deployment topology: one portfolio per agency deployment, or one central Tinsu AI-hosted portfolio serving multiple agency deployments?
- Which source data is truly client-level versus year/period-level?
  - Catalog and BOM are usually client-level with versions.
  - BCCT is transaction/period evidence and may be uploaded in arbitrary overlapping batches.
  - BCQT NXT/ERP remains project/year-specific for now.
- How should code mappings and unit conversions be shared?
  - They are clearly reusable between years and BCQT projects.
  - C/O may need allocation-code mapping but not the full BCQT unit-conversion model in v1.
- Should portfolio own a generic findings/annotations subsystem, or should each consumer keep its own findings and only attach notes to portfolio rows?

## Recommended Implementation Path

1. Confirm the strategic direction: shared portfolio bounded context with Postgres source-of-truth and snapshot contracts.
2. Write the portfolio API/schema contract before implementation. Keep it small and source-evidence focused.
3. Build the portfolio schema around source uploads, catalogs, BCCT, BOM versions, client config, and snapshots.
4. Move the C/O app first because its source-store/BOM/versioning concepts are already closer to the target, and C/O already has Postgres index code.
5. Add a BCQT adapter that can read portfolio catalogs/BCCT into project-specific settlement runs without moving settlement computation yet.
6. Only after both consumers read from the portfolio should write paths be consolidated and old local stores retired.

Do not start by merging the two apps. Start by extracting the shared evidence boundary and making both apps consume it through explicit contracts.
