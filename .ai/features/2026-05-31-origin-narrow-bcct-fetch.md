# Feature: Origin tab perf — eliminate the full BCCT pull

## Problem

Opening the **origin step** of a CO case triggers `co_case_source_context`'s
heavy path, whose dominant cost is `list_bcct(include_material_identity="true")`
paginating the client's **entire** customs history — 65 846 rows / ~37s for
Johnson (~66 round trips). That single call is ~36s of the ~65s origin load.

## Root finding: the stock half is unmigrated legacy

Git timeline:
- `co_stock_rows_from_bcct` (derive stock live from raw BCCT): **2026-04-28**
- `list_bcct` inside `co_case_source_context`: 2026-05-02 → 05-12 (DH consumer era)
- Materialized `co_stock_rows` snapshot subsystem: **2026-05-25** (later)

When the materialized snapshot landed (25/05), **only the calculate / "Load BOM"
path** was migrated to read from it (`_calculate_stock_rows_from_snapshot`,
main.py:6747 — reads `co_stock_rows` + delta-refresh-if-stale + ledger netting).
The **tab-load** `co_case_source_context` was never cleaned up — it still derives
stock the pre-25/05 way: pull all 66k BCCT live, run `co_stock_rows_from_bcct`.
The materialized table is literally the persisted output of that same function,
so the live re-derivation is redundant.

## What the full `list_bcct` feeds (3 consumers) — and the narrow/snapshot replacement for each

| Consumer | Direction | Needs full pull? | Replacement | Verified (Johnson, local DH) |
|---|---|---|---|---|
| `co_stock_rows_from_bcct` → `stock_rows` | import | **No** | Materialized `co_stock_rows` snapshot (same source calculate uses) | snapshot present: 60 173 rows; delta-refresh of a 2-day-stale snapshot = 0 changed rows in 0.15s |
| `enrich_invoice_matches_with_bcct` | export | **No** | `list_bcct_by_codes(<match item_codes>, direction="export")` | 826 rows, **0 field mismatch** vs full enrichment |
| `match_case_bcct_exports` (export-decl cases only) | export | **No** | `list_bcct(declaration_no=<case's export_declaration_nos>, direction="export")` | **43/43 rows exact** (0 missing/extra), 0.27s vs 35.87s |

**Conclusion: nothing in the origin source-context path requires a full BCCT
pull.** Every consumer has a narrow/snapshot equivalent, each empirically verified
to produce identical results. All three narrow endpoints (`by-codes`, `list_bcct`
with `declaration_no`/`direction` filters) already exist in the adapter and are
used elsewhere — no new Data Hub endpoint needed.

## CO stock cannot serve the export side (by design)

The materialized `co_stock_rows` table is **import-only** — `co_stock_rows_from_bcct`
skips every `direction != "import"` row (source_store.py:1222). CO stock = import
lots available for allocation; it holds zero export rows. So the two export
consumers (invoice-value enrichment, export-declaration matching) **cannot** read
from CO stock — that is a fundamental data boundary, not a gap to fill.

But export does **not** always hit DH either:
- After first computation, enriched invoice_matches are persisted on the case as
  `case["source_invoice_matches"]` (main.py:1274). The warm/snapshot path
  (`cached_origin_source_context`, used by calculate via `cached_case_context=True`)
  reads them straight from the case — **no DH/BCCT call** (main.py:1663).
- Only the **first cold load** of a case needs the narrow export fetch (~0.3s) to
  compute those values. Export declaration values are pure DH data — not derivable
  from import stock — so one narrow DH touch on cold load is unavoidable (and fine).

No separate "export materialization" is warranted: per-case persistence
(`source_invoice_matches`) already covers warm loads.

## Target architecture (converged)

| Path | Stock source | Export source |
|---|---|---|
| Tab-load origin (cold) | CO stock snapshot (delta-refresh if stale) | narrow export fetch (item_codes / declaration_no), then persist on case |
| Tab-load origin (warm) | CO stock snapshot | `case["source_invoice_matches"]` (no DH) |
| Calculate / Load BOM | CO stock snapshot + ledger (unchanged) | `case["source_invoice_matches"]` (unchanged) |

Net: tab-load and calculate read the **same** CO stock → preview matches the
computed result (consistency, which matters for a dossier app). Origin source-context
fetch drops from ~37s to sub-second. BOM workspace (~22s) becomes the next
bottleneck (separate task).

## Decisions

- **Converge tab-load onto the CO stock snapshot** rather than bolt a parallel
  live narrow-stock fetch onto it. The snapshot is already the authoritative
  source for the calculation (calculate path); making the preview use a different
  (live, gross) source would show numbers that diverge from the computed result.
  This is finishing the 25/05 migration, not inventing a new path.
- **Export stays a narrow DH fetch on cold load**, reusing existing adapter
  methods; persist on the case so warm loads need no DH.
- **Export-declaration cases**: narrow by `declaration_no`. Invoice-only cases:
  narrow by item_codes for enrichment. Both verified above.

## Risks

1. **RVC/LVC calculation parity (high — CLAUDE.md high-risk area).** The whole
   change must produce byte-identical origin results. Guard with an end-to-end
   parity assert: full-bcct path vs converged path on a real Johnson case must
   yield identical origin product RVC + identical `invoice_matches`. Run on real
   data, not stubs.
2. **Tab-load semantics change: stock gross→netted.** Tab-load currently shows
   live gross stock; the snapshot path applies ledger netting (used/remaining).
   This is the *desired* outcome (preview = computed result), but it is a
   behavioral change — add a preview-vs-calculate consistency test.
3. **`origin_build_signature` cache key (medium).** Signature hashes `stock_rows`;
   switching the source changes the hash → one-time cache invalidation (recompute
   once), then stable. Confirm warm-reopen reuse still works.
4. **Cold-start / DB dependency.** Empty snapshot or DB down → fall back to a
   one-time full pull (existing guarantee: never silently serve stale). The
   snapshot path already handles this; reuse it, don't reinvent.
5. **Server-side `declaration_no` filter normalization.** `match_case_bcct_exports`
   normalizes declaration tokens (`re.sub(r"[^A-Z0-9]","")`); confirm the DH
   `declaration_no` filter matches the same way so a formatting difference can't
   drop a row. (Verified equal on the one declaration tested; widen in TDD.)

## Deferred (next session)

- **CO stock freshness strategy.** Keep the snapshot fresh for tab-load:
  delta-refresh-on-access with a TTL (what calculate does; ~0.15s typical) and/or
  a scheduled/nightly delta refresh so the first cold access is warm. DH supports
  `since` (verified). Memory: `origin-costock-freshness-deferred`.

## Open items for /tdd

- Parity test FIRST (full vs converged path, real Johnson data): identical RVC +
  invoice_matches + signature stability.
- Confirm the cold-load export fetch + persistence flow yields the same
  `source_invoice_matches` the heavy path produced.
- Decide placement: a typed service method (keeps DH calls behind the adapter,
  testable) vs inlining in `co_case_light_context`'s origin branch.

## Benchmark harness

Bearer JWT via DH `/v1/auth/token` for `claude-check@local`, then
`curl -w %{time_total}` the `/origin` route. Component-level: call
`svc.co_case_source_context(...)` and the individual `list_bcct*` adapter methods
directly (as done during discovery). Prod case `johnson-vn / co-case-0605189d5eea`;
local invoice-only case `co-case-ec000d03522e` (invoice `VNG25120047`).
