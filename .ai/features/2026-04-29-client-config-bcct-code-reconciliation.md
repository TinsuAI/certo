# Feature: Client Config, BCCT Direction Views, And Allocation Codes

## Scope

Add a per-client configuration layer for C/O evidence processing, then use it to control:

- Which BCCT declaration types count as C/O-eligible import stock.
- Which BCCT declaration types count as relevant exports for C/O case matching.
- How the app resolves a line-level `allocation_code` from BCCT rows for C/O stock/BOM matching.

In scope:

- Split BCCT into first-class import and export child views.
- Add a Client Config page for company-level source-processing settings.
- Keep config file-backed for the demo, similar to current source/BOM stores.
- Use config in CO stock derivation and BCCT source tables.
- For clients like Growatt, support extracting line-level allocation codes from BCCT descriptions.

Out of scope for the first pass:

- Final production database schema.
- Fully automated allocation-code acceptance for ambiguous rows.
- Rewriting existing BCCT transaction identity.
- Legal origin-rule resolution by Form/HS.
- Editing historical BCCT rows.
- Building a general many-to-many customs/internal code relationship graph.
- Reviewing and maintaining company-wide code relationships unless a later workflow needs it.

## Decisions

- Treat declaration-type inclusion as client config, not global code.
- Keep BCCT `direction` inference from declaration type, but use config to decide whether a row is relevant for C/O stock/export matching.
- Default Growatt as a DNCX/EPE-style profile:
  - import C/O stock candidates: `E11`, `E15`
  - export C/O case candidates: `E42`
  - exclude `E13` from stock by default because it is "hàng hóa khác vào DNCX", often tools/assets/other goods rather than production materials.
- Provide configurable presets rather than one hard-coded list:
  - `dncx`: imports `E11`, `E15`; exports `E42`
  - `sxxk`: imports `E31`; exports `E62`
  - `gia_cong`: imports `E21`, `E23`; exports `E52`, `E54`
  - `manual`: no assumption; operator selects codes
- Add BCCT child routes:
  - `/clients/{client_id}/bcct/imports`
  - `/clients/{client_id}/bcct/exports`
  - Keep `/bcct` as upload/overview or redirect to imports.
- Add client config route:
  - `/clients/{client_id}/config`
- Track C/O stock as BCCT line-level stock lots. `allocation_code` is only the BOM matching key, not the stock identity.
- Treat BCCT `item_code` as customs declaration code. For Growatt, this may be a customs grouping code rather than the SKU/BOM code used for allocation.
- Never aggregate stock identity by code alone. The same customs declaration can contain multiple lines with the same `item_code`, and those lines may have different quantities, descriptions, allocation-code hints, origin, invoice data, or allocation history.
- Make stock lot grouping configurable with a conservative default:
  - `line_level`: default; each BCCT import line becomes one stock lot.
  - `aggregate_by_declaration_and_allocation_code`: group only inside the same declaration, allocation code, unit, and origin/status.
  - `manual_review`: rows matching ambiguous grouping patterns require operator review.
- Do not provide an `aggregate_by_allocation_code` mode in v1 because it loses declaration context and weakens audit traceability.
- Resolve each eligible BCCT import row into a stock lot with:
  - immutable BCCT transaction key
  - declaration number and line number
  - customs declaration code
  - allocation code resolved by client policy
  - resolution source and confidence
  - raw description evidence
- Multiple rows with the same declaration number, customs item code, and allocation code must remain separate lots when their BCCT line numbers differ.
- If the configured policy aggregates rows, the derived stock lot must keep `source_line_ids` for every contributing BCCT import line.
- If no allocation code is present in the BCCT description, use a configurable fallback policy such as `same_as_customs_code` or `requires_review`.
- Keep v1 config lightweight:
  - `co_stock_lot_policy`: `line_level`, `aggregate_by_declaration_and_allocation_code`, or `manual_review`
  - `allocation_code_strategy`: `same_as_customs_code`, `description_regex`, or `manual_review`
  - `description_regex` when using regex extraction
  - `allocation_code_fallback`: `same_as_customs_code` or `requires_review`
- Define regex resolution rules explicitly:
  - exactly one regex capture resolves the line
  - zero captures uses the configured fallback
  - multiple captures marks the line `requires_review`
  - invalid regex fails config save
- Do not mutate DS NVL/DS SP rows to force allocation-code semantics. Catalogs remain customs registration evidence.

## Risks

- Changing which BCCT rows are C/O-eligible affects stock counts and case allocation. Existing raw BCCT rows should stay unchanged; only derived views/stock should change.
- Current BCCT transaction key includes `direction + declaration_no + line_no + item_code`; allocation-code resolution should not rewrite `item_code` inside the transaction key.
- A customs declaration code can relate to many allocation codes, and an allocation code may appear under more than one customs code. Do not model this as one-to-one.
- For v1, avoid modeling the full relationship graph. It is not required to make C/O allocation work if every stock lot carries its own `allocation_code`.
- Description-derived allocation codes are strong line-level evidence for Growatt, but the extraction rule remains configurable and should preserve the original description for audit.
- Per-client config can sprawl if every setting is unstructured. Keep it grouped:
  - `bcct`
  - `allocation_code`
  - `co_case_defaults`
  - `source_uploads`
- File-backed JSON is acceptable for demo scale, but config changes must still be versioned or content-hashed.
- C/O cases must snapshot the client config version/hash used for BCCT eligibility and allocation-code resolution; otherwise stock and allocation could change retroactively after config edits.
- Aggregated stock lots must never hide source evidence. Even when rows are grouped for operator convenience, the app must retain declaration number and `source_line_ids` for audit.
- Browser tables still load JSON state in memory. Acceptable for current ~20k BCCT rows, not production scale.

## Open Questions

- Should `E13` ever be allowed into C/O stock for Growatt after review, or should it stay excluded except by explicit manual override per row/type?
- Should domestic purchases under `E15` count as originating/domestic by default, or only as eligible stock requiring origin classification evidence?
- What is the preferred allocation-code regex for Growatt? Current BCCT sample strongly suggests parenthesized codes such as `(920.0038701)`, but this should be configurable and versioned.
- If a row cannot resolve an allocation code, should the app block C/O allocation for that row or allow fallback to customs code with a warning?
- Should export matching use allocation code, customs code, model name, or invoice line?

## Research Notes

- Decision 1357/QD-TCHQ defines `E42` as export of DNCX products; `E11` as DNCX raw material import from abroad; `E15` as DNCX raw material import from domestic/DNCX/FTZ sources; and `E13` as other goods into DNCX.
- Local Growatt BCCT sample distribution:
  - total rows: 19,898
  - imports: 19,369
  - exports: 529
  - declaration types: `E11` 18,456; `E13` 717; `E15` 196; `E42` 529
- Local Growatt BCCT descriptions often embed allocation codes in parentheses. The working assumption from the user is that almost all Growatt BCCT rows include the allocation code in the goods description; if they do not, the allocation code usually matches the customs `item_code`. Sample examples include:
  - `LKN-VO#&... (920.0038701)`
  - `GIAY#&... (047.0003100)`
  - `DIENTRO#&... (001.0000400)`
- This means the safest CO-stock grain is the BCCT declaration line/import row. Customs `item_code` remains part of customs evidence and transaction identity; BOM allocation should use the policy-resolved allocation code. If a client chooses declaration-level aggregation, the lot still stays within one declaration and keeps source line evidence.
- The production DM/BOM side should be treated as using allocation codes. The app does not need a global HQ-NB mapping to allocate stock if BCCT stock lots already carry allocation codes.

## Recommended Implementation Plan

1. Add `client_config_store.py` with defaults, file-backed state, and config version/hash.
2. Add `/clients/{client_id}/config` UI for BCCT include/exclude declaration types, stock lot policy, and allocation-code strategy.
3. Apply config to CO stock derivation: raw BCCT remains complete, derived stock uses eligible import types, configured stock lot policy, and line-level allocation codes.
4. Split BCCT into imports/exports views with active declaration-type chips and excluded-row summaries.
5. Add a generic allocation-code resolver:
   - `same_as_customs_code`
   - `description_regex`
   - `manual_review`
6. Add Growatt defaults for the generic resolver:
   - configurable regex extraction from BCCT descriptions first
   - exact code fallback only when no allocation-code hint is present
   - preserve extraction evidence per BCCT line
7. Add tests around config defaults, BCCT filtering, route split, regex ambiguity handling, line-level allocation-code resolution, stock derivation, aggregation source-line traceability, and config snapshotting.

## Recommendation

Implement this in two TDD slices:

1. Client config + BCCT import/export split + eligible CO stock filtering.
2. Line-level allocation-code resolution for stock lots.

Do not hard-code Growatt behavior into BCCT parsing. Put Growatt-specific defaults in client config and make extraction rules configurable. Defer many-to-many reconciliation UI until it becomes necessary for audit or data cleanup.
