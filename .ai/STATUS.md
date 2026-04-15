# Project Status

## Currently Working On
- Bootstrap and discovery phase for the CO staff webapp
- Converting the supplied agency archive into a usable local inventory and app-facing dashboard

## Recent Changes
- Scaffolded a Next.js 16 + TypeScript app in the project root
- Expanded the supplied ZIP archive and explored the extracted CO case folders
- Added a filesystem discovery layer and initial dashboard that reads from `data/extracted/CO`
- Added `node-unrar-js`, extracted all supplied `.rar` archives locally, and kept a repeatable extraction script

## Next Steps
- Define the first end-to-end operator workflow: create/edit a CO case from source documents
- Decide how spreadsheet fields map into normalized app data
- Choose long-term storage and auth once discovery on the source files is complete

## Blockers
- None for bootstrap

## Notes for Next AI Session
- `data/` is local-only and gitignored on purpose
- The current app is intentionally discovery-first, not a full CO submission workflow yet
- The legacy `.xlsm` workbook in `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/` is a likely source of business rules
