# 2026-08-17 — Client questions on VNG26020033: missing-price belt, honest sheet status, clearer labels

Operator (Thanh Tâm, Johnson VN) sent 5 questions with screenshots about case
`CO-JOHNSON-VN-VNG26020033-6CB0`. Diagnosed all 5 against the live stack (read-only),
then shipped 3 fixes. `origin/main` = prod `barry-co` = nightly `demo-co` = **`72de4eb`**.
Full suite **1035 pass / 17 skip**.

## Commits (all deployed)

| SHA | What | CD run |
|---|---|---|
| `0ad5c3e` | `lvc_missing_price` ignores rác; bulk routes persist the earned status; aggregate lists rác + stops inviting Chốt | `31995246886` |
| `059f276` | `.ai/feedback/2026-08-17-client-questions-vng26020033.md` (findings + forwardable VI reply) | same |
| `72de4eb` | one label for `declarable_unmatched` — "NVL chưa có tờ khai nhập" | `31996774344` |

Plus one **prod config change, not code**: `features.bulk_delete_junk_rows` = ON for
johnson-vn (`config_version` 1→2, `co_config_fingerprint` unchanged `17c95904c2712c54`
→ no stock re-derivation; `allocation_code`/`co_stock`/`bcct` untouched). Written through
`_local_config_store().save_client_config`, verified via `portfolio_service.get_client_config`.

## The case, measured (prod, read-only)

| | MPL0108-39 | MFW0509-39 |
|---|---|---|
| persisted status | `bom_loaded` | `stale` |
| active materials | 145 | 86 |
| `declarable` + `ready` (lot-matched, priced) | 82 | 62 |
| `declarable_unmatched` | 35 | 19 |
| `excluded_non_material` (nhãn — `item_category: "label"`) | 28 | 5 |
| rows with `valuation_status == missing_unit_value` | **0** | **0** |
| `lvc_missing_price` (before fix) | true | true |

53 distinct unmatched codes. DH johnson-vn BCCT: import 84,231 rows / 10,393 codes /
2025-04-18 → 2026-08-05; CO `co_stock_rows` = 84,231 (1:1, refreshed 2026-08-17 03:25Z,
no declaration-type filter) — no upload or sync gap.

## What was wrong (4 defects, 1 non-defect)

**D1 — `lvc_missing_price` fired on rác (`co_case_context.py:3233`).** The flag ORs on
`unit_value_missing`, which a no-lot row always sets (`material_value = None`), while its
`valuation_status` is deliberately `partial_allocation` — the ADR 2026-07-11 decision that
a no-lot line's defect is the missing DOCUMENT, not a price (`:2734`). The predicate also
never excluded `bom_technical_noise`, unlike its sibling `lvc_allocation_shortage` (`:3255`),
so shortage read false while missing_price read true and the chip named the wrong remedy.
Fix = add `and not material.get("bom_technical_noise")`. Proven by the data: 0 rows carry
`missing_unit_value` yet the flag was true; every real row was `ready`.

**D2 — the two aggregate routes stamped `"calculated"` without re-deriving it**
(`co_case.py` bulk-substitute + bulk-delete-rac). A sheet still held by a belt read
"Đã tính" in the list while the lock gate refused it → "Đã chốt 0 sheet · bỏ qua 2", and the
real state only appeared after F5. **This, not a client-side repaint gap, is the F5 story.**
Fix = new `recalculate_origin_sheet_and_status` used by both.

**D3 — the aggregate panel invited "Chốt tất cả" while blocked.** `case_shortfall_rollup`
routes all-noise materials into `folded_rac`, never `materials`, so `material_count == 0` →
"✓ Đủ tồn cho tất cả SP … có thể Chốt tất cả". `folded_rac` was then dropped client-side
when the feature flag is off (`racItems = bulkEnabled ? … : []`), leaving no trace of the 53
codes that blocked issuance. Fix = list rác read-only regardless of the flag, warn instead of
inviting Chốt while `declarable_unmatched` remains.

**D4 — four phrasings for one condition.** The chip said "NVL chưa khớp tồn", which reads
as a quantity shortfall — exactly what the *other* label ("thiếu tồn") means. Unified on
**"NVL chưa có tờ khai nhập"** across chip, lock error, per-sheet filter chip, rác
quick-select button, row tag, per-row mark, fold toggle. Detail texts now state what it is
NOT ("không phải thiếu số lượng") and name remedies (sửa mã / thay mã / xoá dòng). "BCCT"
dropped from operator text; the `declarable_unmatched` token stays in the lock error as a
support anchor (and `UNMATCHED_LOCK_FRAGMENT` pins it).

**Not a defect — Q1 ("BCCT uploaded but codes still missing").** All 53 unmatched codes
appear in **0** johnson-vn BCCT rows, either direction. They exist in `hub.materials` only as
`provenance = {"seen_in_bom_only": true}` with `name == material_code`; matched codes carry
`provenance.seen_in_bcct` + a real description (e.g. `0000096074`, 54 declarations).
Client-wide **3,822 / 14,527** catalog materials are BOM-only, and `hub.code_mappings` has
**0 rows for johnson-vn** (growatt-vn: 2,913) — a BOM code that is not literally the declared
customs code can never match. Earliest import row is 2025-04-18, so any Jan–mid-Apr 2025
declaration never landed. **CO-side code cannot fix this; it is client data / a DH mapping.**

## Decisions

1. **The feature flag gates bulk ACTIONS, not visibility of a blocker.** Hiding `folded_rac`
   when `bulk_delete_junk_rows` is off is what let the panel claim "có thể Chốt tất cả" on a
   case that cannot lock. Read-only listing is always on.
2. **`excluded_non_material` does NOT block Chốt** (after D1). It is folded out of the bảng kê
   and contributes 0 to VNM, so only `declarable_unmatched` (and `mixed`, treated as blocking
   for safety) counts toward the warning. The e2e deliberately asserts the ✓ invite SURVIVES
   when only phi-vật-tư rows remain — that is what proves D1 and D3 agree on which kind blocks.
3. **Fixing D1 alone does not unblock the case** — `lvc_declarable_unmatched` still holds both
   sheets by design (DC3c). The operator's path is: clean the rác → Tính lại → Chốt.
4. **Ran `/code-review` inline instead of spawning the two sub-agents** the skill prescribes —
   standing user rule forbids Agent calls unless requested. Two findings applied: matched the
   file's zero-blank-line convention between top-level defs; gave the new warning its own
   `.rs-blocked` class instead of reusing `.rs-nobom`, whose name means something else.
5. **Left `co_case.py:3358` / `:3556` out of scope** (same hardcoded-status defect, different
   user actions) rather than widening past what was approved.

## What didn't work / environment gotchas

- **Local CO `:8001` is useless without local DH `:8754`** — every page 503s
  ("Data Hub không phản hồi"). Start `../data-hub` first:
  `cd ../data-hub && (set -a; . ./.env; set +a; uv run uvicorn app.main:app --host 127.0.0.1 --port 8754)`.
  Port 8754 is not negotiable (CO's JWT issuer check).
- **Background servers die when the Bash `timeout` fires** (exit 124) and take CO to 503 with
  them. Start long-lived servers with `nohup … & disown`, not a timeout-bounded background task.
- **A file-mode server (no DH) needs `CO_ALLOW_LOCAL_SOURCE=1`**, not just `DATA_HUB_ENABLED=0`
  — otherwise `get_portfolio_service` raises `SourceBackendUnavailable` → 503 on every page.
  It was still a dead end: the case page renders with no `case.products`, so the
  `{% if case.products %}` aggregate section never emits and the panel can't be driven.
- **No local case has rác rows persisted.** `.ai/scripts/e2e_johnson_rac_seed.py` is the only
  way to get one (clones `co-case-e0b390ead3b0` with deletions reverted → 22 thiếu-tồn + 71
  folded rác). Always `--cleanup` after.
- **Reaching `material_count == 0` with rác still present is impractical on real data** (it
  means substituting every shortfall first). Covered instead with a synthetic rollup via
  puppeteer request interception — `.ai/scripts/e2e_rac_blocks_chot_message.cjs`. The renderer
  reads only `rollup.materials` / `folded_rac`, so a stubbed body exercises the branch exactly.
- **zsh:** `--include=*.py` and `ls -t` need quoting/care; `grep -rn … --include="*.py"`.
- **psql through `ssh tinsu` + `docker exec`:** nested quoting mangles the SQL. Write a `.sql`
  file and pipe it: `ssh tinsu 'docker exec -i co-db-1 psql -U co -d barry_co' < q.sql`.
  Prod DB users are `co` / `hub` (not `postgres`).
- **`uv run python <script outside the repo>`** needs `PYTHONPATH=$(pwd)` or `from app import …`
  fails.

## Open items

- **Same defect class as D2, not fixed:** `co_case.py:3358` (per-sheet "Lưu bảng kê") and
  `:3556` (mở chốt) also stamp `"calculated"` without re-deriving. Needs a decision; a
  `recalculate_origin_sheet_and_status`-style call does not fit `:3556` directly (reopen has no
  recalculation right before it).
- **Adjacent, inert today:** VNM sums `non_origin_cif_value` over noise rows too
  (`co_case_context.py:2455-2460`, no `bom_technical_noise` filter) — harmless while noise rows
  carry no value, but it is the same missing filter D1 fixed one flag later.
- **Cosmetic:** the LVC "Tạm đạt / Tạm tính" label and the "Thiếu tồn CO N dòng" quality warning
  still count noise rows (`:2461`, `:3208-3226`). Does not block lock.
- **Client-side (Q1), no CO work:** johnson-vn has 0 `hub.code_mappings`; 3,822 BOM-only catalog
  materials; the 2025-01 → 2025-04-17 BCCT window is absent. Needs the agency to confirm whether
  the 1000…-series codes are internal codes needing a mapping, domestic VAT purchases, or older
  imports. A DH-side mapping is `data-hub` repo work (guardrail — not from here).
- **The reported case is still not lockable** and correctly so: 35 + 19 `declarable_unmatched`
  rows remain. With the flag now ON the operator can clear them from "Tổng hợp NVL" in one pass.

## Verification

- Full suite **1035 pass / 17 skip** (was 1031; +4 tests: 1 belt-1 rác exclusion, 1 belt split,
  2 route status tests).
- Browser e2e on a real Johnson clone, both flag states: **off** → 71 rác rows listed read-only,
  0 checkboxes / substitute / delete controls, no console errors; **on** → unchanged behaviour,
  48-row bulk delete with kind isolation intact, per-sheet panel renders.
- Synthetic zero-shortfall rollup: both message branches (✓ invite retained for phi-vật-tư-only;
  warning + badge + ribbon held for unmatched present).
- **On prod after deploy**, running the deployed code against `co-case-6cb034e91cb7` in-container:
  `missing_price=False` on both sheets (was True), `unmatched=True`, status `bom_loaded`, chip =
  "Cần xử lý: NVL chưa có tờ khai nhập".
- `/version` on prod + nightly = `72de4eb`.
- Local flag reset to OFF and the e2e clone removed after each run.
