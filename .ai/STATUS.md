# Project Status

## Currently Working On
- Metadata bootstrap and data discovery for the CO project
- Converting the supplied agency archive into a fully extracted local corpus and a written exploration report

## Recent Changes
- Expanded the supplied ZIP archive and explored the extracted CO case folders
- Added `node-unrar-js`, extracted all supplied `.rar` archives locally, and kept a repeatable extraction script
- Removed premature webapp scaffolding; repository now reflects discovery-first scope
- Pulled relevant CO knowledge from the correct host Obsidian vault into `.ai/knowledge/`
- Added a design-foundation document that consolidates workbook workflow, business logic, knowledge base, and legal constraints
- Published shared project docs in `docs/` for workflow, knowledge base, workbook logic, and data analysis

## Next Steps
- Confirm the first business workflow to model from the explored documents
- Confirm the real production macro path and ledger semantics in the workbook
- Decide application stack only after discovery on source files and workbook logic is complete
- Normalize naming, statuses, and dossier types into a stable domain model

## Blockers
- None for bootstrap

## Notes for Next AI Session
- `data/` is local-only and gitignored on purpose
- The legacy `.xlsm` workbook in `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/` is a likely source of business rules
- Do not assume the current folder structure maps 1:1 to future product entities
- Correct host wiki path is `/mnt/c/Users/sys/Dropbox/Obsidian/V-Notes/30_Resources`
