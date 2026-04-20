# CO Legal Lookup System

## Purpose
This document defines how the legal corpus mirrored from eCoSys should be organized into a lookup system that supports the future CO workflow.

It is not a legal memo for one document.
It is the retrieval and integration model for the whole corpus.

Important scope clarification:
- `eCoSys` is the discovery feed for this corpus
- the mirrored files are provenance artifacts
- the future lookup system should run on resolved canonical text sources, not directly on raw PDF or office-file extraction

## Current Corpus
As of `2026-04-20`, the local eCoSys mirror contains `71` legal and procedural items under `data/legal/official-mirror/ecosys/`.

Current high-volume groups seen on the official page:
- `Văn bản pháp luật chung về C/O`: `18`
- `Form E`: `6`
- `Form D`: `5`
- `Form AK`: `5`
- `C/O qua Internet`: `5`
- several other FTA/form groups with smaller counts

The generated lookup entry point is:
- [eCoSys Legal Mirror Index](../indexes/ecosys-documents.md)
- [Legal Text Source Registry](../indexes/text-source-registry.md)

Source policy for this corpus:
- `discovery-first`: use the eCoSys listing to detect and mirror in-scope documents
- `official-text-first`: prefer official text-based sources for canonical legal text
- `TVPL fallback`: use `Thư Viện Pháp Luật` as an internal digitalized lookup layer when official text-based sources are not yet resolved
- `binary-secondary`: mirrored PDFs and office files remain secondary provenance artifacts

## Why The Lookup System Is Needed
The CO workflow does not need “all legal documents” in one flat list.
It needs to answer a small number of operational questions quickly:

1. Which documents govern `issuance`, `amendment`, `withdrawal`, `retention`, and `delegation` in the current period?
2. Which documents govern `origin rules` for the chosen agreement or C/O form?
3. Which document is the `current effective version`, and which older documents are only background or amendment history?
4. Which forms, appendices, declarations, and evidence templates are required in the current process?
5. Which legal rules should drive the future system’s:
   - filing workflow
   - rule engine
   - document checklist
   - audit trail

## Lookup Layers

### 1. Common CO governance
This layer answers questions about the general legal framework for origin, issuance, authority, and process.

Current anchor documents in the mirrored corpus:
- `31/2018/NĐ-CP`
- `05/2018/TT-BCT`
- `23/2025/TT-BCT`
- `40/2025/TT-BCT`

Typical use:
- define baseline concepts
- define issuance and management process
- define general origin framework
- define how later form-specific rules sit on top

### 2. Agreement / form-specific origin rules
This layer answers questions like:
- what is the governing rule set for `Form D`, `Form AK`, `Form EUR.1`, `Form RCEP`, `Form VK`, and so on
- which amendment chain is currently effective for that form
- which appendices or PSR tables belong to that rule set

This is the layer the rule engine will depend on most directly.

### 3. Electronic filing and internet issuance
This layer covers:
- `C/O qua Internet`
- electronic forms
- delegated digital procedures
- online issuance and operational requirements

This is the layer the future filing workflow and status tracking must consult.

### 4. Self-certification and delegated authority
This layer covers:
- documents on self-certification
- decisions or lists of authorized bodies
- operational delegation / authorization decisions

This is relevant because the target system should not hardcode one issuance lane.

### 5. Historical and superseded lineage
The corpus contains many amendments and older predecessor texts.

This layer matters because:
- legal retrieval needs lineage, not only current-text search
- the system must distinguish:
  - `current governing document`
  - `amendment`
  - `historical predecessor`
  - `supporting operational decision`

## Core Retrieval Keys
Each legal document in the lookup system should eventually be tagged by these keys:

- `document_type`
  Example: `decree`, `circular`, `decision`, `official letter`, `appendix package`
- `process_scope`
  Example: `general-origin`, `issuance`, `verification`, `electronic-filing`, `self-certification`, `delegation`
- `agreement_scope`
  Example: `general`, `ATIGA`, `AKFTA`, `RCEP`, `EVFTA`, `UKVFTA`
- `form_scope`
  Example: `Form D`, `Form AK`, `Form EUR.1`, `Form RCEP`
- `legal_status`
  Example: `current`, `amending`, `historical`, `administrative-support`
- `effective_date`
- `supersedes`
- `amends`
- `attachments_present`
- `contains_psr`
- `contains_forms_or_templates`

## Lookup Views The Project Needs

### View A. Current governing baseline
A shortlist of the currently governing common documents for:
- general origin framework
- C/O issuance process
- self-certification approval
- authority / delegation

This view should be shown first to anyone trying to understand the live regime.

### View B. Agreement pack
For one chosen agreement or form, show:
- governing core circular
- amendment chain
- appendices and PSR materials
- forms / templates / declarations bundled in the mirrored archive

This view should feed the origin-rule engine and the dossier checklist builder.

### View C. Filing workflow pack
For one shipment case, show the legal materials relevant to:
- trader registration
- dossier submission
- issuance lane
- correction / amendment
- archive / retention

This view should feed the operational workflow and task states.

### View D. Rule-engine pack
For one target agreement and product case, show:
- governing rule document
- rule family / PSR annex references
- valuation and evidence requirements
- appendices used for declaration or calculation

This view should feed the origin engine and explainability layer.

## Integration With The CO System

### 1. Trader profile registration
The legal lookup should resolve:
- whether this agreement or issuance lane has special registration requirements
- which declaration or approval artifacts are needed

### 2. Product-origin evidence
The legal lookup should resolve:
- which rule document governs the product case
- whether the rule is `CTC`, `RVC`, `PSR`, process-specific, or compound
- which appendices or declaration templates support the evidence pack

### 3. Shipment-level filing
The legal lookup should resolve:
- which issuance document governs the filing lane
- which forms and supporting documents are mandatory
- whether the case is electronic, paper, or mixed-lane

### 4. Origin evaluation engine
The legal lookup should resolve:
- the current effective rule text
- amendment lineage
- rule parameters, PSR references, and required evidence artifacts

### 5. Audit and post-issuance review
The legal lookup should resolve:
- verification rules
- retention expectations
- authority and delegation basis

## Proposed Next Normalization Step
The mirrored corpus is enough to move beyond flat wiki pages, but not enough to treat the current raw wiki as canonical legal text.

The next normalization pass should create one canonical row per document with:
- discovery metadata
- text-source candidates
- preferred canonical text source
- lineage fields
- scope tags
- agreement / form tags
- “core vs supporting” classification
- appendix presence
- extracted citation targets

That normalized legal index should then become the retrieval backbone for:
- document checklist generation
- rule-engine lookup
- operator-side legal drilldown
- explanation links inside the future CO system

## Current Practical Shortlist
If the project needs a first “must-resolve” pack before deeper legal tagging, start with:

1. `31/2018/NĐ-CP`
2. `05/2018/TT-BCT`
3. `23/2025/TT-BCT`
4. `40/2025/TT-BCT`
5. the active form/agreement circulars actually seen in cases:
   - `Form D`
   - `Form AK`
   - `Form EUR.1`
   - `Form RCEP`
   - `Form VK`

This shortlist is enough to begin connecting:
- issuance workflow
- origin-rule lookup
- dossier template expectations
- current project case patterns
