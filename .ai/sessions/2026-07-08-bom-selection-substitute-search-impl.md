# Session handoff — 2026-07-08 (PM)

Grilled the two agreed design items (#1 BOM-selection, #2 substitute-search) with
`/grill-with-docs`, then implemented BOTH test-first, then iterated the UI from live
manual testing. **All work UNCOMMITTED on `feat/co-flow-guards`.** Suite **741 pass /
15 skip** (was 729; +12 new). Branch base for review: **`840fb74`**.

---

## What the grill decided (→ domain docs, all written this session)
- `.ai/GLOSSARY.md` — 8 terms: BOM version precedence, case-override vs client-default,
  `source`/provenance, **item_code/customs_item_code**, **allocation_code** (CO-derived,
  mutable, `resolved`/`unresolved`), stock-key-candidates, substitute-candidate identity,
  **declarable_unmatched** (polarity clarified — see below).
- `.ai/DECISIONS.md` — 2 ADRs (2026-07-08): (1) BOM precedence = **honour the pin, not
  the newest** (override > client-default > DH composition > DH latest); (2) substitute
  discovery is **stock-first**, stock-sourced substitutes are **declarable, no blocker**.
- `.ai/features/2026-07-08-bom-selection-and-substitute-search.md` — full spec + slice
  status + verification log.

**Key correction the user caught mid-grill:** `declarable_unmatched` is a *Data-Hub
catalog classification* ("real material, NO BCCT import match"), NOT "missing catalog
metadata". A stock-sourced substitute has an import match **by construction** → it is the
opposite of unmatched → NOT blocked by DC3c. Build its row from the **stock lot's**
name/HS/value; catalog join is enrichment only. This dissolved the deferred #3 concern.

---

## Built + verified this session (all UNCOMMITTED)
- **#1a — precedence bug fix (correctness).** Extracted one resolver
  `resolve_selected_product_version(...) -> (version, source)` in `app/bom_store.py`;
  BOTH `attach_case_bom_snapshot` and `selected_bom_rows_by_product` (via
  `_bom_selection_inputs`) call it. Adds the missing client-default step to the snapshot
  writer (was shadowing it). Tests: `tests/test_bom_selection_resolver.py`.
- **#1b — provenance + batch picker.** `selected_bom_versions_by_product` (honor_product_pin
  =False → echo never masquerades as a pick) + `attach_bom_version_picks` →
  `product.bom_version_pick` (view-only, not persisted, not in `origin_case_revision`).
  Chip `.bom-version-why` on the per-SP toolbar (amber `.is-unpinned` for `dh_*`).
  **Batch BOM-selection modal** opens on "Tính tồn tất cả (SP)" → per-SP version table →
  confirm runs the calc (reuses `compactOriginRequest`, no new persistence).
- **#1b — save-mirror-leak fix (from manual-test feedback).** The echo
  `product.bom_product_artifact_id` used to be persisted as an override for **every** SP on
  batch save (silently pinning the whole lô). Now the panel carries `data-bom-source` +
  `data-bom-resolved-version`; `compactOriginPayload` sends a version as a pick **only** if
  it deviates from the resolved default OR was already a `case_override` — else `""` (neither
  client nor server pins it). Verified in-browser both directions (unchanged stays unpinned;
  a real change becomes an override; existing pins persist).
- **#2 — stock-first discovery.** `app/substitute_discovery.py::build_stock_first_candidates`
  (pure, 7 tests): group by `stock_row_identity` (allocation_code resolved → else
  customs_item_code), LEFT-JOIN catalog, metadata from the lot, `stock_only` display flag
  (no blocker), stock-first ordering, exclude/query. Wired into the substitute-candidates
  route search branch (stock-first prepended; catalog-no-stock kept, `stock_first:false`).
- **#2 — smart lots collapse (from manual-test feedback).** Substitute modal now shows the
  first 3 lots + a "▾ Xem tất cả N lô" toggle (`collapseLotsTable`) so a many-lot NVL
  doesn't flood the panel.

**Verification:** suite 741; `co_case.html` compiles with the app's real Jinja filters.
Live browser e2e (Playwright + system chromium, auth toggled off then restored) on real
`growatt-vn` `e2e-batch-real`: chip renders ("#1 · bạn chọn" ×2, "mới nhất · chưa ghim"
amber ×1), batch modal opens (3 SP, 0 JS error), stock-first search returns 638 real stock
candidates (DIENTRO/điện trở…), override-intent fix confirmed via captured POST payloads.
Screenshots: `.ai/screenshots/2026-07-08-bom-substitute-e2e/`.

---

## NEXT SESSION — user's explicit ask
**Review the batch-flow logic carefully: does it correctly handle preparing MULTIPLE
dossiers for the SAME company?** The batch feature so far is validated per-single-dossier;
the cross-dossier (client-wide) correctness is the open question.

Concrete review agenda (things that could break with 2+ dossiers per client):
- **Cross-dossier stock contention.** Stock (`co_stock_rows`) is client-wide; a LOCKED
  dossier holds `co_stock_claims`. Dossier B's *available* stock must subtract dossier A's
  locked claims. Check the claims overlay at read time: `co_stock_ledger`,
  `_calculate_stock_rows_from_snapshot` (claims overlay `co_case_context.py:~3373`),
  `record_sheet_lock_claims` (`co_case.py:177` → `co_stock_ledger.py:150`), and the
  `FOR UPDATE … order by source_row` overclaim guard (StockOverclaimError).
- **Does batch `calculate-all` / the shared per-material pool account for OTHER cases'
  claims?** The whole-case pool (`case_allocation_pool`, `prepare_case_origin_products`) is
  per-CASE; confirm it overlays cross-case locked claims (or that preview is advisory and
  lock re-checks — R5 preview↔commit drift).
- **`/substitute-stock` + stock-first discovery** read the client-wide snapshot
  (`read_co_stock_rows_cached`) — confirm the tồn they show is net of other dossiers' claims
  (or clearly "gross tồn, advisory").
- **Client-scoped signals are shared across dossiers by design** (client-default BOM store,
  substitution-history) — verify that's intended, not a leak between dossiers.
- **Same-case double-count note** (already logged): `used_qty_by_lot` missing case filter
  (`co_stock_ledger.py:491`) — conservative, not over-claim; re-confirm under multi-dossier.

Suggested skills next: `/diagnosing-bugs` if a concrete cross-dossier discrepancy shows up;
`/code-review` against `840fb74` before any PR. Consider a multi-dossier e2e seed (extend
`.ai/scripts/e2e_batch_real_seed.py`) that locks dossier A then calculates dossier B.

---

## Pending UI polish (data flows; front-end only)
- #1b: the batch **modal** covers the "choose BOM per SP" flow; a dedicated inline picker
  row in the Review dashboard is still optional (chip already shows provenance per SP).
- #2: substitute modal has no stock-first **badges** / catalog-no-stock **dimming** /
  `stock_only` "⚠ chưa đăng ký catalog" chip yet — the `stock_first`/`stock_only` flags are
  in the JSON, only the presentation is missing.

## Environment / cleanup done
- Dev server `:8001` restored to `CO_AUTH_REQUIRED=1` (auth on); `devctl restart co` done.
- `e2e-batch-real` (growatt-vn) restored: INV-3000 re-pinned to `ba_o3m17lCoy3IhokGJ`.
- Playwright uninstalled (was added ad-hoc for e2e). Scratch scripts removed.
- Nothing committed. Commit/PR English, no AI trailer (user rule). `840fb74..HEAD` unmerged.
