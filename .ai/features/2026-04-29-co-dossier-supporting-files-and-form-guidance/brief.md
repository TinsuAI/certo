# Feature: C/O Dossier Supporting Files And Form Guidance

## Scope

Build a first operational C/O dossier workflow inside the existing FastAPI/Jinja demo:

- A user enters a client workspace and opens or creates a shipment-level C/O dossier.
- Each dossier stores shipment metadata separately from company master data:
  - dossier code/title
  - destination market
  - invoice number
  - bill of lading number
  - selected C/O form
  - selected governing instrument
- Each dossier accepts supporting file uploads for invoice, bill of lading, export declaration, packing list, and other evidence.
- Invoice number is used to search reviewed BCCT export rows and show matching exported products.
- Destination market is used to show candidate C/O forms for the current sprint focus:
  - Form B
  - Form AI
  - Form CPTPP
  - Form EUR.1
- Product HS codes from matched BCCT exports and DS SP catalog rows are used to surface rule-lookup status.
- Generate a criteria/bảng kê view from the currently selected BOM snapshot and existing origin evaluators.
- Export an XLSX evidence workbook for the dossier, including shipment metadata, supporting files, BCCT invoice matches, form guidance, and criteria rows.

Out of scope for this sprint:

- Full OCR or semantic parsing of uploaded PDFs.
- Final production database/auth/deploy choices.
- Automatic eCoSys filing.
- Full per-HS legal rule extraction for all agreements.
- Stock consumption ledger mutation. The dossier may preview required/available data, but must not decrement C/O stock yet.
- General legal advice. The UI must expose sources and review status, not pretend every rule has been legally resolved.

## Decisions

- Keep the implementation file-backed under local-only `data/local/...`, matching BOM/source/config stores.
- Preserve the existing `/clients/{client_id}/co-case` route, but add dossier-aware routes and query selection rather than breaking current tests.
- Add a small C/O dossier store instead of folding dossier state into `demo_data.py`.
- Supporting files are retained as uploaded evidence metadata. The first pass captures invoice/BL numbers from explicit fields and safe filename hints; it does not claim PDF parsing.
- BCCT invoice matching uses normalized invoice text against reviewed/export BCCT rows only. It must respect the existing client config for relevant export declaration types.
- Candidate form guidance is a local, source-backed reference table:
  - Form B: non-preferential/general C/O under `05/2018/TT-BCT`, with later general C/O amendments noted.
  - Form AI: `15/2010/TT-BCT`, ASEAN-India, Form AI, AIFTA rule references.
  - Form CPTPP: `03/2019/TT-BCT`, with CPTPP PSR annex and Form CPTPP.
  - Form EUR.1: `11/2020/TT-BCT` plus `41/2022/TT-BCT` amendment note for EVFTA/EUR.1.
- Use the uploaded `temp/CO-TABLE-FORM.jpg` as an operator matrix signal, but label it as a local matrix source. Prefer local legal corpus entries where available.
- Do not infer the exact legal criterion for an HS code unless the rule text is available in a structured way. For now, show `needs_rule_lookup` when the app has HS/form context but no parsed PSR entry.
- Export XLSX should be practical and audit-friendly, not a pixel-perfect government form yet.

## Risks

- Market-to-form mapping can be wrong if the app treats the image matrix as law. Mitigation: every candidate carries `source_label` and `verification_status`.
- Legal instruments can change. Mitigation: show source issue codes and keep the mapping centralized in a small module for later replacement by a real legal lookup service.
- BCCT invoice references may contain multiple invoice numbers or formatting variants. Mitigation: normalize separators/case and match both exact tokens and full normalized string.
- A dossier could accidentally use correction-candidate BCCT rows. Mitigation: use only published reviewed rows, matching the current source snapshot rule.
- Criteria rows built from BOM are a preview until stock allocation exists. Mitigation: label quantity/stock consumption as preview and avoid mutating stock.
- File-backed JSON is acceptable for demo but not production. The store boundary should make future database migration obvious.

## Open Questions

- Which exact Excel templates must be matched first for Form B, CPTPP, EUR.1, and AI output?
- Should a destination with multiple possible forms require an operator selection before criteria export?
- Should Form B be available as a fallback for every export destination, or only shown under a separate non-preferential lane?
- How should official PSR lookup be populated: parse the local legal corpus into structured rules, or build a curated per-client/per-HS rule table first?
- When stock allocation is implemented, should case creation reserve stock immediately or only when the dossier reaches a reviewed/locked state?

## Recommended Next Step

Implement in TDD slices:

1. Dossier store and route behavior.
2. Supporting upload metadata and invoice-to-BCCT export matching.
3. Form guidance and rule lookup status.
4. Criteria row generation from BOM snapshots and XLSX export.
5. Browser validation and review.
