# Project Status

**Date:** 2026-05-07 PM — BCCT product identity resolver + catalog roles refactor

## Current State

Two large features shipped end-to-end this session, on top of the morning's
Phase 3 work. Both have sister-app notes posted; CO and BCQT can begin
consumer migration.

- **Repo HEAD**: `7792cdd` on `main` — **NOT YET PUSHED**. 8 commits ahead
  of origin/main (3 BCCT identity + 2 catalog roles + 2 round-2 fixes +
  earlier handoff doc commit).
- **Tests**: 606 pass / 15 skip / 1 pre-existing fail (`test_co_columns`
  real-data, untouched).
- **Local DB v3 state**:
  - Growatt: 451 materials, 23,080 BCCT, 207 distinct BOM products.
    Resolution rate post-shipping: **22,333 / 23,080 = 96.8%**.
    275 NVL roles observed (was 47 before NVL-relax mig 034).
  - Johnson: 11,129 materials, 52,224 BCCT, 99.9% resolution.
  - Other clients unchanged.
- **Demo URL**: https://ttdatahub.tinsu.ai (CI/CD picks up after push).

### Features shipped (this session)

| Feature | Commits | Tests |
|---|---|---|
| BCCT product identity resolver (mig 032 + resolver + ingest+API+backfill) | `2d73cf0`, `1b2c354`, `7da0a74` | +28 |
| Catalog roles refactor (mig 033 view + UI chips) | `962a9cd`, `fdcafa9` | +30 |
| Round-2 fix: NVL rule relax (mig 034 — declaration_type filter) | `1b534b1` | +4 |
| Round-2 fix: UI rework + BOM-only fallback + sister-app notes rev 2 | `7792cdd` | (regression-driven) |

### Recent commits (chronological)

```
7792cdd fix(catalog): UI rework + BOM-only resolver fallback + sister-app notes rev 2
1b534b1 fix(catalog): mig 034 — relax NVL rule, filter by declaration_type
fdcafa9 feat(catalog): UI chips for observed_roles + integrity-conflict warning
962a9cd feat(catalog): mig 033 v_material_roles view + resolver wire + API expose
7da0a74 feat(bcct): wire product_identity into ingest + read API + backfill
1b2c354 feat(bcct): canonical product/material identity resolver
2d73cf0 feat(bcct): mig 032 — product_identity column + review table
355c635 docs: handoff for rename + Phase 3 session  ← previous session
```

### Sister-app notes posted

- `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-07-bcct-product-identity-shipped.md`
  (rev 2 — includes BOM-only fallback note)
- `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-07-catalog-roles-shipped.md`
  (rev 2 — D4 rules with `has_nvl_import` + canonical declaration_type table)
- CO migration prompt staged at
  `~/workspace/client/barry-CO-main/.ai/sister-app-prompts/2026-05-07-data-hub-product-identity-migration.md`.

## Next Steps

Priority order:

1. **Push branch to origin** — 8 commits ahead, demo CI/CD waiting. Run
   `git push origin main` when ready.
2. **CO consumer migration** — open Claude Code in `~/workspace/client/barry-CO-main`,
   point it at the staged prompt. CO removes legacy code-mappings BOM
   resolution and consumes `product_identity.bom_product_code`.
3. **BCQT consumer migration** — sister-app work, separate sprint. Adopt
   `resolved_code` + `product_kind` + `direction` + `btp_sourcing` for
   per-line role inference per sister-app note.
4. **Wipe + ingest fresh — Growatt and Johnson** *(pending — user
   chốt 2026-05-07 across three rounds of clarification)*. Now that all
   resolver/role features have shipped, the wipe-and-reingest is unblocked.
   Procedure in memory `project_reingest_pending.md`.
5. **Demo data parity** — once wipe + ingest fresh runs locally, mirror
   to tinsu (`/home/tinsu/data-hub`) via pg_dump → scp → restore.
6. **Backlog: bootstrap script** to backfill `hub.materials` from
   `bom_artifacts.product_code` (eliminates the 17-code data gap that
   prompted the BOM-only fallback in commit `7792cdd`). Keeps materials
   as canonical registry.
7. **Phase 3c follow-ups + Phase 3 review minors** (existing BACKLOG
   entries) — auto-trigger derive from upload, multi-role warning at
   upload, Playwright E2E. Lower-value polish.

## Blockers

None hard. Soft (carry-over):
- 14 orphan BTPs Growatt (data quality — staff classify when TP
  context arrives).
- T1-T2/2026 BCCT for Growatt missing (agency hasn't supplied file).

## Notes for Next AI Session

**Read first** (in order): this STATUS, then session log
`.ai/sessions/2026-05-07-bcct-product-identity-and-catalog-roles.md`
+ the 2 briefs at `.ai/features/2026-05-07-bcct-product-identity/brief.md`
and `.ai/features/2026-05-07-catalog-roles-refactor/brief.md`.

**Key memory** (load before reasoning about resolver / catalog):
- `project_bom_code_multirole.md` — multi-role canonical (PV01.0104300).
- `project_bom_3_shapes.md` — raw_graph / shallow / full_flat semantics.
- `feedback_bom_vocab.md` — artifact / preset, never version / profile.
- `project_reingest_pending.md` — wipe + ingest fresh procedure.
- `feedback_bundle_rev_fixes.md` — show all findings, user certifies.
- `feedback_drive_ops_dont_handoff.md` — execute via ssh.exe / scp.exe.
- `feedback_review_depth.md` *(new this session)* — cap review at 2
  passes; concrete bugs always fixed but speculation stops at round 2.

**Architecture / contracts that are LOCKED, don't relitigate**:
- 3-app split (Data Hub + BCQT + CO).
- BCCT product identity contract: `resolved_code` (any kind),
  `bom_product_code` (alias when has_bom), `product_kind` (declared),
  `observed_roles[]` (derived). Per-candidate minimal field set.
- Catalog roles model: declared `category` (operator intent) + view-derived
  `observed_roles[]` (data-graph truth). Hybrid by design — D11.
- NVL rule (mig 034 final): `has_nvl_import AND NOT has_own_bom`. Filter
  by canonical NVL declaration_types {E11, E15, E21, E23, E31, E33}.
- BOM-only fallback in resolver: codes with BOM but no materials entry
  get synthesized catalog entry (category='tp', has_own_bom=true).

**Environment quirks**:
- Native Postgres on `/var/run/postgresql` socket, owner `vp`.
- WSL2: Windows OpenSSH (`/mnt/c/Windows/System32/OpenSSH/{ssh,scp}.exe`).
- Port 8754 pinned for dev (CO JWT issuer expects exact host).
- Server may already be running from this session — check
  `ss -ltn | grep 8754`. Login: `admin@data-hub.local` / `admin123`.

**Critical user feedback this session** (also in memory):
- "Cap review at 2 passes" — round 3+ becomes paralysis. Concrete bugs
  in document still fix, but stop volunteering new round reviews.
- "Distinguish concrete bug vs speculative finding" — concrete always
  fix; speculative defer to BACKLOG.
- "Domain-rooted rules" — NVL definition: must have NVL-type import
  declaration. Operator intuition wins over pure structural derivation.
- "UI mental model: declared / observed / edit each separate" — 3 cells,
  not 1 cell with 5 things.

**Sister-app commits** (separate repos, not pushed):
- CO `barry-CO-main`: prompt staged at `.ai/sister-app-prompts/`.
  Awaits next CO session.
- BCQT `BCQT-System`: no prompt staged yet; defer until CO migration
  proves the contract.
