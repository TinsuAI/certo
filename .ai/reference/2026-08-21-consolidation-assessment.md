# Architecture assessment — consolidating Data Hub into CO

Date: 2026-08-21. Written in response to the directive: merge the two systems into one new
repo, stop splitting data into Data Hub, simplify wherever possible, and make the app respond
like the Excel workbook it replaced.

All numbers below are measured or read from the source at HEAD (`f6519f6`). Estimates are
marked.

---

## 1. Verdict

**Merge: yes.** The split costs more than it returns. But merge for the right reason —
it removes a large amount of code and machinery, not because it is the main source of the lag.

**New repo built from scratch: no.** Migrate the existing app and its tests into the new repo.
The 27,220 lines of CO tests are the only written record of the domain rules (trừ-lùi folding,
`customs_relevance` semantics, the claim lifecycle, the export == web-grid invariant, RVC
parity with the workbook). A from-zero rewrite discards them and re-introduces exactly the
"lỗi logic" being complained about.

**"Responsive like Excel" is not delivered by the merge.** It is delivered by two other
changes that must be named as their own phases: storing derived state instead of recomputing
it per request, and holding the bảng kê grid in browser memory instead of re-rendering it
server-side on every action. Details in §4.

---

## 2. What is actually there today

| | CO (`barry-CO-main`) | Data Hub (`data-hub`) |
|---|---|---|
| App code | 33,200 LOC Python | 37,955 LOC Python |
| Tests | 27,220 LOC / 121 files / 1,182 tests | — |
| Postgres | 37 tables, 22 migrations | 93 migrations, needs pgvector |
| Templates | 26 Jinja files, `co_case.html` = 7,600 lines | own template set |
| Frontend | hand-written vanilla JS, 32 `fetch()` calls in one template, no framework | — |
| Prod runtime | `uvicorn --workers 1` — one event loop per container | — |

Coupling points:

- CO consumes **16** Data Hub endpoints through `app/data_hub_client.py` — **60 KB** of
  pagination, envelope handling, row normalization, and config partitioning that exists only
  because the boundary exists.
- **Data Hub is CO's identity provider.** `DATA_HUB_ISSUER_URL` / `DATA_HUB_JWKS_URL` in
  `docker-compose.yml`; `app/co_auth.py` verifies Data Hub–issued JWTs; Data Hub owns
  `jwt_issuer.py` (313 LOC), `app/auth/session.py`, and the SSO code/refresh stores.
- A `tinsu-shared` external Docker network exists solely so CO can call Data Hub by an
  internal alias while keeping the issuer on the public URL.
- Process ceremony: `.ai/api-requests/`, a template, "stop and ask for Data Hub-side contract
  approval", and `tests/test_data_hub_policy.py` which fails if a raw `/v1/hub` string appears
  outside the adapter.

### The finding that matters most

`app/portfolio.py:247` selects between **two complete implementations of the same service
interface**:

- `DataHubPortfolioService` — HTTP to Data Hub. **This is what production runs.**
- `PortfolioService` — local stores. Reachable only with `CO_ALLOW_LOCAL_SOURCE=1`
  (tests and offline dev).

The local side is backed by `source_store.py`, `source_index_store.py`,
`source_index_records.py`, `source_workbook_io.py`, `source_postgres_store.py`,
`bom_store.py`, `bom_service.py`, `bom_workbook_io.py`, `bom_default_store.py`,
`source_index_cli.py` — **5,255 LOC that production never executes.** CO's own Postgres
carries `bcct_rows`, `source_catalog_rows`, `source_snapshots`, `bom_versions` and friends for
that dead path.

Every behaviour therefore has two implementations that can drift, and the suite largely
exercises the one production does not use (5 test files touch the local source store; 22 touch
the Data Hub path). That is a structural cause of "fix đi, fix lại mà vẫn lỗi logic" —
independent of any performance question.

---

## 3. Measured latency, and what the merge changes

From `.ai/reference/2026-07-30-cold-open-perf-audit.md`, measured in-container against prod
`johnson-vn` (~65k BCCT rows, ~13k materials):

| Path | Cost | Cause |
|---|---|---|
| Shipment tab (cold) | 124.88s → **0.31s** | fixed by narrowing the call, not by removing HTTP |
| Substitute modal (cold) | ~125s → **15.69s** | still a full `list_materials` pagination |
| Case-list index | **4.27s** | N+1: one `claims_summary_for_case` query per dossier |
| First `/calculate` | **2.6s** | JSONB snapshot deserialize |
| Origin tab (warm click) | **0.3–1.1s** | the render funnel, not Data Hub |

Read the first row carefully. The 124.88s stall was removed by fetching less, with the HTTP
boundary still in place. That is the evidence that the boundary is not the dominant cost.

**What the merge converts:**

- 15.69s catalog pull → one indexed `SELECT` (sub-second) `[estimate]`
- 2.6s snapshot deserialize → a query against real rows `[estimate]`
- 4.27s index N+1 → a single grouped query (already fixable today, branch exists)

**What the merge does not touch:** the 0.3–1.1s warm click. That is `co_case_context`
rebuilding the whole case context and Jinja rendering a 7,600-line template. Excel is instant
because the sheet is resident in memory and recalculation is incremental. A server round trip
that rebuilds derived state cannot match that regardless of where the data lives.

---

## 4. Three separate causes. The merge addresses one.

1. **Data boundary** — whole corpora pulled over paginated HTTP. → Merge fixes this.
2. **Compute model** — derived state (names, `customs_relevance`, stock rows, readiness,
   criteria rows) recomputed on every render instead of stored. → Merge does not fix this.
   Fix = materialize into the snapshot; `R1` in the perf audit already specifies it.
3. **UI model** — every operator action is a server round trip that re-renders the case.
   → Merge does not fix this. Fix = the bảng kê grid holds its rows in browser memory; the
   server is called for load, calculate, and save-delta only.

Delivering only (1) lands the merge and leaves the app feeling the same. That is the failure
mode to avoid.

---

## 5. Recommended shape

New repo. Migrate, do not rewrite. Concretely:

- Port Data Hub's `app/stores/`, `app/parsers/`, `app/flatten/`, `app/resolvers/` in as
  internal modules of the new app.
- **Keep `data_hub_client.py`'s function surface intact and swap its body** from HTTP
  pagination to direct store calls. CO's 1,182 tests keep passing from day one, and the
  adapter/normalization layer is then deleted incrementally rather than atomically.
- Delete `PortfolioService` and the 5,255 LOC local-store path. One implementation, one code
  path, tests exercising what production runs.
- Retire CO's duplicate source tables in favour of the Data Hub schema (which must come across
  with pgvector — `list_material_substitutes` is on the consumed list).
- Retire the JSON blob stores. `data/local` is 1.1 GB: `source-modules/` 978 MB (a 93 MB
  `bcct/state.json` plus ten 88 MB versioned copies), `co-cases/clients/growatt/cases.json`
  22 MB. Reading or writing a store means parsing and rewriting the whole blob. Leaving these
  in place leaves latency source #2 in place.

### Phases

| # | Phase | Delivers |
|---|---|---|
| 0 | New repo; both schemas **dumped and restored** into one Postgres (pgvector image) | one DB holding the real corpus |
| 1 | Data Hub **stores + parsers + flatten + uploads + proposals** in-process behind the unchanged adapter surface | 15.69s → sub-second; ingestion moves with it; tests still green |
| 2 | Delete `PortfolioService`, the adapter internals, the policy test, the API-request process | ~5,255 + ~60 KB of code removed; one code path |
| 3 | Own auth: plain server sessions, login, permissions (new code) | JWT / JWKS / SSO machinery deleted |
| 4 | Materialize derived state into the snapshot | removes the per-render recompute |
| 5 | Client-side bảng kê grid on a grid library (§7) | the Excel-like response |
| 6 | Deploy cutover, retire `tinsu-shared` and the issuer/JWKS split | one deployment |

Phases 0–2 are mechanical and test-guarded. Phase 3 is genuinely new code. Phases 4–5 are
where the responsiveness comes from — do not stop before them.

Two things the phase-1 line understates:

- **It is not only a read-path swap.** Swapping `data_hub_client.py`'s body covers the 16 read
  endpoints. Ingestion is routes + templates + static + upload storage + the mapping-flow and
  proposal screens, so phase 1 also mounts Data Hub's web UI into the merged FastAPI app.
  Expect route-prefix, static-path, and template-name collisions to resolve.
- **Data Hub's tests migrate too.** 162 files, **39,355 LOC** — larger than CO's suite. The
  migrate-don't-rewrite argument applies identically: the 4,772 LOC of customs-declaration
  parsers are guarded by those tests the way trừ-lùi is guarded by CO's. Porting them is part
  of phase 1's deliverable, not a follow-up.

Combined, the merged repo starts at roughly **71,000 LOC of app code and 66,500 LOC of tests**,
before phase 2 deletes anything.

---

## 6. Decisions — settled 2026-08-21

All five were put to the user. Answers recorded here; the phase table in §5 stands.

| # | Decision | Chosen |
|---|---|---|
| 6.1 | Auth | **Plain server sessions.** Drop JWT entirely. |
| 6.2 | Ingestion | **Move everything in phase 1.** No transition window. |
| 6.3 | Other consumers | No live consumer found; one prod check before phase 0. |
| 6.4 | Dead paths | **Delete `PortfolioService` + local stores** and **retire the JSON blob stores into Postgres.** |
| 6.5 | Scope | **All phases 0–6**, with a grid library for the sheet (§7). |

Not selected, still open: retiring CO's duplicate `source_*` / `bcct_rows` tables. Deleting
`PortfolioService` orphans them, so this is a follow-on cleanup inside phase 2 rather than a
separate decision — raise it again when phase 2 starts.

### Detail behind each



**6.1 Auth.** Absorbing Data Hub kills CO's identity provider. The merged app needs its own
login, session, and permission layer — written, not moved. Options: port Data Hub's
`jwt_issuer.py` + `auth/` into the merged app and keep issuing to itself, or drop JWT entirely
and use plain server sessions since there is no longer a second service to authenticate to.
The second is simpler and I would recommend it, but it changes the SSO story if any other app
logs in through Data Hub.

**6.2 Ingestion.** CO reads 16 endpoints, but the corpus behind them is produced by Data Hub's
upload, parser, mapping-flow, and proposal screens (`app/routes/uploads.py`,
`app/parsers/` 4,772 LOC, `app/routes/proposals.py`). If those screens do not move, the merged
app serves a corpus that goes stale at the next customs declaration. Move them in phase 1, or
keep Data Hub running as ingest-only during a transition window?

**6.3 Other consumers — settled, CO is the only live one.** Queried the production registry
(`hub.service_accounts` on `data-hub-db-1`, read-only):

| name | scopes | last_used_at |
|---|---|---|
| `co-prod` | `hub:read`, `bom:propose` | 2026-08-21 01:44 UTC |
| `bcqt-prod` | `hub:read` | **never** |

`bcqt-prod` was provisioned but has never made a call, and none of `bcqt-ai-agent`,
`bcqt-dothanh`, `bcqt-growatt`, `bcqt-showcase` contains a reference to Data Hub. Nothing
outside CO depends on the API, so absorbing it breaks no live consumer.

**6.4 File stores.** Confirm the JSON blob stores are retired into Postgres rather than carried
across. Carrying them across keeps a known latency source.

**6.5 Cutover.** The current repo's push-to-main triggers production CD. The new repo needs its
own CI/CD and compose, and the cutover must be sequenced so both do not deploy against the same
data.

---

## 7. Grid library for the bảng kê (phase 5)

The bảng kê is an editable data grid with server-computed columns and operator overrides — not
a formula surface. Column values come from `/calculate`; the operator edits and overrides
cells. So the requirement is a **data grid with Excel input ergonomics**, not a spreadsheet
engine.

What the sheet needs: virtual scrolling (Johnson sheets run to thousands of rows), in-cell
editing, keyboard navigation, rectangular range selection, clipboard copy/paste of ranges,
a fill handle, and per-cell styling so overrides and folded rác rows stay visually distinct.

| Option | Licence | Range select + fill handle | Fit |
|---|---|---|---|
| **RevoGrid Core** | MIT | in the free core | Web component — drops into the existing Jinja templates with no build step or framework |
| AG Grid Community | MIT | **Enterprise only** ($999/dev/yr) | Largest project, best documented; the Excel ergonomics are behind the paid tier |
| Handsontable | commercial licence required | yes | Most Excel-like, but this is a paid client project so the licence is a real cost |
| Univer | Apache-2.0 | yes, full spreadsheet semantics | Correct only if the sheet later needs real formulas; heavier than the job requires today |

**Recommendation: RevoGrid Core.** It is the only option that is MIT *and* ships the
Excel-style range selection, clipboard, and fill handle, and being a web component it fits an
app with no framework and no bundler. The tradeoff is honest: it is a much smaller project
than AG Grid, so fewer answered questions and a smaller contributor base. If that risk is not
acceptable, the fallback is AG Grid Community plus one Enterprise seat.

Two constraints this phase must not break, both already established in the codebase:

- **Export == web grid.** The bảng kê export is a pure renderer of the web grid; no logic in
  the export step. A client-side grid must therefore send back exactly the state the export
  reads.
- **Override history survives save.** `override_history` / redo are per-sheet and carried
  server-side through `attach_origin_sheet_states` plus the `/undo` and `/redo` routes. A
  client-side undo stack has to stay the view over that, not replace it.

---

## 8. What I would not do

- Do not patch the remaining nine blocking `async def` handlers one by one first. That work is
  superseded by phase 1 — once the Data Hub call is a local query, the blocking window is
  milliseconds and the `asyncio.to_thread` wrappers become noise.
- Do not rewrite the domain logic. Port it with its tests. The RVC calculation, trừ-lùi
  folding, and bảng kê export parity were paid for once already.
