# Session: Full Canonical Corpus Build

## What Was Done
- Added a full-corpus canonical builder in `scripts/build-legal-canonical-corpus.mjs` and exposed it via `npm run legal:build-canonical-corpus`.
- Extended canonical source selection in `scripts/lib/legal-canonical-normalization.mjs` so a caller can exclude specific source ids; current corpus build excludes `tvpl`.
- Patched `scripts/enrich-legal-sources.mjs` so dead `VBPL` seeds no longer crash the whole enrichment pass. Live fetch errors now fall back to cached HTML when available, otherwise resolve as `unresolved/fetch_failed`.
- Added `source inventory` and `source packets` builders plus supporting helper library:
  - `scripts/build-legal-source-inventory.mjs`
  - `scripts/build-legal-source-packets.mjs`
  - `scripts/lib/legal-source-packets.mjs`
- Rebuilt the non-`TVPL` corpus end to end:
  - `SKIP_TVPL=1 npm run legal:enrich-sources`
  - `npm run legal:build-source-registry`
  - `npm run legal:build-source-inventory`
  - `npm run legal:build-source-packets`
  - `npm run legal:build-canonical-corpus`
  - `npm run legal:build-wiki`
- Generated `71/71` canonical corpus files under `docs/legal/canonical/corpus/` and created `docs/legal/indexes/canonical-corpus.md`.
- Updated `source inventory` and `source packets` to recognize canonical files from both `canonical/pilot` and `canonical/corpus`, so the metrics now reflect the full build.
- Added regression coverage for the new source-packet helpers and for excluding `TVPL` from canonical selection.

## Decisions Made
- `TVPL` is off the critical path for corpus build. Canonical generation now proceeds from `official-text`, `ocr-recovery`, or `ecosys-extracted` only.
- Full coverage was preferred over waiting for perfect source fusion. The repo now has a complete canonical layer for all 71 documents, but quality still depends on the selected lane.
- Dead or unstable official URLs must not block batch builds. The enrichment layer should degrade gracefully and preserve prior cache when possible.
- `source packets` were introduced as a separate artifact rather than mutating the registry schema in place. This keeps the viewer and registry stable while creating a foundation for future block-level fusion.

## What Didn't Work
- `TVPL` remains unusable for live auto-fetch because of Cloudflare. Existing TVPL files on disk are historical/manual artifacts only and should not be interpreted as a reliable live source lane.
- Re-running `legal:enrich-sources` initially failed on a `VBPL` 404 (`23/2025/TT-BCT`) because the script treated official fetch errors as fatal. This was fixed during the session.
- The current canonical builder still normalizes whole-document text in one pass. It does not yet preserve tables, formulas, or appendices as first-class structural blocks.

## Open Items
- Replace whole-document canonical selection with block-level fusion for the documents that have better attachment text than their current chosen lane.
- Tighten preservation policy for `official HTML`, especially VBPL Word-clipped HTML, before promoting more official sources into trusted canonical use.
- Audit the `24` `ecosys-extracted` canonicals and `19` `ocr-recovery` canonicals to identify the next best upgrade candidates.
- Clean up the semantics around TVPL in viewer/index docs so it is clearly labeled as a reference artifact rather than a stable fetchable source.
