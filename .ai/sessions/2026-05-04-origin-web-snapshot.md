# Session: Origin Web Snapshot

## What Was Done
- Refreshed project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and the latest session summaries.
- Started the CO dev server at `http://127.0.0.1:8001`; `/` redirects to `/auth/login` under the current auth setup.
- Planned the corrected scope after user feedback: the `Xuất xứ` web page must be the authoritative calculation/review surface, while Excel `bảng kê` is downstream output.
- Added origin calculation metadata to the C/O origin flow:
  - method code `build_down_lvc`
  - method label `Build-down LVC/RVC`
  - formula `(FOB - VNM) / FOB x 100`
  - readiness labels/statuses for product-level review
  - valuation source/status labels and warnings for material-level evidence
- Updated origin material derivation to record valuation source from BOM, CO stock/BCCT import, or material catalog.
- Added warning generation for missing material unit values and conservative default non-origin classification.
- Added CTC/CTSH preview output using existing HS comparison logic, with explicit UI copy that it does not replace PSR/legal review.
- Updated `app/templates/co_case.html` so the `Xuất xứ` tab shows method, formula, criterion mode, CTC preview, evidence warnings, valuation source, and data status.
- Preserved the new origin/evidence fields in hidden form round-trips via `app/demo_data.py`.
- Added `Origin Snapshot` sheet to `create_case_workbook()` in `app/co_case_store.py` so exported dossiers retain the same metadata and warnings shown on the web.
- Added tests in `tests/test_co_demo.py` for:
  - web origin method/readiness/evidence warnings
  - workbook `Origin Snapshot` metadata from the web snapshot
- Verification completed:
  - `uv run pytest tests/test_co_demo.py` passed `113/113`
  - `uv run pytest tests/test_data_hub_policy.py` passed `3/3`

## Decisions Made
- Treat the web `Xuất xứ` tab as the source of truth for calculation snapshot and evidence review; Excel output should consume that snapshot rather than independently reinterpret the case.
- Keep phase-one calculation limited to build-down LVC/RVC because recent workbook exploration only proved that path: `(FOB - VNM) / FOB x 100`.
- Show CTC/CTSH only as a preview/evidence aid for now. It is not a final legal conclusion or full PSR engine.
- Keep missing material valuation as a blocking evidence issue instead of silently calculating with zero or hiding the gap.
- Preserve Data Hub policy boundaries. No new raw `/v1/hub/*` endpoint strings were added outside `app/data_hub_client.py`.

## What Didn't Work
- Initial plan framed `bảng kê` mostly as Excel export; user corrected that the web `Xuất xứ` page itself needs to be chuẩn chỉnh.
- Full `tests/test_co_demo.py` initially failed two old assertions because the UI label changed from `Bảng kê LVC` to `Bảng tính Xuất xứ`. The fix kept the new primary label while adding copy that the web snapshot is the source for `Bảng kê LVC/RVC`, preserving backward expectations.
- Direct handoff wait for the explorer was interrupted by the user, but the sub-agent later returned useful code-location notes. No sub-agent changes were applied.

## Open Items
- Browser-review the updated `Xuất xứ` tab with a real active case and refine layout density if needed.
- Commit the current focused changes after UI review.
- Implement exact legacy-style Excel `bảng kê` export from the accepted web snapshot, using `docs/legacy-workbook-output-sheet-structure.md`.
- Build or request a real legal PSR/CTC evaluator before treating CTH/CTSH as final system-generated conclusions.
- Model direct/build-up inputs explicitly before adding any direct/build-up value-content formula support.
- Keep pre-existing untracked `.ai/features/2026-05-02-*` and `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md` separate unless the user asks to include them.
