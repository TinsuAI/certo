# Feature: Origin Rules Specification

## Scope
Write a project-facing specification that defines the origin-rule model for the future CO system.

In scope:
- normalize the rule taxonomy used across the repo, workbook, and real dossiers
- separate `agreement`, `origin rule`, `C/O form type`, and `issuance channel`
- define the minimum data and evaluator behavior needed for rule-based origin qualification
- capture cross-cutting legal modifiers that affect evaluation

Out of scope:
- a full per-HS-code rule library for every FTA
- a final operator decision tree for choosing the agreement in each commercial case
- field-by-field mapping of every workbook column

## Decisions
- The main project-facing artifact should live in `docs/origin-rules-specification.md`.
- The spec should treat `PSR` as a rule container defined per agreement and tariff line, not as one standalone formula.
- `CTC` should be modeled as an umbrella family with `CC`, `CTH`, and `CTSH` as level-specific variants.
- Compound rules such as `RVC 35% + CTSH` must be first-class, not encoded as ad hoc text.
- Workbook sheet names like `EUR1`, `FORM B`, and `FORM X` should not be treated as origin-rule families.

## Risks
- Origin-rule semantics differ across FTAs; a generic engine can drift into false uniformity if agreement-specific parameters are not explicit.
- The repo has strong evidence for `RVC`, `LVC`, `CTH`, `CTSH`, `CC`, and `PSR`, but weaker live-case evidence for `WO`, `PE`, and some specific-process rules.
- If the system stores only final pass/fail without traceable reasons, it will fail operator review and post-issuance audit needs.

## Open Questions
- Which agreements and product families must be supported first in the first implementation slice?
- When more than one valid rule path exists, does the operator choose manually, or should the system rank/compare candidates?
- Which `specific process` rules matter in the real operating backlog beyond the currently observed cases?
