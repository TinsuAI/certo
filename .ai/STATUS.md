# Project Status

**Date:** 2026-05-03 (PM, post-handoff)

## Current State

Data Hub MVP web app: upload preview-confirm flows across all 4 modules (BCCT/BOM/BQD/Catalog), SSO/JWT auth, read APIs, BOM proposals, chat agent, CO-facing contract guardrails, slim `/client-config` master-data API + admin UI, in-app notifications, BCCT confirm-on-update gate + history page, LLM smart parser for BCCT/BOM/BQD, catalog multi-source provenance, staleness banner, production deployment scaffold, service-account JWTs.

**Shipped this session (PM): technical-BOM flattening end-to-end.** New `technical_flatten` upload profile + pure flatten engine + structured BOM identity (`source_bom_kind`/`flatten_status`/`flatten_strategy`/`lineage`/`display_label`) + UOM canonical model + 5 staff-confirm gates + `/v1/hub/products/{p}/bom/latest` flatten-aware (returns 409 on dual-source variants) + redesigned preview UI + BOM list filter chips + adapter registry refactor (5 adapters, 2 new for SAP-indented Johnson + multi-sheet Growatt). Independent critic review caught 3 Critical (single-tx materialization, dual-source bypass when also non_flattened, variant-equality bug) + 2 Important (multi_sheet adapter false-positive, nested dual-source decisions) — all fixed with regression tests.

**Test count: 307 passed, 15 skipped** (was 239 baseline morning → +68 new). 9 commits since `b6db3d5`.

## Recent Commits (this PM session)

```
2591dfe docs: bom flatten handoff (STATUS + DECISIONS + sister-app note)
262f9f2 chore(scripts): screenshot demo + CO comparison harness
a503bcd test(flatten): regression tests for /rev critic findings
e9b3d3a feat(ui): technical_flatten upload + redesigned preview + bom list filter chips
e1a82aa feat(api): /v1/hub/products/{p}/bom/latest flatten-aware + 409 dual-source
994f9ca feat(stores): bom flatten materialize + uom lookup + decisions store
a05cd82 feat(parsers): pluggable bom adapter registry + 2 single-root adapters
b600d60 feat(flatten): pure flatten engine + UOM lib + classify + identity
23e31dd feat(db): bom flatten schema + UOM model + idempotency v2
```

## Next Steps

1. **CO migration cutover by 2026-05-16** — sister-app notes need CO + BCQT consumer migration. CO must handle `/v1/hub/products/{p}/bom/latest` 409 dual-source response + filter `flatten_status='non_flattened'`. See `.ai/sister-app-notes/2026-05-03-bom-flatten-shipped.md`.
2. **Real-data flatten via technical_flatten profile** — the 9-commit work was tested via Playwright + `scripts/compare_real_boms_vs_co.py`. The latter ran on 39 Growatt + 82 Johnson real workbooks and verified 100 % Johnson leaf-set + 93.3 % Growatt leaf-set match with CO. **96 % of Johnson qty mismatches are CO undercounts** (CO ignores ancestor edge qty>1; DH math is correct). DH is ready for production calculation use.
3. **/rev BACKLOG items not yet addressed** (catalogued in `data/screenshots/_compare_analysis.md` + critic agent transcript):
   - I2: SAP indented adapter defensive leaf-detection second-pass
   - I4: `make_current_db_btp_lookup` allowlist→exclusion intent filter
   - I5: distinct `flatten_strategy='adapter_preflattened'` for audit clarity
   - I6: `recommended_variant_version_id` field in 409 body
   - I7: FK cascade `bom_flatten_decisions.pending_id` → `upload_pending`
   - M1: separate `explicit_walked` evidence code (currently overloaded `explicit_purchased`)
   - M2: i18n key fallback unit test
   - M3: UOM lookup preload for client (currently per-row connection)
   - M4: `normalized_hash` Decimal-instead-of-float precision
   - M5: recursion depth cap on `_explode` + `_walk_tree`
4. **BCQT consumer migration to Data Hub BOM** — when BCQT migrates, it MUST handle the flatten contract per the sister-app note.
5. Backlog items unchanged from morning: CSRF, manual mapping UI when LLM disabled, BOM parse-error UX, migration numbering 010→012.

## Blockers

None.

## Notes for Next AI Session

- **Dev port 8754 is non-negotiable** (CO JWT iss validation depends on it).
- **Dev server may still be running** at `127.0.0.1:8754` (PM session restarted with --reload; PID changed several times). Check `pgrep -f 'uvicorn app.main'` before starting another.
- **`data/screenshots/` is gitignored.** Run `scripts/screenshot_flatten.py` to regenerate the 8-case + duplicate + Johnson + Growatt walkthrough; outputs `flatten_*.png`. Run `scripts/compare_real_boms_vs_co.py` (needs `BOM_DATA_DIR` env or the symlinked `/tmp/dh_real_data/`) to regenerate `_compare_report.{json,md}` + `_compare_analysis.md`.
- **Single-tx materialization invariant**: `create_flattened_version_set` opens ONE connection + ONE transaction, passes `cursor=cur` into `create_version`. Any future store helper that materialises bom artifacts MUST follow the same pattern OR be called inside the existing transaction. Test `test_C1_materialize_rolls_back_on_failure` in `test_flatten_rev_findings.py` will catch regressions.
- **Strict variant equality**: `same_upload_btp` wrapper + `make_current_db_btp_lookup` treat `default` as a real variant, NOT a wildcard. Caller passing `""` ⇒ match anything; specific variant ⇒ exact match. `test_C3_*` covers this.
- **Adapter registry order matters**: single-root adapters (`sap_indented_walk`, `multi_sheet_per_root`) run FIRST in `parse_with_fallback`, then generic adapters. Each strict adapter rejects (raises `BomParseError`) when its preconditions don't match, so a plain manual_flat upload falls through cleanly.
- **Service-account JWT design unchanged** — auth via registry (`hub.service_accounts`), tokens are authentication only.
- Respond in Vietnamese with full accents when user writes Vietnamese; user uses "tao" / responds with "ông"-"tôi".
