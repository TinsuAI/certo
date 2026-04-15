# Project Status

## Current State
- Repo is now a discovery-first workspace for the CO domain, not a webapp scaffold.
- Shared project-facing documentation lives in `docs/` and covers data exploration, procedure analysis, CO knowledge, and workbook business logic.
- The source archive has been extracted under `data/extracted/CO`, including nested RAR extraction via `npm run extract:rars`.
- The `.xlsm` workbook remains the strongest source of current business rules, especially around allocation, traceability, and rule-specific output generation.

## Recent Changes
- Removed the premature Next.js scaffold and committed the repo back to a documentation and discovery baseline.
- Analyzed the procedure PDF, flowchart image, and the macro workbook in depth.
- Pulled relevant CO knowledge from the correct V-Notes vault path at `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`.
- Published project-facing docs in `docs/`:
  - `docs/workbook-business-logic-foundation.md`
  - `docs/procedure-and-workbook-analysis.md`
  - `docs/co-knowledge-base.md`
  - `docs/data-exploration.md`
- Clarified the business model around:
  - trader profile registration on eCoSys
  - reusable product-origin evidence
  - shipment-level C/O filing

## Next Steps
- Confirm the exact production path operators use inside the workbook, especially whether `RunUpgrade` is the true source-of-truth path.
- Confirm the semantics of the historical ledgers in `Save` and `Tru lui` and whether they are scoped per company, workbook clone, or period.
- Identify the first form families and shipment workflows to support in a system design.
- Convert workbook sheet semantics into a field-level domain map once operator validation is available.

## Notes for Next AI Session
- `data/` is local-only and gitignored on purpose.
- Correct host wiki path is `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`.
- The key design insight from this session is that the future system must model both:
  - compliance workflow
  - stateful allocation / origin-rule engine
- The docs in `docs/` are intended for the whole project, not only AI handoff. `.ai/` should remain working context and session history.
