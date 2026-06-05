# Feature: Upload mapping flow overhaul (BCCT-first, shared)

Status: ALL PHASES SHIPPED (2026-06-05). Phase 0 hotfix (cache fix +
pending discard, dev DB) · Phase 2 anomaly net `f58c42a` · Phase 1
auto-map `81adc4b` · Phase 4 LLM prompt `834ac99` · Phase 3 per-client
column config + admin UI + mig 075 `21f2a23` · screenshots `121c0a4` ·
Phase 5 no-header positional mapping (this commit). Full suite 1336 passed.
Not yet deployed to prod.

Phase 5 (no-header files): parser `positional_override` (0-based col index
→ field, data from row 1, no row consumed as header); mapping page picker
gains a "— Không có header —" option (value 0) → route maps by column
position and skips the per-shape cache. Solves the headerless case where
the first data row was previously eaten as a header (1 of N rows lost).

## Problem / incident

`shape=flat`-style rigid alias mapping works, but EVERY cache-miss upload
is routed to a manual mapping page where a human can mis-confirm. On
2026-06-05 a staff user swapped `Đơn giá`→`unit_price` and
`Đơn giá tính thuế`→`unit_price_nt` (backwards vs canonical mig-039
semantics: `unit_price`=VND taxable, `unit_price_nt`=nguyên tệ). The
rigid auto-match had it RIGHT; the human override was cached, so every
re-upload of that file shape produced inverted prices → diff showed 67
rows "changing" against correct DB data. Nothing was committed (caught at
preview), but the flow has no guardrail against a confirmed-but-wrong
mapping.

BCCT columns are highly uniform (ECUS/VNACCS exports). Target experience:
mapping is near-automatic; staff focus only on the **Diff**, not on column
mapping.

## Scope

IN (4 phases, generic across bcct/catalog/bqd/bom where sensible):

1. **Auto-map on cache miss.** Run rigid (`_rigid_match_header` over
   `ALIASES` + client config). If ALL `required_mapped_fields` resolve with
   no ambiguity AND no blocking anomaly → parse and go straight to the Diff
   preview; cache the mapping as `proposed_by='auto'`. Only show the manual
   mapping page when a required field is unresolved or a column is
   ambiguous. Cache-hit path unchanged.

2. **Anomaly/validation layer (non-blocking warnings in preview).**
   Pluggable per-module validators producing `summary.warnings[]`:
   - BCCT price/value magnitude: for rows with `currency_nt`≠VND, expect
     `unit_price ≈ unit_price_nt × exchange_rate` and `unit_price ≥
     unit_price_nt` (same for `total_value`/`_nt`). Inversion → "nghi đảo
     cột đơn giá/trị giá".
   - Mapping deviates from rigid-canonical on a known column → warn.
   These would have caught today's swap. Surfaced in
   `bcct_upload_preview.html` next to the diff; advisory, not a hard block
   (open Q4).

3. **Per-client column alias config, editable in Web UI.** New table
   `hub.client_column_aliases (client_id, module, field, alias, enabled,
   …)`. Match resolution order: client aliases → code `ALIASES` (global
   default). Admin UI to view/add/disable aliases per (client, module).
   Empty config ⇒ identical to today (code ALIASES). No per-client bulk
   seed migration — code stays the default.

4. **Smarter LLM (only for unresolved headers).** Improve
   `propose_header_mapping`: prompt carries field DEFINITIONS (VND "tính
   thuế" vs nguyên tệ), sends sample VALUES + `exchange_rate` so magnitude
   disambiguates unit_price vs unit_price_nt; model returns confidence and
   ABSTAINS (leave unmapped, flag for human) instead of guessing. Call LLM
   only for headers the rigid + client-config layer couldn't resolve.

OUT: changing the diff/confirm/ingest semantics; changing
`parser_mappings` per-shape cache contract; sister-app (CO/BCQT) changes
(this is hub-internal ingest config, not a read-API contract).

## Decisions

- **Diff preview stays the universal safety net.** Auto-map removes the
  human mapping step, NOT the human Diff review. Every upload still lands
  on the preview-confirm page.
- **`client_column_aliases` is distinct from `parser_mappings`.** Aliases =
  reusable per-client header→field knowledge; parser_mappings = per-exact-
  file-shape confirmed cache. Keep both; aliases feed the rigid matcher,
  the cache short-circuits repeat shapes.
- **Validators are module-pluggable.** Magnitude check is BCCT-specific
  (price/value domains). Register validators per module so catalog/bqd/bom
  don't run price checks.
- **No data backfill.** DB BCCT values are correct; only the cached mapping
  was wrong (already fixed).

## Risks

- **Auto-map silently applies a wrong mapping** for an unusual client file.
  Mitigation: Phase 2 anomaly warnings + always-on Diff. Open Q1: still
  force the mapping page on a client+module's FIRST-EVER upload?
- **False-positive anomaly warnings** annoy staff → ignored. Needs a
  tolerance band + only warn on clear inversion. Tune on real Johnson/
  Growatt data.
- **Schema migration** (new table) — hub-internal, low cross-app risk;
  follow numbered-migration convention (next after 074).
- **LLM contract change** (confidence/abstain) — keep
  `propose_header_mapping` return back-compatible (dict header→field);
  surface confidence via a parallel structure, not a breaking change.
- **Generic vs BCCT-specific** — auto-map + config + LLM are generic;
  validators are per-module. Don't leak BCCT price logic into shared code.

## Decisions resolved (2026-06-05)

1. **Auto-map skips the mapping page even on first-ever upload** when all
   required fields resolve with no ambiguity. Diff + anomaly net are the
   safety. (No "confirm once per new client" step.)
2. Magnitude tolerance: start with ratio band [0.5, 2.0] of expected,
   tune on real data. "≠VND" = `currency_nt` set and not VND/VND-aliases.
3. Column-config UI = **per-client overrides only**; global `ALIASES`
   stays in code as default. (No global-edit UI.)
4. Anomaly handling is **two-tier**: minor anomalies = advisory warning;
   a CLEAR inversion (e.g. unit_price↔unit_price_nt) = **hard gate**,
   requires an explicit ack checkbox (`confirm_anomalies`) before commit,
   same pattern as `confirm_diffs`/`confirm_orphans`.

## Suggested build order (TDD per phase)

Phase 2 (anomaly net) → Phase 1 (auto-map) → Phase 4 (LLM) → Phase 3
(config table + admin UI). Rationale: land the guardrail before removing
the human mapping step; Phase 3 (schema+UI) is the heaviest and least
urgent. Each phase: tests first → implement → `/rev` → commit. UI proof
(mapping page skip, preview warnings, admin config) committed under this
feature folder's `screenshots/`.

## Done criteria

- Uniform BCCT re-upload with a known shape never shows the mapping page;
  lands on Diff.
- A swapped unit_price/unit_price_nt upload raises a preview warning
  (regression test reproducing the 2026-06-05 incident).
- Per-client alias added via UI changes rigid resolution without a code
  change.
- LLM is invoked only for genuinely unresolved headers and abstains on
  low confidence (test with a deliberately ambiguous header).
- Catalog/BQD/BOM uploads unaffected (no price validators run); all
  existing mapping/preview tests still green.
