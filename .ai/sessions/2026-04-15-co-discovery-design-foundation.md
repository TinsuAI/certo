# Session Log: CO Discovery Design Foundation

## What Was Done
- Reversed the earlier wrong direction where the repo had been bootstrapped as a webapp.
- Kept the useful archive extraction work and turned the repo into a discovery-first workspace focused on the CO process.
- Extracted the supplied ZIP and all nested RAR archives so the local corpus is fully explorable.
- Analyzed the three key workflow artifacts:
  - `QUY TRÌNH XIN CẤP CO.pdf`
  - `Lưu trình xin CO.jpg`
  - `tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm`
- Reverse-engineered the workbook at the sheet, formula, and VBA-module level to identify:
  - intake sheets
  - selection and matching flow
  - historical ledgers
  - rule-specific output sheets
  - evidence of security and time-lock logic
- Located the correct host Obsidian vault and extracted relevant CO/legal knowledge from `V-Notes/30_Resources`.
- Published shared project docs in `docs/` for business logic, knowledge base, procedure analysis, and data exploration.
- Clarified the business workflow into three layers:
  - trader profile registration
  - product-origin evidence reuse
  - shipment-level C/O filing

## Decisions Made
- The repo should remain discovery-first until workbook logic and domain semantics are better understood.
- Project-facing business and analysis docs belong in `docs/`, not only in `.ai/`.
- The workbook should be treated as a stateful business-rule engine, not merely a spreadsheet attachment.
- The future solution must represent both the compliance workflow and the allocation/origin engine.
- Reuse of product-origin evidence for the same fixed product should be modeled explicitly, separate from shipment-level filing.

## What Didn't Work
- An earlier attempt used the wrong host wiki path and briefly pulled notes from the wrong vault. That was rewound before continuing.
- The initial assumption that “bootstrap” meant scaffolding a webapp was wrong for this project stage and was reverted.
- Workbook analysis through high-level libraries was too heavy for full inspection in one pass; direct OOXML/VBA inspection worked better.

## Open Items
- Validate with operators whether `RunUpgrade` is the real production path or only an upgraded branch coexisting with legacy flows.
- Confirm exactly how `Save` and `Tru lui` are scoped and maintained in practice.
- Build a field-level domain map from workbook sheets to business entities.
- Decide which form families and filing paths should be in scope for the first system design.
