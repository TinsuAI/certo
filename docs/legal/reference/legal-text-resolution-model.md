# Legal Text Resolution Model

## Purpose
This document defines the target legal-text pipeline for the project.

The key change is simple:
- `eCoSys` is a discovery feed and binary mirror
- the future legal lookup system should run on a canonical text layer
- PDF and office-file extraction are secondary, not the default reading layer

## Why The Previous Direction Was Not Enough
The initial pipeline mirrored the official eCoSys page, downloaded its files, and extracted text directly from those binaries.

That is still useful, but it is not enough for a reliable lookup system because:
- some PDFs return empty text
- some legacy `.doc` files decode with mojibake
- page-layout extraction introduces page breaks, line wraps, and broken legal structure
- the rendered output is closer to raw OCR/layout text than to a legal wiki

## Source Roles

### 1. Discovery feed
`eCoSys DocumentView.aspx`

Role:
- detect which legal and procedural documents are currently in scope
- mirror the linked official binary files
- keep the source list in sync over time

This layer answers:
- what new document appeared
- what file the official workflow page links to
- what form/group bucket the document is shown under

### 2. Binary provenance
`pdf`, `doc`, `docx`, `rar`, `zip` mirrored from eCoSys

Role:
- provenance
- auditing
- fallback extraction
- attachment preservation

This layer should not be treated as the main lookup text if a better text-based source exists.

### 3. Canonical text source
Preferred order:
1. official text-based source
2. `TVPL` internal fallback text source
3. raw extraction from mirrored binary files

This is the layer that should drive:
- article-level reading
- search
- citations
- future legal knowledge extraction
- links into CO workflow logic

## Registry Model
Each document should have one registry entry with these fields:
- `discovery`
  Where it was seen in eCoSys and which mirrored binary file belongs to it.
- `rawBinarySource`
  The mirrored official file kept for provenance.
- `textCandidates`
  All candidate text sources currently known for this document.
- `preferredTextSource`
  The current canonical source selected for lookup.

This allows the system to distinguish:
- what was discovered officially
- what is only a mirrored binary artifact
- what text source is currently trusted for reading/search

## Resolution Strategy

### Step 1. Mirror the feed
Mirror the eCoSys listing and linked files.

### Step 2. Resolve text candidates
For every discovered document:
- try to resolve an official text-based source
- if that is not available yet, resolve a `TVPL` fallback
- keep raw binary extraction as a temporary or emergency fallback

### Step 3. Normalize into canonical markdown
Only after a preferred text source is chosen should the system produce canonical legal markdown with:
- metadata
- article structure
- clause structure
- point structure
- appendices
- tables
- source lineage

### Step 4. Build the lookup app on top of canonical markdown
The webapp should consume canonical markdown, not raw extraction pages.

## Current Status
The repo now has:
- an eCoSys mirror
- a raw extraction layer
- a source-enrichment layer
- a text-source registry

The missing layer is still:
- official text-source resolution
- canonical legal markdown normalization

## Practical Rule
If a user asks to read, search, or cite a legal document:
- prefer the canonical text source
- if none is resolved, use the best fallback text source
- use the mirrored binary file only for provenance or recovery
