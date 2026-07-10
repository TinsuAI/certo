# Session 2026-07-11 — VN-origin grill part 2: leftovers closed, phase 2 deferred (design only, no code)

Continuation of `2026-07-11-vn-origin-design-grill.md`. All remaining grill branches are
now closed: 5 new ADRs in `.ai/DECISIONS.md` (2026-07-11), addenda in both knowledge
files, glossary + BACKLOG updates. No production code changed.

## Decisions closed this session (full text in DECISIONS.md)

1. **Q1 — column-9 unknown label:** free-text client-config key `bang_ke.unknown_origin_label`
   on the existing `/clients/{id}/config` form; code default "Không xác định"; unknown bucket
   only (unmapped-but-real country strings still render raw + warning); materialized at Tính.
2. **Q2 — flip-while-locked:** both directions always allowed; ON→OFF = explicit confirm with
   computed damage list (locked sheets whose snapshots relied on the supplier); OFF→ON = info
   note; append-only log with actor from DH JWT; NO effective-dating (that's the DH-migration
   trigger).
3. **Q3 — evidence store:** CO-side Postgres, `co_supplier_evidence_events` append-only via
   migration chain (NOT client_config.json, NOT DH, NOT a bare boolean). `evidence_kind`
   (`phu_luc_x`|`co_import`) kept day-one; **`doc_no`/`doc_date` deferred (user directive)** —
   col (12) renders composed "Phụ lục X/<NCC>", col (13) blank + warning until then. Snapshot
   enrichment: Tính materializes `supplier_key` + (12)/(13) text per row. Curation = new
   per-client screen; shared whitespace-only normalization fn; no branch/parent auto-merge.
4. **Q4 — dncx preset:** becomes `["E11","E13","E15"]`; live configs untouched; client-config
   form gets per-declaration-type BCCT counts + save-time exclusion warning.
5. **Q5 / phase 2 — in-bloc cumulation DEFERRED until a client actually files a preferential
   form.** Three constraints pinned: form-scoped resolution; consignment-grain evidence;
   ATIGA partial = number-only change in the amount-based resolver. "Các Form khác sẽ plan
   sau" (user).

## Facts established (recorded in knowledge addenda)

- **Staff:** Growatt has exactly 2 Phụ lục X suppliers — `CONG TY TNHH MINGJIE VIET NAM`,
  `CONG TY TNHH MINGHUI VIET NAM` (both pure E15: 81/61 rows). **Johnson has ZERO** — all
  1,252 VN-origin Johnson codes legally stay non_origin; the current all-VNM treatment is
  CORRECT for Johnson. Day-one beneficiary = Growatt only. No seed script — 2 rows via UI.
- **Name trap:** `MINGJIE INDUSTRIAL (HK) LIMITED` is a different legal entity — must NOT
  be flagged (validates no-auto-merge).
- **growatt-vn on-spot mix:** E13 = 1,444 rows (83%), E15 = 296. Johnson: E15 4,870 / E13 1,373.
  Empty `eligible_import_declaration_types` = NO filter (`co_stock_derivation.py:150-151`).
- **Trừ-lùi workbook scan (exhaustive):** Form D/ATIGA/TT 22-2016 = 0 hits; forms actually
  filed = B, X (both VCCI non-pref), EUR.1 (printed phôi in HONG AN dossier), AI (XUẤT ẤN
  dossier; "RVC 35% + CTSH"). `BẢNG THEO DÕI TỒN CO.xlsx` = material import inventory
  (Đã xuất/Tồn per declaration line), NOT a C/O register — no manual in-bloc evidence
  practice exists. **Form X missing from `co_forms.py` → BACKLOG FX1.**

## Updated prerequisite ticket order (build plan for the VN-origin feature)

1. Plumb `origin_country` + `consignee_name` into the sheet material dict at Tính —
   **widened:** also materialize `supplier_key` per row (damage-list + (12)/(13) need it).
2. Re-key overrides positional-index → `material_sequence` (+ version-aware); render-split fan-out.
3. Shortage three-belt guard + lock-block reason (ship independently — legal urgency).
4. Column-9 mode + `app/origin_country.py` + `bang_ke.unknown_origin_label` config field —
   **widened:** (12)/(13) text materialization into the snapshot.
5. **NEW:** `co_supplier_evidence_events` migration + curation screen (`/clients/{id}/suppliers`-style)
   + flip flow (ON→OFF damage-list confirm, OFF→ON info) + shared normalization fn.
6. Per-row VN resolver (`origin_country`→VN AND supplier flag on) — the feature.
7. Independent/small, any time: dncx preset E13 fix + config-form per-type counts.

## Process notes / what didn't work

- **User caught two real errors of mine:** (a) proposing file-JSON storage when the app runs
  DB-mode Postgres in prod; (b) a "knob" framing when they meant a free-text field.
- **One misread cost a critic pass:** I read "editable text luôn" as per-row grid editing and
  ran a full adversarial review of that design. The review verdict (storing `origin_text` on
  `material_overrides` is a key-space category error — material-keyed scalar cannot address
  split sub-rows; display-only field in a calc-input map breaks undo/diff/export purity) is
  RECORDED in the Q1 ADR's alternatives as a permanent "don't do this" + the corrected shape
  (`origin_text_overrides` keyed by sub-row identity, applied at a split-off col-9
  materialization step) if per-row deviation ever becomes a real request.
- **Fable full-context review (fork) materially upgraded Q3:** re-affirmed CO-side with
  code-verified reasons (mig-078 exists for a DH-owned derivation; supplier flag feeds no DH
  computation; damage list needs CO snapshots; `co_stock_events_store` audit precedent) AND
  found the boolean table could not render bảng kê (12)/(13) → evidence-record schema.
- Agent passes this session: config-surface explore, col-9 critic, CO-vs-DH fork review,
  workbook inspection. All four changed the outcome — none was ceremonial.

## Open items

- Build not started; ticket order above. Two non-grill action items from part 1 still stand:
  (a) audit already-locked SHORTAGE sheets in prod; (b) `missing_price` one-belt hole.
- `doc_no`/`doc_date` enhancement (additive migration + curation fields) when the agency
  wants real Số/Ngày on (12)/(13).
- BACKLOG FX1 (Form X) — small parity item, not urgent.
- Exact `consignee_name` spellings for Mingjie/Minghui VN to be confirmed at build time
  (query recorded in knowledge addendum).
