# Session 2026-07-16/17 — #14 CO-owned client config + material/lot code-vocabulary dictionary

Design + docs only. **No code changed.** All changes uncommitted on local `main`
(`.ai/DECISIONS.md`, `.ai/GLOSSARY.md`, new `.ai/features/2026-07-16-…`); 5 issues on
GitHub `TinsuAI/co`.

## What Was Done

1. **`/grill-with-docs` on #14** (growatt-vn allocation strategy hard-defaults to
   `same_as_customs_code` in DH source-mode → technical BOMs match no on-spot lots).
2. **Empirically settled the root cause** against the live DH Postgres
   (`postgresql:///data_hub?host=/var/run/postgresql`, schema `hub`), not by inference:
   - growatt-vn lots embed the internal code in `goods_name` parentheses, e.g.
     `DIOT#&Đi ốt 16V~100V (008.0006100)`; the `customs_code` column is the short
     declared code (`DIOT`) that `same_as_customs_code` keys on.
   - Applying the real regex `\(([A-Z0-9][A-Z0-9._/-]{3,})\)` to all 38,287 growatt-vn
     import lots vs the 2,236 distinct published BOM `material_code`s:
     **`same_as_customs_code` = 101/2,236 (4.5%)**, **`description_regex` = 2,145/2,236 (96%)**.
   - `material_identity.internal_code` is null on **0/38,287** rows, so the
     `resolve_allocation_code` short-circuit (`client_config_store.py:126`) is inert.
   - Verified the code path: `normalize_bcct_row:1163` maps DH `goods_name` → CO
     `description`, which the regex runs on. It is a config problem, not a keyspace
     problem. **Option 3 (reseed with customs-coded BOMs) is dead.**
3. **Wrote the ADR** `.ai/DECISIONS.md` [2026-07-16] "Client config ownership is
   partitioned…".
4. **Wrote the spec** `.ai/features/2026-07-16-co-owned-client-config-allocation.md`
   (slices S1–S4).
5. **Wrote the code-vocabulary dictionary** — `.ai/GLOSSARY.md` new "Material & lot
   codes" section (7-concept model + identity-vs-derived rule) and new "Runtime modes"
   section (Axis-1 source backend, Axis-2 persistence, DH `code_resolution_mode`).
6. **Ran a 3-agent code-vocabulary audit** (declared/customs identity family; internal/
   material/BOM family; allocation_code derived family) + an **independent logic review**
   that re-derived every load-bearing claim from code and re-ran the DB numbers — all
   CONFIRMED, numbers reproduced to the digit.
7. **Filed 5 GitHub issues** (`TinsuAI/co`) from the audit — see Open Items.

## Decisions Made

- **#14 fix = CO-side, via ownership-partition (SUPERSEDES the old STATUS "option 2:
  CO-side allocation override on client overlay").** Do NOT build a new
  `bang_ke_overrides`-style blob. Instead: **DH owns the `bcct` section (declaration
  types); CO owns `allocation_code` + `co_stock`**, persisted through the EXISTING local
  `client_configs` store (`app_state_store.py:96-144`, already has validation + versioning
  + hash). In DH source-mode: `get_client_config` = local saved config as base + DH's
  `bcct` overlaid; `save_client_config` writes the CO-owned sections locally instead of
  raising.
- **Rejected Option A** (add `allocation_code` to DH's client-config + API): it's a
  CO-derivation parameter no DH consumer reads, and decays to a fallback if DH ever
  resolves `material_identity` — a two-repo contract is the wrong cost.
- **Rejected gap-filler precedence** (DH wins the day it sends `allocation_code`): a
  future DH backfill would set the `same_as_customs_code` default and silently revert
  growatt-vn from 96% to 4.5% via a deploy in the *other* repo, no error either side.
  Ownership-partition (local-authoritative for CO sections) fails safe.
- **S3 is mandatory and must fingerprint BOTH CO-owned sections.** A config change
  touches no DH source row, so the delta refresh (`co_case_context.py:3672`) re-derives
  nothing and the 60k snapshot keeps stale codes → the fix silently no-ops. Add a
  `co_config_fingerprint` column to `co_stock_refresh_state` hashing `allocation_code` +
  `co_stock` (covers the `line_level → manual_review` lot_policy case the review caught),
  force full on mismatch. **NOT** keyed on `config_hash` (unstable in DH mode —
  `default_config` restamps `updated_at` every call, `co_stock_materializer.py:194`).
- **Dictionary canonical names:** identity = `customs_item_code`; material = `material_code`
  (+ keep `internal_code` distinct); product = `product_code`; keep `material_identity`,
  `bom_code`, `allocation_code`. Persisted-column renames (T5) intentionally skipped —
  guard the overloads with invariant tests + docs instead.

## What Didn't Work / Corrected

- The first-draft #14 plan (a new `allocation_overrides` blob + gap-filler precedence)
  was **overturned by the Fable design review + the independent logic review**: the blob
  reinvents the `client_configs` store; gap-filler is unsafe against a DH backfill.
- Two glossary lines were **wrong and fixed**: "item_code … For Johnson/Growatt it equals
  the internal NVL code" (true for Johnson, FALSE for growatt-vn) and a stale
  `co_case_context.py:1896` reference (now `:1952`).
- Booting the full DH+CO stack for a UI Tính was unnecessary (and Docker is unavailable in
  WSL) — the DB-level re-derivation with the production regex is faithful and quantified.
- The two audit agents disagreed on the claim `material_code`; **resolved**: the claim
  ledger is sound (keys on `source_row` + the stable BOM `material_code`, `co_stock_ledger.py:54-71`);
  the one real mutable-key exposure is `allocation_line_matches_stock:1097` (→ issue #18).

## Open Items

- **Issues on `TinsuAI/co` (code-vocab refactor batch):**
  - **#18 (T0)** — `allocation_line_matches_stock:1097` vetoes a saved allocation line's
    rebind when `allocation_code` re-derives; a strategy change orphans saved lines.
    growatt-vn safe today (no saved cases). `ready-for-agent`+`bug`, linked to #14.
    **Must land before any strategy change on a client with saved cases.**
  - **#19 (T2)** — safe in-memory helper renames + return-shape unification. `ready-for-agent`.
  - **#20 (T3)** — invariant tests (claim.customs_code == lot.customs_item_code;
    stock-row material_code == allocation_code) + adapter-boundary docs. `ready-for-agent`.
  - **#21 (T4)** — allocation_code `_source`/`_confidence`/`_status` value cleanup.
    **Blocked by #14** (rides S3 re-derivation). `ready-for-agent`.
  - **#22 (T6)** — DH→CO normalization fallback investigation (behavior-risk).
    `needs-triage` — needs a keep/tighten/remove decision per case before an agent takes it.
  - **T5 (persisted-column renames) intentionally NOT filed** (skip; guard via #20 instead).
- **#14 itself is spec'd but not implemented.** `/implement` the S1–S4 slices; then seed
  growatt-vn `allocation_code.strategy = description_regex` through the new save path (the
  current path raises in DH+DB prod).
- **Reusable lessons (offered, not yet written to the knowledge base):** (1) gap-filler
  precedence for a config value another system may later backfill with a default is unsafe
  — the backfill silently reverts; (2) a mutable/derived value persisted and used as a
  match key orphans saved references on a config change.
- Uncommitted docs on local `main` (`.ai/DECISIONS.md`, `.ai/GLOSSARY.md`, the new spec) —
  commit when convenient; no code, docs-only.
