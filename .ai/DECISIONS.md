# Architecture Decisions

<!-- Format:
## [Date] Decision Title
**Context:** Why this decision was needed
**Decision:** What was decided
**Alternatives:** What else was considered
**Consequences:** What this means going forward
-->

## [2026-04-15] Defer Application Stack Until Discovery Completes
**Context:** The user asked for project bootstrap in the sense of metadata and data exploration, not immediate application scaffolding.
**Decision:** Do not commit to a web application stack yet; keep the repo focused on archive extraction, project context, and data discovery.
**Alternatives:** Scaffold a frontend or backend before understanding the data and workflow.
**Consequences:** The next architecture decision should be made against the actual CO process and dataset, not against a guessed UI stack.

## [2026-04-15] Discovery Is File-System Backed First
**Context:** The only reliable source material today is the agency archive, including spreadsheets, PDFs, ZIPs, and RARs.
**Decision:** Treat `data/extracted/CO` as the discovery source of truth for the bootstrap phase instead of inventing seed data or introducing a database immediately.
**Alternatives:** Start with mock data, or design the full relational model before reading the real files.
**Consequences:** Planning stays anchored to the actual case structure, but the next phase must normalize spreadsheet and document metadata into app-owned entities.

## [2026-04-15] Use JS-Based RAR Extraction
**Context:** The environment does not include a native `unrar` binary, but the supplied archive set contains multiple `.rar` bundles that are part of active and completed cases.
**Decision:** Add `node-unrar-js` and provide a local extraction script.
**Alternatives:** Leave RAR files opaque, depend on manual extraction outside the repo, or install platform-specific native tooling.
**Consequences:** Discovery remains reproducible within the project, and future ingestion flows can reuse the same JS-based archive support.

## [2026-04-27] Use FastAPI/Jinja For First CO Demo Shell
**Context:** The user asked for a working demo webapp for preparing a simple C/O case, with BCQT-System as the reference implementation style.
**Decision:** Add a small FastAPI/Jinja demo app in this repo for the first C/O preparation surface. This is a demo shell decision, not a final production architecture decision.
**Alternatives:** Continue with Node-only scripts, or scaffold a larger frontend/backend stack before validating the C/O workflow.
**Consequences:** The demo can reuse the same operational UI pattern as BCQT-System while keeping the final database/auth/deploy decisions open.
