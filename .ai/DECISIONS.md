# Architecture Decisions

<!-- Format:
## [Date] Decision Title
**Context:** Why this decision was needed
**Decision:** What was decided
**Alternatives:** What else was considered
**Consequences:** What this means going forward
-->

## [2026-04-15] Defer Application Stack Until Discovery Completes
**Context:** The user asked for project bootstrap in the sense of metadata and data exploration, not immediate application scaffolding.
**Decision:** Do not commit to a web application stack yet; keep the repo focused on archive extraction, project context, and data discovery.
**Alternatives:** Scaffold a frontend or backend before understanding the data and workflow.
**Consequences:** The next architecture decision should be made against the actual CO process and dataset, not against a guessed UI stack.

## [2026-04-15] Discovery Is File-System Backed First
**Context:** The only reliable source material today is the agency archive, including spreadsheets, PDFs, ZIPs, and RARs.
**Decision:** Treat `data/extracted/CO` as the discovery source of truth for the bootstrap phase instead of inventing seed data or introducing a database immediately.
**Alternatives:** Start with mock data, or design the full relational model before reading the real files.
**Consequences:** Planning stays anchored to the actual case structure, but the next phase must normalize spreadsheet and document metadata into app-owned entities.

## [2026-04-15] Use JS-Based RAR Extraction
**Context:** The environment does not include a native `unrar` binary, but the supplied archive set contains multiple `.rar` bundles that are part of active and completed cases.
**Decision:** Add `node-unrar-js` and provide a local extraction script.
**Alternatives:** Leave RAR files opaque, depend on manual extraction outside the repo, or install platform-specific native tooling.
**Consequences:** Discovery remains reproducible within the project, and future ingestion flows can reuse the same JS-based archive support.

## [2026-04-27] Use FastAPI/Jinja For First CO Demo Shell
**Context:** The user asked for a working demo webapp for preparing a simple C/O case, with BCQT-System as the reference implementation style.
**Decision:** Add a small FastAPI/Jinja demo app in this repo for the first C/O preparation surface. This is a demo shell decision, not a final production architecture decision.
**Alternatives:** Continue with Node-only scripts, or scaffold a larger frontend/backend stack before validating the C/O workflow.
**Consequences:** The demo can reuse the same operational UI pattern as BCQT-System while keeping the final database/auth/deploy decisions open.

## [2026-06-17] Consolidate worktree split → single standalone repo
**Context:** Two confusing CO folders under `/home/vp/workspace/client/`: `barry-CO` (the main git working tree that held the canonical `.git`, but was stuck on a stale April branch `case/growatt-rvc-20260421` with uncommitted experiment scripts) and `barry-CO-main` (a linked worktree carrying all active `main` work). The real `.git` lived in the stale folder — backwards and confusing.
**Decision:** Re-init `barry-CO-main` as a standalone repo from `origin` (TinsuAI/co — `main` was fully pushed), preserving working tree + `.env` + the `data` symlink in place; repoint upstream to `origin/main`; then delete `barry-CO`.
**Alternatives:** Fresh clone into a new folder (loses local-only `.env`/`data`/uncommitted `.ai`); manual git-pointer surgery (riskier); leave the split.
**Consequences / RECOVERY POINTERS:**
- `barry-CO`'s uncommitted experiment scripts → saved on origin branch **`case/growatt-rvc-20260421`** @ `26b6476`. Recover: `git fetch origin case/growatt-rvc-20260421 && git checkout case/growatt-rvc-20260421`.
- Deleted `barry-CO` was the old predecessor checkout; all committed content is the shared repo history already on origin (same repo) — nothing unique lost beyond the branch above.
- Earlier this session: **CO cases + claims fully purged (dev + prod, all clients)**. Restorable backups at `barry-CO-bom-data/local/backups/full-purge-20260615-032608/` — dev (`db_cases_claims.sql`, `claim_events.csv`, `db_supporting_files.sql`, `cases-json/`, `uploads-growatt-vn/`) + `prod/` (`db_cases_claims.sql`, `claim_events.csv`, `co-cases-files.tar.gz`). Stock (`co_stock_rows`) was NOT purged. Restore via `psql` (dev local socket; prod `docker exec -i co-db-1 psql -U co -d barry_co`).
- `barry-CO-main` is now standalone (own `.git`, single remote `origin`); no worktree split remains.

## [2026-07-08] BOM version precedence: honour the pin, not the newest
**Context:** A sheet auto-calculates against a product BOM version chosen by a precedence chain. The chain was duplicated in two functions that had drifted: `attach_case_bom_snapshot` (`bom_store.py`) ran first with a 3-step chain (no client-default step) and *wrote* `product.bom_product_artifact_id`; `selected_bom_rows_by_product` (`co_case_context.py`) then read that already-written field as its step 1, so its own client-default step never fired. Effect: staff pin v1 as the client default, DH publishes v2 → the sheet silently calculates v2, the ★ sits on the unselected v1. The written field is load-bearing (the version dropdown's `selected` value and the "có BOM" badges read it), so "just stop pre-pinning" is not viable.
**Decision:** Precedence is **explicit pin (case override) > client default > DH aggregate composition > DH latest usable**. A pinned/client-default version is honoured even after DH publishes a newer one — newest does NOT auto-win. Enforce it through **one** resolver `resolve_selected_product_version(product, …) -> (version, source)` called by both the snapshot writer and the per-sheet selector; it also returns `source` (which step won) to drive the picker's "why" label.
**Alternatives:** (a) Latest-wins — auto-adopt DH's newest published version; rejected because it makes an explicit pin meaningless and breaks trừ-lùi determinism. (b) Narrow patch — add the missing client-default step to `attach_case_bom_snapshot` only; rejected because two copies of an 8-step chain will drift again.
**Consequences:** Existing live cases whose client-default differs from DH-latest will start calculating the *pinned* version (the intended correction; locked/snapshotted cases are frozen, unaffected). The unified resolver is the seam the #1b batch BOM-selection picker builds on (provenance label comes free).

## [2026-07-08] Substitute discovery is stock-first; stock-sourced substitutes are declarable
**Context:** The substitute picker discovers candidates from DH substitutes + DH catalog + CO history, then annotates them with stock; it never builds candidates FROM stock. So an NVL in stock but absent from the DH catalog is invisible and cannot be substituted. A prior handoff (#3) claimed such stock-only codes would be `declarable_unmatched` and blocked by the DC3c lock/export guard, and proposed flagging them + a reverse "register in Data Hub" flow as a precondition. Re-checking the code: `declarable_unmatched` is a **Data-Hub catalog classification** (`customs_relevance == "declarable_unmatched"` = "real, declarable, but no BCCT import match"); CO only echoes it, never manufactures it, and an unclassified material is KEPT not dropped (`origin_material_filters.py`). A substitute sourced from `co_stock_rows` has a BCCT import match by construction (stock IS materialised import lots carrying hs/CIF/customs_item_code), so it is the opposite of unmatched.
**Decision:** Flip discovery to **stock-first ⟕ catalog**: build candidates from the CO-stock snapshot grouped at the logical-material grain (`allocation_code` when resolved, else `customs_item_code`), LEFT-JOIN the catalog for name/HS/origin enrichment, dedup against the DH "Khuyến nghị" list, order stock-first (not a hard filter — catalog-no-stock stays visible, dimmed). A stock-sourced substitute is **fully declarable with NO blocker flag**: build its material row from the stock lot's own name/HS/unit_value; the catalog join only enriches. Missing origin_status defaults conservative (non_origin), safe for LVC.
**Alternatives:** (a) Handoff #3's flag-and-block + reverse-DH-registration-as-precondition — rejected: mis-scoped `declarable_unmatched` (wrong polarity); imported/warehoused goods are declarable by construction. (b) Hard filter to only-in-stock in search — rejected: loses the ability to see catalog-only materials. (c) Special-case the rare DH-vs-stock contradiction (a stocked code DH classifies as unmatched/rác) — deferred: flipping "stock evidence beats DH classification" is a trust-model change, out of scope; keep trusting DH, surface via the existing review row (→ BACKLOG).
**Consequences:** stock-only NVL become findable and substitutable; #3 (the deferred compliance nuance) largely dissolves; the reverse "missing-material → Data Hub" flow, if built later, is a name-normalisation convenience, not a C/O-issuance precondition.
