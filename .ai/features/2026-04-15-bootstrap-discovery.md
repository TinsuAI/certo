# Feature: Bootstrap Discovery Workspace

## Scope
Set up the first runnable webapp shell for barry-CO and ground it in the supplied agency archive. This includes extracting the available ZIP sources, inspecting the document landscape, and exposing the real case/status structure in the UI.

Out of scope for this bootstrap:
- Building CO submission forms
- Normalizing spreadsheet fields into a database
- Auth, permissions, and external submission integrations

## Decisions
- Start with Next.js 16 + TypeScript because the app needs a UI quickly and can benefit from server-side filesystem access during discovery.
- Keep the bootstrap local-first: extracted files under `data/extracted/CO` drive the first dashboard.
- Add JS-based `.rar` extraction support because the source material includes RAR bundles and native tooling is unavailable here.

## Risks
- Business rules likely live in the legacy `.xlsm` workbook and are not yet modeled in code.
- Some case data is still nested in archives, and RAR extraction can fail on damaged or password-protected files.
- The current folder names mix status labels, dossier labels, and document categories; app entities will need explicit normalization.

## Open Questions
- Which fields from the spreadsheets and customs forms are mandatory for the first operator workflow?
- Will the production system store uploaded documents in app-managed storage, or continue to rely on external folder structures?
- What submission target and auth model does the agency need once the app moves past discovery?
