# DH-side build prompt — merged declarations PDF: speed + file-size efficiency

Hand this prompt to the Data Hub AI agent. It is self-contained (does not
require the CO repo). This **extends an already-shipped endpoint**
(`GET /v1/hub/clients/{client_id}/declarations/download.pdf`, the merged
TKX/TKN "tờ khai ghép" PDF, shipped + verified 2026-06-06). The new work is
**efficiency only** — faster render + smaller / size-bounded output — with full
backward compatibility. No change to auth, scoping, ordering, or the existing
gap-reporting headers.

---

```
You are working in the Data Hub codebase. You previously shipped this read-only endpoint for the CO (certificate-of-origin) service:

  GET /v1/hub/clients/{client_id}/declarations/download.pdf
    direction=import|export   declaration_nos=<csv ≤500>   sort=declaration_no|registration_date
  -> 200 application/pdf : all of the client's TKX/TKN declarations rendered to the official A4 tờ khai layout, merged into ONE PDF, in declaration_no order. Headers: X-Declarations-Requested/Included/Missing/Missing-Nos.

It works, but two real production problems remain. Fix both WITHOUT breaking the current contract: with none of the new params present, behaviour must be byte-for-byte the same as today.

## Problem 1 — too SLOW
This render dominates CO's dossier export. Real case: ~194 import declarations -> ~5668-page PDF -> ~43-45s, almost all of it spent inside DH rendering the .xls declarations to the official layout. CO already runs export as a background job, so the wall-clock is yours to cut.

Asks:
  1. PERSIST / CACHE per-declaration renders. The same declaration is re-rendered on every export and across dossiers. Cache the rendered single-declaration PDF keyed by the source file blob (content hash) + render-version. On a merge request, render only cache-misses, then concatenate. This is the big win: repeat/overlapping exports become near-instant.
  2. Render cache-misses in PARALLEL (bounded pool), then concatenate deterministically.
  3. STREAM the response (don't buffer the whole merged PDF for large sets) — the contract already asked for this near the 500 cap; confirm it holds.
  4. Add timing visibility: header  X-Render-Ms: <int>  (and optionally X-Render-CacheHits / X-Render-CacheMisses) so CO can confirm the win.

## Problem 2 — file too LARGE for the legacy Ecosys upload
The merged TKN PDF is ~20-50 MB. The agency files it on the OLD Ecosys portal, which rejects large attachments — practical working limit ~2 MB per file. Today they cannot attach the dossier. Two independent levers; please do BOTH:

  A. Render-time size reduction (a "compact" profile). Add:
       quality = print (default, = today's output)  |  compact (Ecosys-friendly)
     For quality=compact: downsample embedded scans/images to a target DPI (~150), use an efficient image codec (JPEG/Flate as appropriate), SUBSET fonts, dedup repeated XObjects/resources, and linearize. Goal: smallest file that is still clearly LEGIBLE as the official tờ khai. Report final size: header  X-Pdf-Bytes: <int>.
     NOTE — this trades against the contract's "faithful, lossless rendering" clause. Confirm with the CO owner the acceptable legibility floor before shipping a lossy profile; quality=print stays lossless and is the default.

  B. Size-bounded SPLIT. Add:
       max_part_bytes = <int>   (optional; when set and the output would exceed it)
     When the (already size-reduced) PDF would exceed max_part_bytes, return a ZIP
       Content-Type: application/zip
     of  declarations_{client_id}_{direction}-part-001.pdf … part-NNN.pdf , each part <= max_part_bytes, split on DECLARATION boundaries (never split a single declaration across parts). If one declaration alone exceeds max_part_bytes, emit it as its own part and report it via a header  X-Pdf-Oversize-Nos: <csv> . Deterministic part order = same declaration_no order. Headers  X-Pdf-Parts: <n>  and  X-Pdf-Bytes  (sum). When max_part_bytes is absent -> single PDF exactly as today.
     CO will pass its own configurable limit here (default 2 MB), so the agency can attach each part to Ecosys directly. Doing the split in DH (where you know per-declaration page sizes mid-render) is cleaner than CO re-parsing a finished PDF.

## Backward compatibility (hard requirement)
No quality, no max_part_bytes -> identical to the current shipped behaviour (single lossless application/pdf, same headers, same ordering). New headers (X-Render-Ms, X-Pdf-Bytes, X-Pdf-Parts) are additive.

## Open questions to answer back to CO
  1. What is the current dominant cost — the .xls->official-layout render, or the concatenation? (tells us whether caching alone fixes Problem 1).
  2. Do you already cache/persist any rendered declaration PDFs? If yes, can the merge reuse them?
  3. For quality=compact, what DPI / codec gives the smallest file that customs/Ecosys still accepts as legible? Propose a concrete profile.
  4. Confirm the split can stay on declaration boundaries at a 2 MB cap for a typical TKN (i.e. a single declaration is comfortably < 2 MB).

## Acceptance
  - quality=compact on the ~194-declaration set -> materially smaller X-Pdf-Bytes, still legible official layout, same page order/content.
  - max_part_bytes=2_000_000 -> application/zip of part-00N.pdf, every part <= 2 MB except declarations that alone exceed it (reported in X-Pdf-Oversize-Nos); parts concatenate back to the same content in order.
  - Warm cache (same declarations re-requested) -> X-Render-Ms drops sharply; X-Render-CacheHits > 0.
  - No new params -> unchanged response; existing tests still pass.

## Provider tests (add)
  - quality=compact: 200 application/pdf, X-Pdf-Bytes < print-profile bytes, golden legibility check vs the agreed compact profile (no data loss of declaration fields).
  - max_part_bytes set + output over limit: 200 application/zip, N parts each <= limit, deterministic names/order, parts reassemble to the same declarations; single oversize declaration -> own part + X-Pdf-Oversize-Nos.
  - max_part_bytes set + output under limit: single application/pdf (no zip).
  - Cache: first call renders all, second identical call hits cache -> X-Render-CacheHits == included count, lower X-Render-Ms.
  - No new params: byte-content-equivalent to pre-change output; ordering + X-Declarations-* headers unchanged.
  - Negatives unchanged (400 invalid_direction / declaration_nos_required / too_many / invalid_sort; 401/403/404).

## CO side (for context, no DH action)
CO holds the per-file limit as configurable app config (default 2 MB) and passes it as max_part_bytes; on a zip response CO drops the parts into the dossier's numbered tờ-khai slots. CO falls back to the current single-PDF behaviour on any DH error. CO has no PDF tooling, which is why size-reduction + splitting must live in DH.

After building, report: which caching strategy you used, the chosen compact profile (DPI/codec) and its measured size delta, the split behaviour at 2 MB, and the answers to the open questions above, so CO can verify end-to-end.
```
