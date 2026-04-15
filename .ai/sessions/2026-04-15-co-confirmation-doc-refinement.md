# Session Log: CO Confirmation Doc Refinement

## What Was Done
- Drafted a new agency-facing confirmation document at `docs/BUSINESS_LOGIC_CONFIRMATION.md`, using `BCQT-System/docs/BUSINESS_LOGIC_CONFIRMATION.md` as the structural reference.
- Reworked the draft through multiple review rounds so it now:
  - keeps business confirmation separate from future-system framing
  - distinguishes product-level origin evidence from shipment-level filing
  - makes clear that the product-evidence layer is not a separately submitted C/O dossier per product
  - uses the new response format:
    - `☐ Đúng / ☐ Sai`
    - `Phản hồi:`
- Ran critical reviews on the confirmation doc and then applied the findings rather than leaving them as comments.
- Cleaned terminology across the active project docs and supporting AI artifacts:
  - removed `form family` / `nhóm mẫu` as a catch-all
  - separated `quy tắc xuất xứ` from `loại mẫu C/O`
  - separated `loại mẫu C/O` from `kênh cấp / kênh nộp`
  - stopped using `phôi` as a generic domain concept
- Updated related files to keep the same vocabulary aligned:
  - `docs/co-input-output-model.md`
  - `docs/origin-qualification-case-studies.md`
  - `docs/workbook-business-logic-foundation.md`
  - `docs/co-knowledge-base.md`
  - `docs/README.md`
  - selected `.ai/knowledge/` and `.ai/reports/` references that are still used as AI source material

## Decisions Made
- The CO-side confirmation document should be client/agency-facing and in Vietnamese.
- `docs/BUSINESS_LOGIC_CONFIRMATION.md` should be a business-confirmation checklist, not a hidden system-specification document.
- The domain should explicitly separate:
  - product-origin evidence
  - shipment-level filing
  - origin-rule evaluation
  - C/O form type
  - issuance channel
- `loại mẫu C/O` must not be treated as an input to origin-rule determination.
- `phôi` should only be used for actual paper-output artifacts or filenames.

## What Didn't Work
- The first draft still mixed confirmed business facts, inferred interpretations, and future-system implications too freely; critical review exposed that and forced a rewrite of several sections.
- A terminology cleanup that only renamed `form family` to `loại mẫu C/O` was insufficient. It still left structurally wrong relationships where form type appeared to drive origin-rule selection.
- Early wording in Part 3 of the confirmation document could still be read as “one product = one separately submitted C/O dossier”; that had to be corrected explicitly.

## Open Items
- Review `docs/BUSINESS_LOGIC_CONFIRMATION.md` with the user / agency and collect real confirmations or disagreements.
- Confirm operator-side semantics for:
  - `DM` grouping key
  - `Save`
  - `Tru lui`
  - the practical relationship between agreement choice, origin rule choice, and chosen C/O form type
- Decide when to commit the current project-facing docs set.
- If the confirmation doc stabilizes, inspect `BCQT-System` doc rendering code and build the CO-side `.docx` pipeline.
