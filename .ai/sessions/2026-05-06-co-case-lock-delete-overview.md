# Session: C/O Case Locking, Delete Guardrails, and Overview UX

Date: 2026-05-06

## What Was Done

- Implemented customer-scoped origin calculation locking.
  - `Tính lại snapshot` and case dossier XLSX export now acquire/renew a per-customer lock.
  - If another dossier for the same customer holds the lock, the request returns `409` and renders the origin page with a clear message.
  - A blocked dossier can still be opened and prepared, but cannot calculate/export official origin stock output.
  - Locks record case, actor, acquired/renewed/expiry timestamps, and use a 60-minute TTL.
- Surfaced lock state in the C/O case overview.
  - Added a `Phiên tính tồn đang mở` banner.
  - Added `Mở hồ sơ giữ tồn` and `Nhả phiên` actions directly in the overview.
  - Added a `Tồn C/O` column on each dossier row showing `Đang giữ tồn`, `Chỉ chuẩn bị`, or `Sẵn sàng`.
- Added guarded dossier deletion.
  - Delete permission is configurable via Technical Settings `CO_CASE_DELETE_ROLES`.
  - Draft/preparation dossiers can be deleted.
  - Dossiers holding the stock lock must release the lock before deletion.
  - Completed/submitted/closed dossiers cannot be deleted.
  - Delete removes the case record and supporting upload folder.
- Replaced browser `confirm()` with an in-app delete confirmation modal.
- Reworked the C/O case overview layout.
  - Removed the sidebar-style `Tạo hoặc mở hồ sơ` block.
  - Moved the create form into the main overview above the full-width dossier list.
  - Fixed mobile layout regressions after the overview became full-width.
- Added regression tests for lock blocking, overview lock controls, delete guardrails, and configurable delete roles.
- Captured local screenshots under `.ai/screenshots/co-case-overview-lock/` while checking desktop/mobile layout.

## Decisions Made

- Keep the calculation lock in CO local case state for now. This prevents parallel same-customer CO calculations in the current app without pretending to be a global stock ledger.
- Do not auto-release a stock lock when deleting. A locked dossier must explicitly release its lock before deletion so operators see the business action.
- Delete is role-gated by `CO_CASE_DELETE_ROLES`, defaulting to `dev,admin`; local auth-disabled development can delete.
- Completed dossiers are protected by status strings for now: `completed`, `done`, `finished`, `submitted`, and `closed`.
- Use an in-app confirmation modal for delete instead of native browser prompts.
- Keep create-dossier controls in the main overview instead of a sidebar so the dossier list has full width.

## What Didn't Work

- Initial screenshot attempt against `http://localhost:8001/clients/growatt-vn/co-case` redirected to Data Hub login because auth was enabled. A temporary auth-disabled server with Data Hub source enabled was used for screenshots and then stopped.
- Starting an auth-disabled server with Data Hub source disabled returned 404 for `growatt-vn`; the correct screenshot setup was `CO_AUTH_REQUIRED=0 DATA_HUB_ENABLED=1`.
- The first mobile overview layout kept desktop grid columns because `.co-dossier-list` specificity beat the generic responsive rules. Added explicit mobile overrides.
- After moving the create form into the main view, mobile form controls overflowed because the desktop `co-overview-create .co-create-flow` grid still applied. Added a mobile one-column override.
- A native `confirm()` delete prompt was too crude for the workflow; replaced with a modal.

## Open Items

- Manually review the overview in a real authenticated session, including lock release, delete modal, and mobile layout.
- Confirm the final production source of truth for dossier completion state; current blocking is string-based.
- Decide whether a future global stock reservation/decrement ledger belongs in Data Hub before implementing cross-dossier stock decrement.
- Keep unrelated `docs/co-form-index-confirmation.*` and screenshot artifacts out of commits unless explicitly requested.
