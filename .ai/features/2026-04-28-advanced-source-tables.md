# Feature: Advanced Source Tables

## Scope

Split the current Catalog page into separate child views and introduce a reusable advanced table pattern for source-heavy modules:

- `Catalog > DS NVL DK HQ`
- `Catalog > DS SP DK HQ`
- `Tồn CO`
- `BCCT`

The feature should replace the current side-by-side catalog panes with focused table pages. It should also make large customs datasets usable after real HQ uploads, especially BCCT files with tens of thousands of rows.

In scope:

- Add child routes for catalog material and product views.
- Keep a Catalog landing/upload page, or redirect `/catalog` to the most useful default child view.
- Add shared table behavior for search, filters, pagination, sorting, and grouping summaries.
- Use server-side query handling for large datasets.
- Preserve existing upload/versioning semantics.
- Remove misleading `Mã nội bộ` display from DS NVL DK HQ until a real ERP/internal-code mapping module exists.

Out of scope:

- Replacing the file-backed stores with a database.
- Editing or accepting correction candidates.
- Building a full spreadsheet-like grid editor.
- Defining final production UX for permissions, saved views, or multi-user collaboration.

## Decisions

- Use server-side pagination/filtering first. Real BCCT samples already have about 20k rows; rendering all rows and filtering in browser will not scale well.
- Build one small table view-model/helper instead of copying table logic across templates.
- Keep Jinja/FastAPI as the implementation layer for now. The app is still a demo shell, and adding a frontend framework only for tables is premature.
- Treat Catalog child views as first-class routes, not only hash anchors:
  - `/clients/{client_id}/catalog/materials`
  - `/clients/{client_id}/catalog/products`
  - `/clients/{client_id}/co-stock`
  - `/clients/{client_id}/bcct`
- Keep advanced controls restrained: compact toolbar above the table, not dashboard cards around the table.
- Default page size should be conservative: 50 or 100 rows. BCCT should not default to all rows.

## Risks

- Query-state complexity can spread across route handlers if not centralized. Pagination, search, sort, and filters should be parsed by one helper.
- Grouping can be expensive if implemented repeatedly over large lists on every request. For demo scale this is acceptable, but the code should make the future database boundary obvious.
- Current source data lives in JSON files under `data/local`. For 20k-row BCCT, loading the module state for every request is tolerable for demo validation but not a production architecture.
- Catalog rows and BCCT rows have different schemas. The shared component should support per-view column definitions rather than assuming one table schema.
- Overbuilding table features now can distract from the more important review workflows: correction candidates and inactive-pending-review catalog rows.

## Open Questions

- Should `/catalog` remain the upload/version landing page, or should it redirect to `/catalog/materials`?
- Which filters are required for first demo validation?
  - DS NVL: code, HS, unit, status, purpose.
  - DS SP: code, HS, unit, purpose.
  - BCCT: declaration type, direction, declaration number, item code, HS, invoice, origin, date range.
  - Tồn CO: material code, declaration number, remaining quantity status.
- Should grouping be interactive in the first pass, or should the first pass only show summary chips such as by direction, declaration type, HS, and status?
- Should table state live only in URL query params, or should saved views be added later?

## Recommended Implementation Plan

1. Add route-level split for Catalog child views and update nav/chips.
2. Create a lightweight table helper that accepts rows, column definitions, and query params, returning paginated rows plus metadata.
3. Apply it to DS NVL and DS SP first, including search and page controls.
4. Apply it to BCCT with server-side pagination, search, direction/type filters, and compact grouping summaries.
5. Apply it to Tồn CO with search, status filter, and pagination.
6. Add focused tests for routes, query behavior, pagination boundaries, and preserving upload/version flows.

## Recommendation

Implement directly, but with tests around the table helper and route behavior before changing templates. This is a standard feature, not a risky architecture decision, as long as it stays file-backed and server-rendered for now.
