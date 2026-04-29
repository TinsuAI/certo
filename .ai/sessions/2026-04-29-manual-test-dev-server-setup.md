# Session: Manual Test Kit And Dev Server Setup

## What Was Done
- Got up to date with the project state on branch `sprint/co-case-supporting-files-20260429`.
- Verified the current C/O demo status: persisted dossier workflow exists, Growatt case `co-case-1d5ef62b0f86` is available in the temp user-test store, and Python C/O tests pass.
- Generated a full manual test kit under ignored `temp/user-test/manual-files`:
  - `00-growatt-co-case-input.xlsx`
  - `01-invoice-GIN01424L171.pdf`
  - `02-bill-of-lading-BL-TEST-GIN01424L171.pdf`
  - `03-packing-list-GIN01424L171.xlsx`
  - `04-export-declaration-E42-307121331440.xlsx`
  - `05-product-photo-GIN01424L171.png`
  - `90-invalid-format-GIN01424L171.txt`
  - `91-too-large-supporting-file.pdf`
- Wrote `temp/user-test/MANUAL_TEST_INPUTS.md` with the exact test URL, input values, upload slots, and expected results.
- Smoke-tested the prepared Growatt case URL and confirmed it returns `HTTP 200` with expected invoice, Form AI guidance, and reviewed BCCT export matches.
- Smoke-tested dossier workbook export and confirmed it returns a valid XLSX with sheets `Case`, `Supporting Files`, `BCCT Invoice Matches`, `Form Guidance`, and `Criteria`.
- Smoke-tested negative upload validation:
  - `.txt` supporting file returns `400` with unsupported-format message.
  - oversized PDF returns `400` with the 20 MB limit message.
- Started the dev server in tmux window `1-CO-MAIN:barry-co-dev` using `npm run co:serve` and `CO_CASE_STORE_ROOT=/home/vp/workspace/client/barry-CO-main/temp/user-test/co-cases`.

## Decisions Made
- Keep manual test artifacts in ignored `temp/user-test/...` so the user can upload real files without committing runtime data.
- Use the existing Growatt case `TEST-AI-GIN01424L171` as the primary manual test path because it already has a known invoice match against reviewed BCCT export declaration `307121331440`.
- Keep the visible dev server in tmux instead of a background service because the user wants a stable session process they can inspect, not a hidden systemd unit.
- Leave the manual test case itself clean before user testing; smoke tests did not upload accepted files into the case, so `supporting_files` remains empty for the user-run test.

## What Didn't Work
- Starting uvicorn in an interactive exec/nohup-style detached command did not keep the server reliably available after the tool call ended.
- A transient `systemd-run --user --collect` service started successfully but later disappeared after failure because the unit was transient and collected.
- A persistent user systemd service with `Restart=always` worked technically, including restart after killing uvicorn, but it was the wrong operational model for the user's request. It was stopped, disabled, and deleted.
- tmux created as a separate transient session was less aligned with the user's workflow than adding a visible `barry-co-dev` window to the existing `1-CO-MAIN` session.

## Open Items
- User still needs to run the browser manual test with the files in `temp/user-test/manual-files`.
- Capture any UI/domain issues from the manual run before building more dossier functionality.
- `npm test` still fails 3 known legal lookup `raw-binary` source-link expectations unrelated to the C/O dossier flow.
- The app still needs a structured PSR/HS legal rule lookup before showing final form-specific origin pass/fail.
- Criteria preview still needs real stock allocation/reservation semantics before it can become operational allocation.
