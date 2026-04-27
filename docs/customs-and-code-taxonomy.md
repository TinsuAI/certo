# Customs And Code Taxonomy

This note captures the domain assumptions that affect BOM import, material identity, customs reconciliation, and later CO calculation.

## Customs-Side Sources

The current project works with at least three customs-side source families:
- `BCCT`: transaction rollup of import and export declarations
- `DS NVL DK HQ`: customs registration master for materials and inputs
- `DS SP DK HQ`: customs registration master for finished goods

These are operational exports from the customs or ECUS side, not ERP-native master data.

## Reliability Assumption

The registration masters are intended to be exhaustive.
In theory, any code that appears in `BCCT` should already exist in either `DS NVL DK HQ` or `DS SP DK HQ`.

In practice, the system must tolerate exceptions:
- unregistered codes that still appear in transaction data
- inconsistent descriptions
- late or incomplete registration maintenance

For that reason, `DS NVL` and `DS SP` should be treated as strong evidence, not as an infallible validation oracle.

## Code Systems

Some clients use one code system.
Others use separate customs-facing and ERP or internal codes.

### Johnson

Current working assumption:
- customs code and internal code usually match

This makes direct BOM-to-customs reconciliation simpler unless later evidence contradicts it.

### Growatt

Current working assumption:
- customs code and internal or ERP code often differ
- descriptions frequently carry both identities

This means the product must support code reconciliation instead of assuming one canonical code from the start.

## Material Classification Is Multi-Axis

A single `NVL/BTP/TP` label is not enough.
The same code can behave differently depending on accounting, customs, production, and sourcing context.

The future system should support at least these parallel classification axes:
- `accounting_class`: `NVL`, `BTP`, `TP`, or other bookkeeping-oriented roles
- `customs_role`: `NPL`, `SP`, or unknown from the customs perspective
- `movement_behavior`: imported by PO, consumed into production, produced by production, exported as product, and similar operational signals
- `source_type`: internally produced, externally purchased, or both

This is necessary because some codes can be:
- internally produced semi-finished goods
- externally purchased semi-finished goods
- export-facing finished goods
- black-box imported modules with no exploded child BOM in the technical source set

## Design Implications

- BOM import should preserve both raw codes and normalized code mappings.
- Reconciliation logic should allow `customs_code`, `internal_code`, and `description-derived hints` to coexist.
- Validation should distinguish between:
  - registered and matched
  - present in transactions but missing from registration masters
  - unresolved code mapping
- Product and material master design should allow one code to carry multiple roles instead of forcing one permanent bucket.
