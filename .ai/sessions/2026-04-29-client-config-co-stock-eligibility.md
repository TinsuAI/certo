# Session: Client Config And C/O Stock Eligibility

## What Was Done
- Implemented reusable advanced table support for source-like views:
  - `app/table_view.py`
  - `app/templates/_advanced_table.html`
  - `app/templates/catalog_table.html`
- Split Catalog into DS NVL and DS SP child routes and removed the misleading product/catalog rule display from the source catalog flow.
- Added company config:
  - File-backed client config store in `app/client_config_store.py`.
  - Config UI at `/clients/{client_id}/config`.
  - Configurable BCCT import declaration types, relevant export declaration types, C/O stock lot policy, allocation-code strategy, regex, and fallback.
  - Config hash/version snapshot in C/O case source evidence.
- Split BCCT into `/bcct/imports` and `/bcct/exports`.
- Added allocation-code handling for C/O stock:
  - BCCT `item_code` remains customs/audit code.
  - `allocation_code` is the BOM matching key.
  - Growatt defaults to extracting parenthesized codes from BCCT descriptions, with fallback to customs code.
- Changed C/O stock model after user review:
  - Every BCCT import line now becomes a C/O stock candidate.
  - Config no longer filters candidates out of stock.
  - Config marks candidates `active` or `inactive`.
  - Inactive candidates stay visible for audit and have `remaining_qty = 0`.
  - Unresolved/manual-review candidates remain visible but cannot match via `material_code`.
  - Aggregation keeps active/inactive/review-required candidates separate and preserves `source_line_ids`.
- Fixed review findings:
  - Normalize declaration types to uppercase.
  - Map configured import types `E21`, `E23`, and `E31` during direction inference.
  - Apply configured relevant export types to BCCT export view.
  - Normalize common thousands separators like `1,000` before aggregation.
  - Wrap long mono tokens in callouts for mobile layout.

## Decisions Made
- Do not model a global HQ-code/internal-code many-to-many graph yet. For the current C/O workflow, each stock candidate carries its own `allocation_code`; that is enough for BOM matching and audit.
- Do not hard-code Growatt behavior into BCCT parsing. Growatt-specific defaults live in client config.
- Do not provide `aggregate_by_allocation_code`; it loses declaration traceability. The supported aggregate mode is scoped to declaration + allocation code and keeps source line IDs.
- Treat config changes as changes to stock eligibility, not deletion from stock. This keeps historical audit lines visible when declaration types are deactivated.
- Keep inactive/review-required rows in the same C/O stock table for now, controlled by status filters.

## What Didn't Work
- The first implementation filtered non-eligible import declaration types out of `co_stock_rows`. That made Tồn CO change too destructively when config changed and would make later audit harder. It was replaced by candidate-level `eligibility_status`.
- The first review pass exposed that unresolved allocation fallback could make review-required rows look matchable via `material_code`. Review-required rows now keep `material_code` blank.
- The first BCCT mobile screenshot flagged long mono tokens in the callout; CSS now allows callout mono text to wrap.

## Open Items
- Manual browser testing is still needed for the exact user flow:
  - Remove `E15` from config.
  - Confirm E15 stock rows remain visible as `Không dùng`.
  - Add `E15` back.
  - Confirm the same rows become `Khả dụng`.
- Future allocation/consumption logic must only use rows where `eligibility_status == active` and `allocation_code_status == resolved`.
- The export declaration-type config currently affects the BCCT export view; future C/O case export matching still needs design.
