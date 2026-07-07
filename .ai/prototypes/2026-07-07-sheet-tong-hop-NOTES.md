# Prototype verdict — sheet tổng hợp (2026-07-07)

**Question:** which of 3 layouts best carries "auto tính cả lô → thiếu tồn → thay phần thiếu/thay hết → chốt tất cả"?

**Answer: Variant A (consolidated shortfall table) — unanimous** across a 4-expert judge panel
(UX workflow-fit, consistency/reuse, information-design-at-scale, build-cost/risk). Scores:
A 4.5/5/4.5/5 · B 3.5/3/2.5/3 · C 3.0/2/3.0/2.

**Grafts (all judges agreed):**
- From **B** — a *slim phase ribbon* (Tính cả lô → Xử lý thiếu tồn → Review & Chốt), reusing the
  existing `owz` "Xử lý tuần tự" wizard bar idiom, NOT a new full stepper (stepper step-state is the
  half-built statefulness that got the old batch UI disabled — `834e1da`).
- From **C** — the per-SP spatial cue as a *per-row drill-down dot-strip* (đủ/thiếu/không-dùng),
  NOT the full matrix (matrix needs a new material-centric endpoint + 30-col horizontal-scroll; dies at 30 SP).
- Add per-sheet **LVC** + clear **locked / DC3c-blocked** encoding in the drill-down (gap in all 3 protos).

**Key build fact:** the batch loop is ALREADY wired product-centric and reuses the rich modal:
`runStockAll → renderRunStockSummary → openBulkSubstitutePicker (.origin-substitute-modal stage-mode)
→ applyBulkSubstitute → runBulkLock` (co_case.html ~5783-5968). Gated buttons (913-920) just need
`data-*`+URLs. The ONE genuinely-new interaction = the **scope toggle** (thay phần thiếu/thay hết),
backed by the already-built-but-unused `bulk-substitute-plan` route.

Full solution spec → `.ai/features/2026-07-06-auto-flow-batch-redesign.md` (Slice 2 UI decision).
Fold the winner into co_case.html, then delete this prototype + the losing variants + switcher.
