# Session: Origin perf — discovery, BCCT-pull elimination design

2026-05-31

Discovery-only session (no code changes). Picks up STATUS Next Steps #2 (origin
tab = the dominant bottleneck after the shipment fix). Produced a verified design
to remove the full BCCT pull from the origin path. Output: feature brief
`.ai/features/2026-05-31-origin-narrow-bcct-fetch.md` (title: "eliminate the full
BCCT pull"). Next session: `/tdd`.

## What Was Done

`/discover` on the origin ~37s load, then four rounds of empirical probing
against the local DH (:8754) on real Johnson data. Every claim below was measured,
not assumed.

1. **Located the cost.** `co_case_source_context` heavy path →
   `list_bcct(include_material_identity="true")` paginates all 65 846 rows / ~37s
   for Johnson. This single call is ~36s of the ~65s origin load.

2. **Identified the 3 consumers of the full BCCT pull** and a verified
   narrow/snapshot replacement for each:
   | Consumer | Dir | Replacement | Verified |
   |---|---|---|---|
   | `co_stock_rows_from_bcct`→`stock_rows` | import | materialized `co_stock_rows` snapshot | snapshot has 60 173 rows; 2-day-stale delta = 0 rows / 0.15s |
   | `enrich_invoice_matches_with_bcct` | export | `list_bcct_by_codes(item_codes, "export")` | 826 rows, **0 field mismatch** vs full |
   | `match_case_bcct_exports` | export | `list_bcct(declaration_no=…, "export")` | **43/43 exact**, 0.27s vs 35.87s |
   → **Nothing requires a full pull.** All 3 narrow endpoints already exist in the
   adapter; no new DH endpoint needed.

3. **Git-confirmed the stock half is unmigrated legacy.** `co_stock_rows_from_bcct`
   = 2026-04-28; materialized `co_stock_rows` subsystem = 2026-05-25. Only the
   calculate/"Load BOM" path (`_calculate_stock_rows_from_snapshot`, main.py:6747)
   was migrated to the snapshot; tab-load `co_case_source_context` still does the
   pre-25/05 live full pull. The materialized table IS the persisted output of
   that function — the live re-derivation is redundant.

4. **Resolved the export question.** CO stock is **import-only** (source_store.py:1222
   skips `direction != import`), so it cannot serve export. But export doesn't always
   hit DH: enriched invoice_matches are persisted on the case
   (`case["source_invoice_matches"]`, main.py:1274) and the warm/snapshot path
   (`cached_origin_source_context`, main.py:1663) reads them with no DH call. Only
   the FIRST cold load needs the narrow export fetch (~0.3s). No export
   materialization needed.

## Decisions Made

- **Converge tab-load onto the CO stock snapshot** (the source calculate already
  uses), NOT bolt a parallel live narrow-stock fetch onto tab-load. Rationale: the
  authoritative number comes from the snapshot (calculate); a live-gross preview
  would diverge from the computed result — bad for a dossier app. This is finishing
  the 25/05 migration, not inventing a path.
- **Initially proposed** a 2-fetch live narrow design (`list_bcct_by_codes` import +
  export). **Reversed** after the user pushed: "bảng kê must compute against CO
  stock; if stale is a problem, solve it at the CO Stock layer." Correct — the live
  approach's "always fresh" advantage is illusory because calculate isn't live
  either. Converging is the right architecture.
- **Export stays a narrow DH fetch on cold load**, persisted on the case so warm
  loads need no DH. Export-decl cases narrow by `declaration_no`; invoice cases
  narrow by item_codes for enrichment.
- **Freshness strategy deferred** to next session (memory:
  `origin-costock-freshness-deferred`). NOT a blocker: refresh-on-access already
  lives in `_calculate_stock_rows_from_snapshot` (delta-if-stale + fallback); reuse
  it and tab-load inherits it. Deferred part = optional scheduled refresh only.

## What Didn't Work / corrected mid-session

- First benchmark used prod case `co-case-0605189d5eea`, which is NOT in the local
  CO store (it's a prod case) → KeyError. Switched to local Johnson case
  `co-case-ec000d03522e` (invoice `VNG25120047`, no export decls).
- I over-advocated the snapshot approach in round 1, then over-corrected back to
  narrow-fetch in round 2. The user's "solve staleness at the CO stock layer"
  framing settled it: converge on snapshot. Lesson captured in the brief's
  Decisions section.
- Probe scripts run with `PYTHONPATH=.` (bare `uv run python` → `ModuleNotFoundError:
  app`). `.env` must be loaded manually in standalone probes (app doesn't auto-load
  it outside the server).

## Open Items — all in the brief, sequenced for /tdd

1. **Parity test FIRST** (real Johnson data): full-bcct path vs converged path →
   identical RVC + invoice_matches + `origin_build_signature` stability.
2. Converge `co_case_light_context` origin branch onto `_calculate_stock_rows_from_snapshot`
   (or a typed service method) for stock; narrow export fetch + persist on case for
   the cold load.
3. 5 risks to guard (brief §Risks): RVC parity, gross→netted semantics change,
   signature cache one-time invalidation, cold-start/DB fallback, `declaration_no`
   filter normalization (`re.sub([^A-Z0-9])`).
4. Deferred: CO stock freshness strategy (scheduled refresh).

## State at Handoff

- Branch `main`, clean except untracked `.ai/features/2026-05-31-origin-narrow-bcct-fetch.md`.
  No code changes. Prod unaffected.
- Servers up: CO :8001, local DH :8754 (both healthy). May need restart next session.
- Memory added: `origin-costock-freshness-deferred` (+ MEMORY.md index).
- Timing instrumentation `[origin-timing]` mentioned in prior STATUS — not touched
  this session; verify whether still present before shipping.
