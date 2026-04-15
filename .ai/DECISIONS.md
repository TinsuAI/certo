# Architecture Decisions

<!-- Format:
## [Date] Decision Title
**Context:** Why this decision was needed
**Decision:** What was decided
**Alternatives:** What else was considered
**Consequences:** What this means going forward
-->

## [2026-04-15] Bootstrap With Next.js App Router
**Context:** The project started as an empty AI-initialized workspace with only agency source archives and no existing application structure.
**Decision:** Use Next.js 16 with TypeScript and React 19 as the initial webapp stack.
**Alternatives:** Vite + React, a custom Node server, or waiting for a stack decision before bootstrapping.
**Consequences:** We get a production-capable UI shell quickly, can read local files on the server side during discovery, and keep room for route handlers and future authenticated workflows.

## [2026-04-15] Discovery Is File-System Backed First
**Context:** The only reliable source material today is the agency archive, including spreadsheets, PDFs, ZIPs, and RARs.
**Decision:** Treat `data/extracted/CO` as the discovery source of truth for the bootstrap phase instead of inventing seed data or introducing a database immediately.
**Alternatives:** Start with mock data, or design the full relational model before reading the real files.
**Consequences:** Early UI and planning stay anchored to the actual case structure, but the next phase must normalize spreadsheet and document metadata into app-owned entities.

## [2026-04-15] Use JS-Based RAR Extraction
**Context:** The environment does not include a native `unrar` binary, but the supplied archive set contains multiple `.rar` bundles that are part of active and completed cases.
**Decision:** Add `node-unrar-js` and provide a local extraction script.
**Alternatives:** Leave RAR files opaque, depend on manual extraction outside the repo, or install platform-specific native tooling.
**Consequences:** Discovery remains reproducible within the project, and future ingestion flows can reuse the same JS-based archive support.
