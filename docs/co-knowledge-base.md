# CO Knowledge Base

## Scope
This document consolidates the high-signal business and regulatory knowledge needed to reason about the CO domain for this project.

Primary source families:
- local agency files and workbook analysis
- V-Notes wiki under `C:\Users\sys\Dropbox\Obsidian\V-Notes\30_Resources`
- current procedural interpretation from the extracted CO materials

## Core Concepts

### Certificate of Origin
A Certificate of Origin (`C/O`) is issued for a specific export shipment to certify origin status for customs, trade preference, and compliance purposes.

This is not the same as product registration.

The business appears to operate with three layers:
- `Trader profile`
  Registered once on eCoSys for the enterprise.
- `Product-origin evidence`
  BOM, manufacturing process, origin criteria sheets, supplier/manufacturer declarations, and supporting evidence for a product or product family.
- `Shipment C/O application`
  A filing for a specific shipment / lô hàng, using shipment documents plus reusable product-origin evidence where legally allowed.

### eCoSys
`eCoSys` is the current filing platform used for trader registration, document submission, status tracking, and issuance flow.

Operational facts captured from the knowledge base:
- filing is electronic through eCoSys
- digital signature is required
- enterprise profile registration typically takes `6-12` hours or about `1 working day`

### Origin Rules
The main origin-rule families currently relevant to this project are:
- `WO`
- `CTC`
- `RVC`
- `LVC`
- `CTH`
- `CTSH`
- `CC`
- `PSR`

Captured formulas:
- `RVC = (FOB - non-origin material value) / FOB × 100%`
- `LVC = (FOB - CIF value of imported or undetermined-origin inputs) / FOB × 100%`

Imported materials are treated as non-originating in origin calculations, even when duty-exempt.

Observed practical rule behavior from completed dossiers:
- a finished product can still qualify as Vietnam-originating even when many inputs are marked `Không xuất xứ`
- qualification depends on the applicable rule under the applicable agreement, not on all inputs being domestic
- some cases use tariff-shift logic, some use value-content logic, and some use product-specific rules

## Two Registration Layers

### 1. Trader profile registration
This is the first-time enterprise registration on eCoSys / with the issuing system.

Typical inputs:
- enterprise profile
- seal sample
- signature sample of the authorized signer
- business registration information
- tax registration information
- production facility list

Operational meaning:
- this is company-level setup
- it should not be repeated for every shipment

### 2. Shipment-level C/O application
Each shipment / lô hàng requires its own C/O filing.

Typical shipment dossier:
- application form
- C/O form
- export customs declaration
- invoice
- packing list
- bill of lading or equivalent transport document
- origin criteria sheet
- manufacturing process summary
- BOM
- import declaration evidence for imported inputs
- domestic input evidence / supplier declarations

Operational meaning:
- C/O is issued per shipment
- but product-origin evidence may be reused across shipments when the legal conditions are met

## Reuse Of Product-Origin Dossier

### Fixed product behavior
For a fixed product / stable product line, the business does not appear to rebuild the full origin dossier for every shipment.

Practical interpretation from the legal/procedural material:
- first filing for a new or newly exported product requires the full dossier
- subsequent filings for the same fixed product can reuse the product-origin evidence
- shipment-specific documents still need to be submitted for each shipment

### Evidence validity
The product-origin evidence set has a reuse window.

The key reusable materials are:
- detailed origin criteria declaration
- manufacturer or supplier origin declaration
- production process documentation

These are treated as reusable for a limited period, commonly captured in the legal procedure as `2 years`, unless the underlying facts change.

Operational meaning:
- the future system should store:
  - shipment-specific documents
  - reusable product evidence
  - validity period and version history of that evidence

## Filing Modes

### Electronic forms
Electronic forms are uploaded and processed in eCoSys.

Typical timing:
- around `3` days for general goods
- around `7` days for electronics

### Paper forms
Paper forms still matter operationally for some form families.

Typical timing:
- around `1` working day

The system should not assume “electronic filing” means “no paper artifacts”.

## Roles In The Current Process

### Import-export team
- determine form type
- prepare export-side dossier
- collect customs and shipping documents
- hand off to the compliance operator

### Accounting / operations
- build and maintain BOM / định mức
- maintain invoice and internal source evidence
- support value and cost proof

### Consultant / compliance operator
- validate dossier completeness
- advise on first-time registration and form choice
- complete rule-specific evidence sheets
- package the filing
- manage issuance updates and archive

### Issuing authority
- review filing
- request supplement or clarification
- issue, reject, or inspect

## Record Retention
The knowledge base indicates a `5-year` retention expectation for C/O-related evidence and trade/origin records.

Operational meaning:
- the future system must treat archive and audit traceability as core features

## Design Implications

### The domain is not only document storage
The system must represent:
- enterprise registration
- shipment filing
- product-origin evidence reuse
- origin-rule evaluation
- traceability to import and domestic input history
- compliance archive

### Suggested first-class entities
- Company
- TraderProfile
- ProductionFacility
- Product
- ProductOriginEvidence
- ProductOriginEvidenceVersion
- Shipment
- ShipmentDocument
- COCase
- COFormType
- OriginRuleEvaluation
- FilingSubmission
- IssuedCO
- AuditRecord
