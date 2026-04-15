# Project Status

## Current State
- Repo remains a discovery-first workspace for the CO domain.
- Project-facing CO docs are materially stronger now: there is a Vietnamese `docs/BUSINESS_LOGIC_CONFIRMATION.md` for agency review, plus supporting docs for workbook logic, input/output model, and origin-rule case studies.
- Terminology has been cleaned up across the active docs so `quy tắc xuất xứ`, `hiệp định áp dụng`, `loại mẫu C/O`, and `kênh cấp / kênh nộp` are no longer intentionally collapsed into one concept.
- The confirmation doc has already gone through several critical review passes and its answer format is now agency-friendly.

## Recent Changes
- Drafted `docs/BUSINESS_LOGIC_CONFIRMATION.md` in Vietnamese, modeled after `BCQT-System/docs/BUSINESS_LOGIC_CONFIRMATION.md` but rewritten for the CO domain.
- Refined that confirmation doc to make product-level evidence reuse explicit, avoid implying that each product requires its own submitted C/O dossier, and switch all answer slots to the new format:
  - confirmation items: `☐ Đúng / ☐ Sai` + `Phản hồi:`
  - open questions: `Phản hồi:`
- Cleaned up domain language across the active docs:
  - removed `form family` / `nhóm mẫu` as a catch-all abstraction
  - separated `quy tắc xuất xứ` from `loại mẫu C/O`
  - separated `loại mẫu C/O` from `kênh cấp / kênh nộp`
  - limited `phôi` to concrete paper-output file references instead of using it as a domain concept
- Updated related docs and AI knowledge/report artifacts so they no longer reintroduce the same terminology confusion.

## Next Steps
- Review `docs/BUSINESS_LOGIC_CONFIRMATION.md` with the user / agency and capture which statements are confirmed, rejected, or need rewriting.
- Decide which current project-facing doc changes should be committed together as the next docs commit.
- If the confirmation doc is accepted as the canonical source, inspect `BCQT-System` rendering code and reproduce an equivalent `.docx` pipeline for the CO-side document.
- Continue refining field-level semantics for `DM`, `X-N`, `Save`, and `Tru lui` only after operator validation is available.

## Blockers
- Agency / operator validation is still missing for several workbook semantics:
  - exact meaning of the grouping key in `DM`
  - operational scope of `Save` and `Tru lui`
  - practical rule for choosing C/O form type vs agreement vs origin rule in edge cases
- The current `docs/` changes are still uncommitted project files.

## Notes for Next AI Session
- `data/` is local-only and gitignored.
- Correct host wiki path is `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`.
- The user wants project knowledge in `docs/`; `.ai/` is only for AI working context and handoff.
- `docs/BUSINESS_LOGIC_CONFIRMATION.md` is agency-facing, so Vietnamese is appropriate there even though most project docs are in English.
- The user is sensitive to concept conflation. Do not collapse:
  - `quy tắc xuất xứ`
  - `hiệp định áp dụng`
  - `loại mẫu C/O`
  - `kênh cấp / kênh nộp`
- Do not use `phôi` as a general domain term; only use it when referring to actual paper-output artifacts or filenames.
