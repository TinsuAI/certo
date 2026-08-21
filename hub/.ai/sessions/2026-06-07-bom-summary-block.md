# Session 2026-06-07 (PM) — BOM summary block on `/source-summary` + F.1 close

## What Was Done

### 1. Backlog review (answered "what's left to do")
Read `.ai/BACKLOG.md` + `STATUS.md`. Summarized open items by theme +
readiness. Flagged F.1 as likely-already-shipped (per memory
`project_reingest_pending.md`).

### 2. Closed backlog F.1 (Growatt bulk re-ingest) — COMMITTED `d16743c`
Verified against HEAD: BCCT onboard 2026-05-28 (`ccbb3ad`), BOM wipe +
re-ingest 2026-05-29 (`03e9c4b`, 823 artifacts local+demo, 1260 tests).
The backlog entry was stale. Moved F.1 to SHIPPED with full record +
removed obsolete "Growatt remains pending" note on the Johnson entry.

### 3. BOM summary block on `/source-summary` (CO request) — UNCOMMITTED
Fulfills `barry-CO-main/.ai/api-requests/2026-06-07-products-total-count.md`
(the lighter "alternative" path). `GET /v1/hub/dncxs/{client_id}/source-summary`
now returns a `bom` block:
```json
"bom": {
  "exported_with_bom", "exported_without_bom", "exported_total",   // headline
  "product_count", "stale_count", "multi_version_count", "last_published_at"  // secondary
}
```
Files: `app/stores/bom.py` (`company_bom_summary`), `app/routes/api.py`
(wire block), `tests/test_read_api_auth.py` (+1 seeded test + empty-case
asserts; 1390 passed), `docs/API_CONTRACT.md` + `docs/API_CHANGELOG.md`
(Additive entry + caveats), `.ai/BACKLOG.md` (C.4 deferred),
`.ai/sister-app-notes/2026-06-07-bom-summary-block-available.md` + INDEX.

### 4. Produced a ready-to-paste CO consumer prompt
In-conversation prompt instructing the CO-side agent to wire
`data_hub_client.py` + `client_context.py` + `routers/bom.py:bom_context`
to read `summary["bom"]`, headline `exported_with_bom / exported_total`,
with feature-detect fallback. Regenerate from the sister-app note if lost.

## Decisions Made

- **Headline = export trio, NOT a catalog-category count.** Checked real
  local data first. `product_count` is inflated by BTP sub-assemblies
  (Johnson 3605 = 574 TP + 3031 BTP; derive_btp_shallows mints a BOM per
  intermediate BTP). Strict `category='tp'` undercounts badly (Growatt
  catalog tags finished-ish codes `btp_sx` or leaves them uncategorized
  → only 7 of 171). The export trio — distinct BCCT export `customs_code`s
  ∩ has-BOM — is category-independent and matches what CO actually
  certifies. Real values: Growatt 20/63, Johnson 574/651.
- **`with + without == total`** invariant: compute `exported_total` +
  `exported_with_bom`, derive `without` by subtraction (guarantees
  consistency).
- **Kept `product_count` as a secondary/internal-coverage metric**, not
  dropped — it's free and gives the BTP-inclusive picture. Documented
  explicitly as NOT a finished-product count.
- **Dropped `tp_with_bom`/`tp_total`** (catalog-category dependent,
  misleading) and **`flattened_ready`/`not_flattened`** (materialize
  always yields a flattened shape → `not_flattened` is uniformly 0 →
  zero signal today). These were in an earlier draft of the block.
- **`/products` total+pagination → DEFERRED (backlog C.4).** The store
  already supports it; route-wiring only. CO doesn't need product
  enumeration yet — the dashboard headline is served by the `bom` block
  with no extra round-trip. Avoided shipping an unneeded contract change.
- **Did NOT touch `barry-CO-main`** (audit-only rule). Coordination via
  sister-app note + the handed-over prompt only.
- **Caveat surfaced to CO:** export trio matches `customs_code` exactly →
  blind to NB codes inside `goods_name` parens (backlog A.5). Documented
  as an approximation, not an absolute/compliance count.

## What Didn't Work

- **First-draft block shape** (`product_count` as headline +
  `tp_with_bom`/`tp_total` + `flattened_ready`/`not_flattened`) was built
  and tested, then revised after a real-data smoke exposed the BTP
  inflation + strict-tp undercount + always-zero `not_flattened`. The
  store function and tests were rewritten to the export-trio shape. Lesson:
  smoke aggregates against real Growatt/Johnson data BEFORE finalizing the
  field set — the "obvious" count was the wrong one.

## Open Items

- **Commit + push** the `bom` block (push = prod deploy). CO can't see the
  field until deployed.
- **CO consumer** not yet shipped — prompt handed over; awaiting their PR.
  They should fill the Approval + Data Hub commit fields in their
  api-request file once done.
- **C.4** (`/products` total+pagination) deferred — pull out when a
  consumer needs full product enumeration.
- Repo hygiene: several pre-existing untracked files/sessions unrelated to
  this work (see STATUS Next Steps #6).
