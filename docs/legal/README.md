# Legal Workspace

This area organizes public legal and procedural materials used to understand and build the future CO system.

## Layout
- `docs/legal/wiki/`
  Generated wiki-style pages for mirrored legal documents.
- `docs/legal/indexes/`
  Generated indexes and lookup entry points.
- `docs/legal/reference/`
  Curated, project-facing synthesis documents.

## Reference Docs
- [CO Legal Lookup System](./reference/co-legal-lookup-system.md)
- [Legal Text Resolution Model](./reference/legal-text-resolution-model.md)
- [Legal Quality Audit](./indexes/quality-audit.md)

## Data Boundaries
- Raw official mirrors stay under local-only `data/legal/official-mirror/`.
- Normalized extracted text and attachment caches stay under local-only `data/legal/normalized/`.
- Only cleaned wiki pages, indexes, and higher-signal reference docs belong in `docs/legal/`.

## Pipeline
1. `npm run mirror:ecosys-docs`
   Mirror the official eCoSys legal-document listing and download the linked files.
2. `npm run legal:enrich-sources`
   Resolve internal fallback text candidates such as `TVPL`.
3. `npm run legal:audit-quality`
   Audit extraction quality, classify source types, and flag OCR candidates before promoting any text into a canonical layer.
4. `npm run legal:build-source-registry`
   Build the text-source registry that separates discovery, binary provenance, text candidates, and preferred canonical text source.
5. `npm run legal:build-wiki`
   Generate provisional raw wiki pages from mirrored files. This is a temporary extraction layer, not the final canonical legal text layer.

## Source Policy
- `eCoSys` is the official discovery feed for this corpus. It tells us which legal/procedural items are in scope and gives us the mirrored binary file for provenance.
- The preferred canonical text source should be an official text-based source when available.
- `Thư Viện Pháp Luật` is an internal fallback text layer when an official text-based source is not yet resolved.
- Binary files mirrored from `eCoSys` remain secondary artifacts for provenance, validation, and emergency fallback only.
- OCR is a controlled recovery lane for scan-like or empty PDFs, not the default extraction path for the full corpus.
