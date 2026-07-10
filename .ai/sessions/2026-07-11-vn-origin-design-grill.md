# Session 2026-07-10/11 — VN-origin design grill (design only, no code shipped)

A `/grill-with-docs` session on how CO should handle materials with Vietnamese (and,
later, in-bloc) origin. No production code changed. Output = 4 new ADRs, 2 knowledge
files, glossary terms, a corrected memory, and a scoped set of prerequisite tickets.

## What the user asked
1. Design + implement "xuất xứ VN" first: mark some suppliers (from BCCT) as VN suppliers → VN origin.
2. Then "xuất xứ trong khối" (in-bloc cumulation) in the related forms — phase 2, deferred.

## Data findings (verified against local `data_hub` Postgres + the promulgating TT 05/2018 forms)
Recorded in `.ai/knowledge/2026-07-10-vn-origin-supplier-data-facts.md` and
`.ai/knowledge/2026-07-10-co-origin-cumulation-and-vn-origin-rules.md` (+3 addenda).
- **VN-origin materials already exist in `hub.bcct_rows`** as on-spot imports: `direction='import'`,
  `declaration_type` E15/E13, `origin='VIETNAM'`, supplier in `consignee_name`. Johnson: 6,272 rows /
  1,252 material codes / 64 suppliers. CO reads `origin` (→`origin_country`) but never lets it touch
  `origin_status`, so all of it is summed into VNM and RVC is understated. **No Data Hub change needed.**
- Three earlier theories were killed by data: no `direction IS NULL` rows exist; domestic materials are
  NOT in `declarable_unmatched`; `consignee_name` already reaches CO. (The draft DH API request written
  early in the session was deleted.)
- **`origin` is free-text, not ISO** (CHINA, VIETNAM, UNKNOWN, HG.KONG, U KING…). No counterparty tax
  code exists anywhere — supplier key is the normalized `consignee_name`.
- **24 of 64 VN-capable suppliers sell mixed-origin goods** (Johnson's own affiliate: 1,399 VN + 1,611
  CHINA/etc.) → a supplier flag alone must NOT flip a row; the rule is AND (see below).
- **213 material codes have both VN and non-VN lots** → origin is a property of the lot, resolved per row.
- **Legal:** a VAT invoice alone does NOT make a domestic material originating — needs the supplier's
  **Bản khai báo xuất xứ = Phụ lục X** (NĐ 31/2018 Điều 15.1.g; TT 33/2023 Điều 6.1.c). Phụ lục X excludes
  Form D. Cumulation is three different mechanisms (partial/ATIGA, full/CPTPP+AANZ, all-or-nothing/others).
- **Bảng kê Phụ lục VIII (verified against promulgating `rev5` .docx):** cols (7)/(8) = money split có/không
  xuất xứ FTA; (9) = country fact; (12)/(13) = Số/Ngày of C/O nhập or Phụ lục X. Agency practice (real
  submitted Growatt dossier): they compose (12)/(13) at **supplier grain** (`Phụ lục X/<NCC>` + date),
  and hand-rewrite col (9) to the literal "Không xuất xứ" — which research found has no legal basis.
- **Shortage (consumption > import lots) has no lawful value** on the bảng kê (TT 05/2018 Điều 6.4.b;
  "giá mua đầu tiên" is origin-unknown, not document-unknown; TT 38/2015 Điều 55/59/60 = unbalanced quyết toán).

## Decisions (ADRs in `.ai/DECISIONS.md`, dated 2026-07-10/11)
1. **VN origin decided per row:** originating iff `origin_country`→VN **AND** supplier flagged as having
   supplied Phụ lục X. Conservative default non_origin. Flag lives in **CO** (keyed on normalized
   `consignee_name`), not DH. Resolver returns an originating **amount**, not a boolean.
2. **Bảng kê row grain = BOM line** — CO already matches agency practice (earlier "one row per lot" draft
   was a misreading, withdrawn). Two independent defects surfaced: col (6) can hold the string "Nhiều đơn
   giá"; `stock_allocation_line` prices BOM-first over the lot's import CIF.
3. **Split a BOM-line row when its lots resolve to different origins**; render-time fan-out (source
   `product["materials"]` unchanged). Row identity = `(material_sequence, origin_status, column9_text)`.
4. **Shortage blocks issuance** via the three-belt guard (mirror `declarable_unmatched`); decoupled from
   any status refactor (HARD constraint from adversarial review: do not delete the `calculated_sheet_status`
   downgrade branches in the same change — `missing_price` is enforced only by that downgrade). Remove the
   fallback-price path for no-lot materials.
5. **Status model:** readiness chip from existing `origin_readiness_status` now (no status-enum change);
   full two-dimension refactor deferred to after VN-origin.
6. **Column (9) content = client-default + per-case mode** (`country` default | `qualification_label`),
   resolved once at Tính and materialized into `bang_ke_origin_text`; 3 renderers become pure. Split-key
   subsumes both modes with no conditional. Normalization = code-owned raw→ISO + ISO→VN, unmapped → raw +
   NON-blocking warning; read-only UI view (not admin-editable yet, user directive).
7. **Override identity = `material_sequence`** (BOM materials) + `added_<n>` (added rows). No new UUID — a
   BOM version is an immutable artifact so `(version, position)` is the robustness ceiling. Upgrade worth
   taking: make the override binding **version-aware** (`(bom_product_artifact_id, material_sequence)`),
   which also closes a pre-existing override-vs-version-switch bug.

## Prerequisite ticket ordering (for when build starts)
1. Plumb `origin_country` + `consignee_name` from the lot into the sheet material dict at Tính
   (`stock_allocation_line` / `origin_material_from_bom_row`) — col (9) is blank in prod today.
2. Re-key overrides positional-index → `material_sequence` (+ version-aware); render-split fan-out.
3. Shortage three-belt guard + specific lock-block reason (ship independently — legal urgency).
4. Column-9 mode (client-config + per-case) + `app/origin_country.py` normalization.
5. Per-row VN-origin resolver (origin_country→VN AND supplier flag) — the actual feature.

## Open / not grilled (self-contained, belong with the build)
- **Supplier-flag curation UI + name normalization** — which screen sets the flag, who sets it, how
  aggressively `consignee_name` is normalized (whitespace vs branch/parent merge). Not a blocker.
- Column-9 sub-decisions recorded as recommended defaults (qualification label "Việt Nam"; UNKNOWN →
  "Không xác định" — user leaned "Không xuất xứ", genuinely open; flip-while-locked = allow-with-warning).
- **Two non-grill action items, must not drop:** (a) audit already-locked SHORTAGE sheets in prod
  (claims already written — legal exposure); (b) resolve the `missing_price` one-belt hole (blocked on
  `/calculate` but leaks via the save-route hardcode + lock gate not re-checking `lvc_missing_price`).
- **Config risk:** `dncx` preset is E11/E15, but 13 of 38 VN-only Johnson suppliers are E13-only;
  `johnson-vn` currently has `eligible_import_declaration_types=[]`. Check before enabling a preset.
- **Phase 2 (in-bloc cumulation):** separate grill. Form D and AK don't exist in `co_forms.py` yet;
  three cumulation mechanisms; Phụ lục X is not valid for Form D.

## Artifacts produced
- ADRs: `.ai/DECISIONS.md` (7 entries dated 2026-07-10/11).
- Knowledge: `.ai/knowledge/2026-07-10-vn-origin-supplier-data-facts.md`,
  `.ai/knowledge/2026-07-10-co-origin-cumulation-and-vn-origin-rules.md` (+3 addenda).
- Glossary: `.ai/GLOSSARY.md` — the three senses of "xuất xứ" + Phụ lục X.
- Client list: `C:\temp\toss\johnson-ncc-xuat-xu-vn-2026-07-10.xlsx` (38 VN-only + 24 mixed suppliers).
- Memory: corrected `co-stock-claim-lifecycle` (missing-price now blocked, shortage still leaks);
  new `vn-origin-materials-are-e15-onspot-imports`.

## What didn't work / process notes
- Two adversarial critic passes (Fable 5) materially changed the design: killed "refactor as prerequisite"
  (sequencing), killed "hard-block on unmapped country string" (category error), corrected the two-map
  split into one canonicalization. A design agent (Fable) produced the column-9 mechanism.
- Repeated correction of my own over-assumptions by reading code: "one row per lot" grain, "is-VN drives
  RVC", "riskiest task" for the override re-key — all walked back against the actual code.
