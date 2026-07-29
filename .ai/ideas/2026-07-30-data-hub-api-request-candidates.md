# Data Hub API request candidates (ideation)

**Date:** 2026-07-30 · **Type:** ideation, no app-code changes · **Owner decision needed:** which of
these to promote to a formal `.ai/api-requests/YYYY-MM-DD-<slug>.md` + Data Hub contract approval.

Grounded in `app/data_hub_client.py` (current adapter), `.ai/BACKLOG.md`, `.ai/STATUS.md`, and the
existing `.ai/api-requests/` set. Per `CLAUDE.md` "Data Hub API Requests", none of these become CO
behavior until a request artifact is filed and Data Hub approves the contract; consumption stays in
`app/data_hub_client.py`.

All four candidates are **READ** (no mutation scope). The only mutation the adapter has today is
`submit_bom_proposal` (`data_hub_client.py:417`, POST `/v1/hub/products/{code}/bom/proposals`), which
is already shipped; nothing below adds a write.

## Do-not-duplicate: existing artifacts that already cover adjacent ground

- **DC1 customs_relevance / Material Group backfill** — already filed:
  `.ai/api-requests/2026-06-20-bom-observed-customs-relevance-coverage.md` (supersedes the 25-code
  hand-list `2026-06-09-johnson-bom-material-group-gap.md`). It is a DH-side **data backfill + a
  coverage block on `source-summary`**, not a new endpoint. Status: awaiting DH execution. Do **not**
  write a new artifact — see P3 below (nudge, not re-file).
- **BOM readiness / `latest_proposal_status`** — already filed:
  `.ai/api-requests/2026-06-20-bom-artifact-coverage-readiness.md` proposes a per-product
  `bom_readiness.latest_proposal_status` field that "mirrors any open CO proposal, see M1" (line 42).
  That partially pre-requests M1's DH surface — see P1.
- **Substitutes endpoint** — `.ai/api-requests/2026-05-11-bearer-aware-substitutes.md` is **FULFILLED**
  (DH shipped `GET /v1/hub/clients/{c}/materials/{m}/substitutes`, scope `hub:read`, 2026-05-13). P2
  is an **additive** ask on that live endpoint, not a new one.
- **BCCT by-codes** — `.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md` covers lookup by *material
  codes*. It does **not** cover lookup by a *set of declaration numbers* — that gap is P4.

---

## P1 — Confirm/extend the BOM proposal-status read (M1)

**CO use case.** Operator clicks "Propose BOM mới" on an origin sheet; CO POSTs the proposal and stores
`proposed_status` from the submit response. After Data Hub reviewers approve/reject the proposal, the CO
bảng kê still shows the stale submit-time status ("pending"/"submitted") forever, because CO never
re-reads it. When approved, CO should reflect that and be able to adopt the approved artifact as the
sheet BOM.

**Current gap (CO file:line hitting the wall).**
- CO writes the submit-time status once: `app/routers/co_case.py:2895-2897`
  (`proposed_artifact_id` / `proposed_proposal_id` / `proposed_status = result.get("status") or "submitted"`).
- Render only echoes the stored value, never re-reads DH:
  `app/web/co_case_context.py:1359-1367` (`state["proposed_status"] = proposed_status`).
- A read adapter already exists but has **0 callers**: `DataHubClient.get_bom_proposal(proposal_id)`
  → `GET /v1/hub/proposals/{proposal_id}` (`data_hub_client.py:440-441`,
  `HUB_PROPOSAL_PATH` at `:24`).

**Request shape.** Likely **no new endpoint** — verify the existing GET first.
```
GET /v1/hub/proposals/{proposal_id}
resp: {
  "proposal_id": "...",
  "product_code": "...",
  "status": "submitted|under_review|approved|rejected|superseded",  # must flip on DH review
  "adopted_artifact_id": "art_...",   # the artifact the approval produced/points to, or null
  "decided_at": "…", "decided_by": "…"
}
```
The two fields CO needs beyond a bare status echo: a **terminal status that transitions on DH-side
review**, and the **`adopted_artifact_id`** so CO can pull the approved BOM via the existing
`get_bom_artifact` (`data_hub_client.py:409`) and set it as the sheet's BOM.

**READ vs MUTATION.** READ, scope `hub:read`. No mutation — "adopt" is CO-side (read approved artifact,
set sheet BOM). The proposal write already happened via the existing `submit_bom_proposal`.

**Partial vs net-new.** **Partial contract.** The read endpoint exists; the customs-exchange-rates
artifact (line 9) lists "BOM versions/proposals" among approved endpoints, and the coverage-readiness
artifact already asks for a `latest_proposal_status` mirror. Net-new is at most **two additive fields**
(`adopted_artifact_id`, a review-driven `status`) *if* the current GET response lacks them.

**Verify before requesting anything.** Call `GET /v1/hub/proposals/{id}` against nightly (or check DH
sister-app-notes) and inspect the payload. If `status` already transitions on review and an adopted
artifact id is present → **no DH request needed, CO-side wiring only** (this matches the M1 backlog
downgrade: "sub-bug 1 no longer needs a DH API request"). If either is missing → file a small additive
request. Sub-bug 2 (the "Đã propose ✓" button re-POSTing, `co_case.html` `initOriginProposeBom`) is
purely CO-side and out of scope for any DH request.

**Backlog unblocked.** M1 (sub-bug 1). Also lets `bom_artifact_coverage_readiness`'s
`latest_proposal_status` field be consumed meaningfully.

---

## P2 — Feasibility/availability signal on substitute candidates (#4 ranking)

**CO use case.** The substitute modal ranks candidates by Data Hub's `combined_score`, which is
textual/HS similarity only. CO then fetches CO-stock async and re-sorts client-side. A candidate with a
high similarity score but **no usable stock** still sorts to the top and buries a slightly-lower-score
candidate that the operator could actually use. Backlog/STATUS call this the blended
**score + feasibility** ranking gap (#4).

**Current gap (CO file:line hitting the wall).**
- CO consumes only `combined_score` from DH and defaults the rest:
  `app/routers/co_case.py:2371-2374` (`"score": float(row.get("combined_score") …)`, plus
  `raw_scores`/`sources`/`confirmed`).
- Feasibility (stock) is bolted on **after** the DH call, CO-side and async:
  `empty_stock_summary()` placeholder at `co_case.py:2339-2348`, merged later via `/substitute-stock`;
  the initial sort is score-only except for CO-owned history pinning (`co_case.py:2520-2524`).
- STATUS.md:431-433: "a high-score-but-low-stock candidate gets buried … still DH-side. Needs
  `.ai/api-requests/` for a score+feasibility blended ranking from Data Hub."

**Request shape.** Additive fields on the **existing** substitutes response
(`GET /v1/hub/clients/{c}/materials/{m}/substitutes`, adapter `list_material_substitutes`
`data_hub_client.py:449`):
```json
{
  "material_b_code": "018.0644700",
  "combined_score": 0.91,
  "availability": {                     // NEW — the part DH can compute
    "has_import_bcct": true,            // candidate appears in import BCCT for this client
    "declared_qty": 12000,             // sum of declared import qty (gross, pre-CO-claim)
    "latest_import_date": "2026-05-…",
    "unit_price_band": {"min": "…", "max": "…", "currency": "USD"}
  },
  "blended_score": 0.87                  // OPTIONAL — DH's own score×availability blend
}
```
Boundary note: **CO net-of-claims remaining stock stays CO-side** — DH does not know CO locked-dossier
consumption (that lives in `co_stock` claims). DH can only supply the *import-availability* signal it
owns (BCCT). CO keeps the final feasibility re-sort net of claims; DH's job is to stop surfacing
zero-import candidates as if they were usable.

**READ vs MUTATION.** READ, scope `hub:read` (same as the fulfilled substitutes endpoint).

**Partial vs net-new.** **Partial contract** — additive fields on a live, already-approved endpoint.
`blended_score` is optional; the `availability` block is the load-bearing ask.

**Backlog unblocked.** #4 ranking (STATUS Next Step #1 / backlog "Ranking mã thay thế"). Complements the
already-shipped CO-side history pinning (`app/substitution_history.py`), which only floats
previously-used codes.

---

## P4 — Batch declaration-number filter on BCCT (the 524 narrow fetches made awkward)

**CO use case.** After the CO-524 fixes, the origin/export-declaration cold path fetches BCCT with a
**narrow per-declaration** filter instead of the full ~65k-row pull. But Data Hub's BCCT list filter
honours only the **singular** `declaration_no` (the plural form is ignored), so CO loops one HTTP call
per declaration. An export-declaration case with N declarations = N round-trips where one would do.

**Current gap (CO file:line hitting the wall).**
- The per-declaration loop and the reason for it, spelled out in the adapter docstring:
  `app/data_hub_client.py:972-983` — "the Data Hub bcct filter honours the singular `declaration_no`
  only (the plural form is ignored), so fetch one declaration at a time" — inside
  `DataHubPortfolioService.origin_invoice_matches`, calling `list_bcct(client, declaration_no=token,
  direction="export")` (`:980`) once per declaration.
- Same narrow fetch is also the subject of STATUS Next Step 00000(A) — but that follow-up
  (`include_material_identity="true"` parity) is **CO-side** (the param already exists on `list_bcct` /
  `list_bcct_by_codes`), so it is *not* a DH ask. The DH-side awkwardness is only the plural filter.

**Request shape.** Either a plural filter on the existing BCCT list, or a dedicated by-declarations
batch mirroring `bcct/by-codes`:
```
GET /v1/hub/bcct?client_id=…&direction=export&declaration_nos=A,B,C   # plural, capped (e.g. 500)
# or, mirroring the by-codes shape:
GET /v1/hub/clients/{client_id}/bcct/by-declarations?declaration_nos=A,B,C&direction=export
resp: { items: [ …bcct rows keyed by declaration… ], next_cursor }
```
CO would drop the per-declaration loop and call once; `match_case_bcct_exports` runs unchanged on the
merged rows.

**READ vs MUTATION.** READ, scope `hub:read`.

**Partial vs net-new.** **Net-new** — no existing artifact covers declaration-set filtering
(`by-codes` is material-code-scoped). Low urgency: the current loop is correct and no longer 524s; this
is a round-trip / latency optimization on the export-declaration cold window.

**Backlog unblocked.** CO-524 residual (STATUS 00000) and export-declaration cold-open latency; reduces
fan-out in `origin_invoice_matches`.

---

## P3 — DC1 customs_relevance / Material Group backfill (already filed — nudge, do not re-file)

**CO use case.** Johnson "rác" rows (drawings/checklists/labels in the `bom_observed` group, ~1,207
codes) come back `customs_relevance=null`, so CO's auto-exclude/fold has nothing to act on and the rác
reaches the bảng kê until an operator deletes it by hand. CO already reads `customs_relevance` and keeps
no local heuristic (correct default per DC1).

**Current gap.** Not a contract gap — a **data-completeness** gap. CO consumes the field already
(`app/origin_material_filters.py`, `is_bom_technical_noise`; export skips at
`app/bang_ke_renderer.py:259`, `app/workbook_io.py:617`, `app/bang_ke_xml_generator.py:391`). The fix is
DH re-ingesting SAP Material Group for the `bom_observed` group.

**Request shape.** Already written:
`.ai/api-requests/2026-06-20-bom-observed-customs-relevance-coverage.md` — backfill + a
`customs_relevance_coverage` block on `source-summary`. No new artifact.

**READ vs MUTATION.** READ / DH-side data job, scope `hub:read`. No CO mutation.

**Partial vs net-new.** **Already filed**, awaiting DH execution. The only action is to nudge DH to run
the `bom_observed` backfill (and, optionally, ship the coverage block so CO can render a
"% NVL classified" health badge). Ranked last here because there is nothing new to *decide* — the
decision was made and the request is on file.

**Backlog unblocked.** DC1 (and, by extension, DC3b's pre-mig-078 rác leak once coverage rises).

---

## Ranking summary

| # | Candidate | Backlog | Read/Mut | Contract status | New DH work needed |
|---|---|---|---|---|---|
| P1 | BOM proposal-status read/adopt | M1 | READ `hub:read` | Partial (endpoint exists) | Verify GET payload; at most 2 additive fields — maybe zero |
| P2 | Substitute feasibility/availability fields | #4 | READ `hub:read` | Partial (live endpoint) | Additive `availability` block (+ optional `blended_score`) |
| P4 | Batch declaration-number BCCT filter | CO-524 residual | READ `hub:read` | Net-new | Plural `declaration_nos` filter or `bcct/by-declarations` |
| P3 | customs_relevance / Material Group backfill | DC1 | READ `hub:read` | Already filed | None new — DH executes the on-file backfill |

**Recommended order to promote to formal requests:** P1 (verify first — may need no request), then P2
(clear value, additive on a live endpoint), then P4 (clean net-new, modest value). P3 needs no new
artifact — nudge DH to execute the existing one.
