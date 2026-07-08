# Feature spec: BOM-selection picker (#1) + substitute-search source (#2)

Grilled 2026-07-08 (`/grill-with-docs`) from the two agreed-but-unbuilt design
items in `.ai/sessions/2026-07-08-batch-tong-hop-tab-bom-catalog-review.md`.
Branch `feat/co-flow-guards`. Domain terms live in `.ai/GLOSSARY.md`; the two
hard-to-reverse calls are ADRs in `.ai/DECISIONS.md` (2026-07-08 ×2).

---

## #1 — BOM-selection for batch (correctness bug + picker)

### 1a — precedence bug (fix FIRST, affects calculations)
The version-selection precedence chain is **duplicated and drifted** across two
functions:

- `attach_case_bom_snapshot` (`app/bom_store.py:786-818`) runs first in every
  origin context build, uses a **3-step** chain `bom_product_artifact_id →
  overrides → composition` (**no client-default step**), and **writes**
  `product["bom_product_artifact_id"]`.
- `selected_bom_rows_by_product` (`app/web/co_case_context.py:1585-1594`) has the
  full **8-step** chain *including* `client_defaults`, but its step 1 reads the
  field the snapshot writer already populated → steps 5–6 (client default) never
  fire.

Effect: staff pin v1 as client default, DH publishes v2 → sheet auto-calculates
**v2**, ★ sits on unselected v1. The written field is **load-bearing** (read at
`co_case.html:959` "có BOM", `:1129` dropdown `selected`, `:1820`, `:2318-2320`
build overrides), so "just stop pre-pinning" is **not** viable.

**Fix (ADR):** extract **one** resolver, called by BOTH functions:
```
resolve_selected_product_version(product, overrides, client_defaults,
                                 composition, bom_workspace) -> (version, source)
```
- Precedence: **explicit pin (case override) > client default > DH aggregate
  composition > DH latest usable**. A pinned/client-default version is honoured
  even after DH publishes a newer one — newest does NOT auto-win.
- `source ∈ {pin, case_override, client_default, dh_composition, dh_latest}` — the
  provenance that drives #1b's "why" label (comes free from the unify).
- Include `bom_product_code` alias resolution (already in the 8-step chain).

### 1b — the picker (UX)
Surface a per-SP BOM-version control in the **batch Review dashboard** row.

- **Persistence:** reuse existing stores, no new store. Dropdown pick →
  `bom_product_artifact_overrides` (**case override**, this dossier only).
- **★ (client default) is NOT in the batch view** (decision Q2 = A). It mutates
  cross-dossier state; keep it in the detailed per-SP tab where it is today
  (`co_case.html:1183`, `6126`). Adding ★ to batch later is non-breaking.
- **"why" label** from `source` (decision Q3a):
  - `case_override` → **"#N · bạn chọn"**
  - `client_default` → **"#N · mặc định khách"**
  - `dh_latest` → **"#N · mới nhất · chưa ghim"** + subtle amber highlight (this
    is the blast radius of the 1a bug — staff must SEE which SP ride auto-latest).
  - Always show the label; only `dh_latest` is highlighted.
- **No-BOM SP** (decision Q3b): no usable version → render no dropdown; keep the
  existing "chưa có BOM" state (`no_bom_products`). Picker appears only when the
  SP has ≥1 usable version.
- **Timing** (decision Q3c): changing the dropdown does **not** auto-recalc (30 SP
  × recalc = costly/janky). It writes the case-override + marks the sheet stale;
  numbers update on **"Tính tồn tất cả"** (server-authoritative, existing batch
  pattern). The "why" label updates immediately client-side.
- **Batch picker modal (built 2026-07-08):** clicking "Tính tồn tất cả (SP)" opens a
  per-SP BOM-version table (dropdown cloned from the existing per-SP select + the
  "why" chip); confirm applies the picks and runs the batch calc. Reuses
  `compactOriginRequest` (reads each panel's `[data-bom-version-select]`), no new
  persistence path.
- **Only-deliberate-picks-become-overrides (save-mirror-leak fix, 2026-07-08):** the
  echo `product.bom_product_artifact_id` (written by `attach_case_bom_snapshot` for
  rendering) is indistinguishable from a genuine pick, so `compactOriginPayload`
  used to persist an override for **every** SP on save — silently pinning the whole
  lô and freezing unpinned SPs against future default changes. Fix: the panel now
  carries `data-bom-source` + `data-bom-resolved-version` (from `bom_version_pick`);
  `compactOriginPayload` sends a version as a pick **only** when it deviates from the
  resolved default OR was already a `case_override`. An SP left at its auto-resolved
  value sends `""` → neither client nor server pins it → it keeps tracking the
  precedence chain. Verified in-browser: unchanged amber SP stays unpinned; a
  deliberate change becomes an override; existing pins persist.

---

## #2 — substitute-search source (stock-first ⟕ catalog)

### The gap (verified)
Neither "Khuyến nghị" (`portfolio_service.list_material_substitutes` → HS-heuristic
→ CO history) nor "Tìm kiếm" (`portfolio_service.search_materials` +
this-dossier rows) builds candidates FROM stock — stock is only fetched *lazily*
to annotate already-discovered candidates (`/substitute-stock`,
`co_case.py:2482`). So an NVL **in stock but not in the DH catalog is invisible**
to discovery. The stock-lookup machinery already matches on all three stock keys
(`co_stock_key_candidates`, `co_case.py:2516`); the gap is **discovery only**.

### Design (decisions Q4–Q6)
- **Candidate identity = `allocation_code` when `resolved`** (one row per logical
  NVL, tồn aggregated across its declared lots), falling back to
  `customs_item_code` when unresolved. Grouping is display-only. Rationale:
  substitution is chosen at the logical-material grain, which is exactly the grain
  the whole calc/allocation system already operates at (pool is keyed
  material-level; FIFO + eligibility auto-select lots within a material). For
  `same_as_customs_code` clients (Johnson + default) allocation_code == customs
  code = 1:1 so it is moot; for `growatt` (`description_regex`) it can gather
  several declared lots — matching the existing grain adds no new risk. Per-lot
  (mã HQ) steering, if ever needed, is a **system-wide** gap, not #2's job.
  (`material_code` in stock rows is just a copy of `allocation_code` —
  `co_stock_derivation.py:53` — not a third identity.)
- **Discovery = stock-first ⟕ catalog:** build candidates from
  `read_co_stock_rows_cached` (grouped by identity above), **LEFT JOIN** the
  catalog by ANY of the candidate's keys for name/HS/customs_relevance /
  origin_status. Dedup against "Khuyến nghị" (same identity → merge, mark "có tồn
  N"). Keep DH "Khuyến nghị" as the quality-ranked complement.
- **Search = stock-first ORDERING, not a hard filter** (decision Q5): one list,
  có-tồn candidates on top (badge "tồn N"), catalog-matches-with-no-stock still
  shown below, dimmed + "không còn tồn". Nothing that is searchable today becomes
  invisible.
- **Stock-sourced substitutes are fully declarable — NO blocker flag** (decision
  Q6, corrects handoff #3): `declarable_unmatched` is a DH catalog classification
  ("real, declarable, but NO BCCT import match"), NOT "missing catalog metadata".
  A stock code has a BCCT import match *by construction* (stock IS materialised
  import lots carrying hs/CIF/customs_item_code); absent from catalog →
  `customs_relevance` empty → `is_declarable_unmatched` False → not blocked. Build
  the substitute's material row from the **stock lot's** name/HS/unit_value; the
  catalog join only enriches (canonical name, origin_status). Missing
  origin_status defaults conservative (non_origin) → safe for LVC. Đã nhập kho =
  đã khai = khai báo được.

### Deferred (Q6 residual, → BACKLOG)
The rare DH-vs-stock contradiction: a code that IS in the catalog AND classified
`declarable_unmatched`/`excluded_non_material` there, yet also has stock. Current
policy "CO trusts DH classification" → DC3c still blocks; surface via the existing
`declarable_unmatched` review row; fix = DH-side map edit. NOT special-cased in
#2. Flipping "stock evidence beats DH classification" is a trust-model change,
out of scope. (This code isn't stock-*only* — it comes through the catalog flow
anyway, so #2 doesn't introduce it.)

---

## Seams & slices for `/tdd`

1. **#1a — resolver unify (correctness).** ✅ **DONE 2026-07-08.**
   `resolve_selected_product_version(product, *, overrides, client_defaults,
   composition_ids, version_index, bom_workspace, bom_product_code,
   honor_product_pin) -> (version, source)` in `app/bom_store.py`; both
   `attach_case_bom_snapshot` and `selected_bom_rows_by_product` (via
   `_bom_selection_inputs`) call it. Tests `tests/test_bom_selection_resolver.py`:
   snapshot pins client-default over composition (the bug); +5 existing precedence
   tests still green.
2. **#1b — batch picker data + provenance.** ✅ **BACKEND + LABEL DONE 2026-07-08.**
   `selected_bom_versions_by_product` → `{code: {version_id, version_no, source,
   usable}}` (honor_product_pin=False so the snapshot echo never masquerades as a
   pick). `attach_bom_version_picks` attaches `product.bom_version_pick`
   (+`source_label`, `unpinned`) — VIEW-only, not persisted, not in
   `origin_case_revision`. Template: provenance chip `.bom-version-why` next to the
   per-SP version dropdown, amber `.is-unpinned` for `dh_*`. Tests: source taxonomy
   (client_default / case_override / dh_composition) + snapshot-echo ignored.
   **Pending:** the full batch **Review-dashboard inline dropdown** relayout + the
   no-recalc-on-change / feeds-"Tính tồn tất cả" wiring (the chip surfaces
   provenance today on the existing per-SP toolbar; the dedicated batch picker row
   is the remaining UI). Live browser render needs a logged-in DH-BOM case.
3. **#2 — stock-first discovery.** ✅ **BACKEND + ROUTE DONE 2026-07-08.**
   `app/substitute_discovery.py::build_stock_first_candidates` (pure): group by
   `stock_row_identity` (allocation_code resolved → else customs_item_code),
   LEFT-JOIN catalog, metadata from the lot, `stock_only` display flag (no
   blocker), stock-first ordering, exclude/query. Wired into the substitute
   candidates route search branch (stock-first results prepended, catalog-no-stock
   kept dimmed via `stock_first: False`). 7 tests in
   `tests/test_substitute_discovery.py`. **Pending:** modal UI (stock-first badges
   / dimming / `stock_only` "⚠ chưa đăng ký catalog" chip) — the data now flows;
   the front-end presentation of the flag/dimming is the remaining UI.

**Verification (2026-07-08):** full suite **741 pass / 15 skip** (was 729; +12
new); `co_case.html` compiles with the app's real Jinja filters. **Live browser
e2e (Playwright + system chromium, auth toggled off then restored) against real
growatt-vn `e2e-batch-real`:**
- #1b — origin sheet view renders the provenance chip **`#1 · bạn chọn`** (×3,
  `case_override`) next to the version dropdown; screenshot
  `.ai/screenshots/2026-07-08-bom-substitute-e2e/bom-version-why-chip.png`. Unpinned
  `dh_composition` → "mới nhất · chưa ghim" verified in-process.
- #2 — the substitute-candidates route (`?search=DIENTRO`) returns 4 stock-first
  candidates (`stock_first=True, stock_only=True`, real tồn, ordered by remaining)
  that the catalog search alone never finds — 638 distinct stock candidates
  discoverable for growatt-vn. NOTE: the chip currently lives on the **per-SP sheet
  toolbar** (visible in sheet view), not yet the batch Review-dashboard row.

Suggested next: finish the two **UI** pendings (batch picker row; modal badges),
then `/code-review` against fixed point `840fb74` before a PR to `main`.
