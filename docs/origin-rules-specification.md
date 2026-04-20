# Origin Rules Specification

## Purpose
This document defines the origin-rule model that the future CO system should implement.
It normalizes the rule taxonomy already seen in the workbook and completed dossiers, then ties that taxonomy to official rule-of-origin sources.

This document is not a full legal digest for every FTA.
It is a system specification for how origin rules should be represented, evaluated, and explained.

## Design Boundaries

### In scope
- origin-rule taxonomy and evaluation semantics
- the relationship between `agreement`, `product-specific rule`, `origin rule`, and `C/O form type`
- minimum data requirements for pass/fail evaluation
- explainability and auditability requirements

### Out of scope
- a complete per-HS rule library for all agreements
- shipment filing workflow and issuance tracking
- final operator policy for choosing the best agreement in borderline commercial cases

## Core Modeling Principles
1. `Origin qualification is rule-based, not purity-based.`
   A good can qualify even when some inputs are non-originating, if the applicable rule is satisfied.
2. `Agreement`, `origin rule`, `C/O form type`, and `issuance lane` are separate concepts.
   They must not be stored as one overloaded field.
3. `PSR` is not one formula.
   It is the agreement-specific rule entry that applies to a tariff line, and it may point to one or more rule tests.
4. `Workbook output families` are not always `rule families`.
   Sheets such as `EUR1`, `FORM B`, and `FORM X` are output or filing artifacts, not rule definitions.
5. The engine must preserve `why this passed` and `which evidence was used`.
   Pass/fail without explanation is not sufficient for operator review or later verification.

## Legal Structure Vs Internal Taxonomy
The future system needs two layers that must not be conflated:

1. `Legal-source structure`
   How an agreement expresses origin criteria in its legal text or PSR annex.

2. `Internal evaluator taxonomy`
   How the system normalizes those criteria into reusable evaluator families.

This distinction matters because agreements do not all package rule logic the same way.
For example, an agreement may use a PSR annex as the legal container for tariff-line rules while still expressing criteria such as `WO`, `CC`, `CTH`, `CTSH`, `RVC`, or a named process rule inside that annex.

The internal system should therefore:
- preserve the legal-source expression for traceability
- normalize the underlying evaluator logic for implementation
- avoid assuming that `PSR` and `non-PSR` are separate legal universes

## Rule Taxonomy

### 1. WO
`WO` applies when the good is wholly obtained or produced in the relevant territory.

Typical examples:
- plants grown and harvested there
- live animals born and raised there
- minerals extracted there
- goods produced there exclusively from such goods

System meaning:
- usually the simplest pass path
- usually incompatible with normal imported-material scenarios
- still needs evidence and provenance, not only a final checkbox

### 2. CTC
`CTC` means `change in tariff classification`.
This family applies only to non-originating materials.

Observed and official subtypes:
- `CC`: change at the `chapter` level, HS 2-digit
- `CTH`: change at the `heading` level, HS 4-digit
- `CTSH`: change at the `subheading` level, HS 6-digit

System meaning:
- the evaluator compares the finished-good HS code against each non-originating input HS code
- the comparison level depends on the rule entry
- exclusions in a PSR must apply only to non-originating materials

### 3. RVC
`RVC` means `regional value content`.
It tests whether the good contains enough regional value to satisfy the required threshold.

Observed formula family:
- indirect/build-down form:
  `RVC = (FOB - value of non-originating materials) / FOB × 100`

Some agreements also define a direct/build-up form.
The engine should not assume one formula implementation is universal across all FTAs.

System meaning:
- the rule definition must store the threshold, formula mode, and valuation basis
- evidence must show the final percentage and the inputs used to derive it
- non-originating and undetermined-origin materials must be handled explicitly

### 4. LVC
`LVC` in this project is a workbook-observed value-content rule variant using imported or undetermined-origin inputs against `FOB`.

Observed project formula:
- `LVC = (FOB - CIF value of imported or undetermined-origin inputs) / FOB × 100`

System meaning:
- treat `LVC` as an agreement-specific or workbook-specific value-content evaluator, not as a universal synonym for `RVC`
- the rule library must allow multiple value-content formulas to coexist

### 5. Process Rules
Some origin criteria cannot be reduced to tariff-shift or value-content logic.
They instead require a named manufacturing or processing operation.

In legal texts, these may appear as:
- a named criterion code such as `CR`
- a process condition inside a PSR entry
- another agreement-specific process requirement

Examples from official materials:
- textile rules such as `yarn-forward` or other stage-specific process requirements
- chemical-reaction rules
- other named processing requirements for a product family

System meaning:
- not every rule can be reduced to HS comparison or a percentage formula
- the engine needs a normalized `process-rule` evaluator family
- the source criterion code or legal phrase must still be stored separately for traceability and output wording

### 6. PSR
`PSR` means `product-specific rule`.
It is the agreement-specific rule entry for a tariff line or tariff group.

Important modeling point:
- `PSR` is not one evaluator
- a PSR entry may require:
  - one test only, such as `CTH`
  - one value-content test, such as `RVC40`
  - one specific process test
  - a compound rule, such as `RVC 35% + CTSH`
  - alternative rules, where satisfying one rule path is enough

System meaning:
- store `PSR` as legal/configuration structure
- store the underlying evaluator graph separately
- allow a PSR entry to encode `WO`, `CTC`, `RVC`, a process rule, or a combination of them
- do not persist only the display label `PSR` without the actual rule logic behind it

## Originating-Material Path
Some agreements also recognize a path where a good qualifies because it is produced exclusively from originating materials.

System meaning:
- this should be modeled as an origin-conferring condition the engine can recognize
- it should not automatically be promoted to a separate canonical rule family in the project taxonomy unless the target agreement or operating vocabulary requires that
- the material model must distinguish `originating`, `non-originating`, and `undetermined`

## Compound And Alternative Rules
Origin rules are not always single-condition.

The engine must support:
- `AND` composition
  Example: `RVC 35% + CTSH`
- `OR` composition
  Example: `RVC40 or CTH`
- nested rule expressions
  Example: `(CTH or RVC40) and not excluded material set`

The rule model therefore needs an explicit expression structure rather than free-text storage.

## Cross-Cutting Modifiers
These modifiers are not primary rule families, but they materially affect evaluation.

### 1. De minimis / tolerance
Some FTAs allow a good to pass even if a small amount of non-originating material does not satisfy the required tariff shift, often subject to percentage limits.

System requirement:
- store the tolerance rule separately from the main evaluator
- apply it only where the agreement allows it

### 2. Cumulation / accumulation
Some FTAs allow originating materials from other member countries to count as originating in the final product.

System requirement:
- origin status cannot be modeled as only `Vietnam` versus `non-Vietnam`
- the material model needs `originating under agreement X from member Y`

### 3. Minimal operations
Many FTAs state that simple or minimal operations are not enough to confer origin.

System requirement:
- even if data appears to satisfy a superficial transformation path, the engine or review layer must still guard against disallowed minimal processing

### 4. Materials of undetermined origin
Official rules commonly treat undetermined-origin materials as non-originating.

System requirement:
- `undetermined` must remain a first-class status
- the evaluator must not silently coerce unknown origin into pass

### 5. Packaging, accessories, and indirect materials
These items may be ignored for some rule tests but included for value-content calculations depending on the agreement.

System requirement:
- the material schema needs typed roles such as:
  - core production material
  - retail packaging
  - transport packaging
  - accessory/spare/tool
  - indirect material

## Minimum Data Requirements

### Product-level data
- finished-good identifier
- finished-good HS code and HS version
- agreement candidate
- declared target market
- BOM or equivalent material structure
- manufacturing process description
- product-specific evidence set version

### Input-material data
- material identifier
- material HS code and HS version when relevant
- origin status:
  - originating
  - non-originating
  - undetermined
- source country or agreement-member source when relevant
- source document links
- valuation data needed by the applicable rule

### Shipment/case data
- shipment identifier
- target agreement
- chosen C/O form type
- chosen origin rule expression
- filing date and export reference data
- evaluator result snapshot for that shipment

### Allocation and traceability data
- source-row provenance for consumed materials
- quantity and value consumed in this evaluation
- residual CO-eligible balance where the workbook logic depends on it
- evidence bundle version used for the decision

## Evaluator Requirements By Rule Family

### WO evaluator
Must confirm:
- the good fits a wholly obtained category
- evidence supports that category
- no disqualifying non-originating materials are involved

### CTC evaluator
Must:
- compare finished-good HS against each non-originating input HS
- compare at the required level: `CC`, `CTH`, or `CTSH`
- respect PSR exclusions and allowed exceptions
- produce a row-level explanation of which inputs passed or blocked the rule

### RVC/LVC evaluator
Must:
- identify which material values are counted as non-originating
- compute the agreed formula using the correct basis
- compare against the rule threshold
- preserve all intermediate values used in the calculation

### Process-rule evaluator
Must:
- compare the declared manufacturing route against the required process rule
- record which process evidence supports the claimed operation
- support agreement-specific process templates
- preserve the legal-source criterion code or phrase behind the normalized process evaluator

### Originating-material path check
Must confirm:
- every consumed material is originating under the target agreement
- no undetermined or non-originating material remains in the evaluated composition
- the result is stored with the legal basis used by the target agreement

### Compound evaluator
Must:
- evaluate each child rule separately
- combine results using the configured boolean logic
- explain both the child outcomes and the final combined outcome

## Rule Configuration Model
At minimum, the future system needs these configuration layers:

### Agreement
- agreement code
- member set
- effective period
- HS version
- special modifiers allowed under this agreement

### PSR entry
- tariff scope
- display text from the legal source
- legal criterion codes or phrases as published
- normalized evaluator expression
- exclusions or notes
- tolerance/cumulation settings if applicable

### Evaluator definition
- evaluator family: `WO`, `CTC`, `RVC`, `LVC`, `PROCESS_RULE`, or composition node
- parameters
- explanation template

### Evidence template
- required supporting document types
- output format or worksheet template where applicable

## Pass/Fail Output Contract
Every evaluation result should produce:
- final status: `pass`, `fail`, or `needs review`
- normalized rule expression actually applied
- agreement and PSR reference used
- summary explanation
- row-level reasoning where relevant
- all computed values and thresholds where relevant
- linked evidence documents and source rows
- reviewer overrides and justification if a manual decision occurs

## Workbook Mapping Constraints
The current workbook mixes several concepts that the future system must separate.

### Worksheet artifacts observed in the workbook
- `LVC`
- `RVC`
- `CTH`
- `CTSH`
- `WOIII`
- `EUR1`
- `FORM B`
- `FORM X`
- `PTN`

Implication:
- a worksheet name may correspond to a rule template, a filing form, or both
- a canonical rule family may exist even when no dedicated worksheet with the same name has been observed
- `CC` is a real rule family in completed cases and in the normalized taxonomy, even though a dedicated `CC` worksheet has not yet been observed in the current workbook
- the target system must not use worksheet names as the canonical rule taxonomy

## What The Current Repo Already Proves
- real cases use `CTH`, `CTSH`, `CC`, `PSR`, and compound `RVC 35% + CTSH`
- non-originating inputs are normal and do not automatically block origin
- the same product family can qualify under different rules in different cases
- rule explainability is operationally necessary
- value-content and tariff-shift logic both exist in the current workbook and dossiers

## Open Questions
- Which agreements should be modeled first in the first implementation slice?
- Which `specific process` rules matter in the actual agency backlog beyond the already observed examples?
- When multiple valid rule paths exist, should the system:
  - let operators choose manually
  - compute all valid candidates
  - or rank candidates by policy
- How should the first release handle `PSR` parsing:
  - curated manual configuration
  - semi-structured import from legal annexes
  - or both

## Source Notes
This specification is grounded in:
- completed dossier evidence already documented in this repo
- workbook and VBA analysis already documented in this repo
- official FTA overview and legal materials published on the Ministry of Industry and Trade / VNTR sites, including:
  - VKFTA overview on origin pathways and rule families: https://vntr.moit.gov.vn/vi/fta/21/2
  - ATIGA overview on `RVC`, tariff-shift, process rules, and combination rules: https://vntr.moit.gov.vn/vi/fta/3/2
  - RCEP legal text on originating goods, RVC calculation, minimal operations, tolerance, and rule definitions: https://vntr.moit.gov.vn/storage/agreement/rcep/1-content-of-the-agreement/en/1-regional-comprehensive-economic-partnership-agreement-full-en.pdf
  - UKVFTA legal text on product-specific rules and certification context: https://vntr.moit.gov.vn/vi/legal-documents/1271

Where an agreement-specific rule differs from the normalized model above, the agreement text must win.
