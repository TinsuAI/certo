# Spec: VN-origin materials — per-row origin resolution, supplier Phụ lục X evidence, bảng kê columns (9)/(12)/(13)

Status: ready-for-agent

Tickets: GitHub Issues [TinsuAI/co #6–#13](https://github.com/TinsuAI/co/issues) (tracker
of record since 2026-07-11); `issues/01…08.md` in this directory are the archive copies.

Sources: 12 ADRs in `.ai/DECISIONS.md` (2026-07-10/11), sessions
`.ai/sessions/2026-07-11-vn-origin-design-grill.md` and
`.ai/sessions/2026-07-11-vn-origin-grill-part2-close.md`, knowledge files
`.ai/knowledge/2026-07-10-vn-origin-supplier-data-facts.md` and
`.ai/knowledge/2026-07-10-co-origin-cumulation-and-vn-origin-rules.md`.
Design is closed — do not re-open the decisions below; build to them.

## Problem Statement

Agency staff prepare CO dossiers for clients whose factories buy some materials
domestically from Vietnamese suppliers. Those purchases already reach CO as on-spot
imports (BCCT rows with declaration types E15/E13, `origin='VIETNAM'`, supplier in
`consignee_name`). Legally, when the supplier has provided a Bản khai báo xuất xứ
(Phụ lục X), those materials are originating: their value belongs in bảng kê column
(7) (trị giá có xuất xứ FTA) and raises RVC/LVC.

Today the app treats every material as non-originating. VN-purchased value is summed
into VNM, RVC is understated, and a dossier that legally qualifies can appear not to.
Column (9) (nước xuất xứ) is blank in production; columns (12)/(13) (Số/Ngày of the
C/O nhập or Phụ lục X) are blank. Staff hand-edit the exported workbook to fill them,
which breaks the export==web invariant and invites transcription errors.

Two adjacent defects carry legal exposure and are settled by the same design:

- A sheet whose consumed quantity exceeds its matched import lots (shortage) can be
  calculated, locked, and exported today. The shortfall has no lawful value on the
  bảng kê (no import declaration and no VAT invoice backs it), so the app can ship an
  unlawful document. A no-lot material is even priced from a BOM/catalog fallback that
  cites no declaration.
- The `dncx` client-config preset excludes declaration type E13, which is 83% of
  Growatt's on-spot volume. Any future DNCX client onboarded via the preset would
  silently lose those lots: false shortages, and VN-origin rows that never render.

Day-one facts from agency staff: Growatt has exactly two Phụ lục X suppliers
(Mingjie VN, Minghui VN — both pure E15). Johnson has zero, so Johnson's current
all-VNM treatment is legally correct and must not change.

## Solution

Staff flag, per client, the suppliers that have provided origin evidence (Phụ lục X
or an import C/O) on a new curation screen. From then on, Tính resolves origin per
material row: a row is originating iff its lot's country of origin normalizes to
Vietnam AND its supplier is flagged. Qualifying value moves to column (7) and RVC
rises; everything else keeps the conservative non-originating default.

The bảng kê fills itself: column (9) renders per the client's convention (real
country name, or the qualification label "Việt Nam"/"Không xuất xứ"), with a
configurable label for unknown-origin lots; column (12) composes
"Phụ lục X/<supplier name>" for qualifying rows ((13) stays blank with a warning
until document dates are captured — deferred by user directive). When one BOM line
draws on lots with different resolved origins, the line splits into one rendered row
per origin. All of this is materialized at Tính; exports stay pure renders of the
web grid; locked sheets never change retroactively.

Shortage now blocks chốt and export with a specific reason, using the established
three-belt guard. The `dncx` preset gains E13, and the client-config form shows
per-declaration-type BCCT counts so an excluding config is visible before it hurts.

## User Stories

1. As agency dossier staff, I want materials bought from a flagged Vietnamese supplier to count as originating when their lot's origin is Vietnam, so that the dossier's RVC reflects what the client can legally prove.
2. As agency dossier staff, I want a material row to stay non-originating unless BOTH conditions hold (VN origin on the lot AND supplier flagged), so that flagging a mixed-origin supplier never promotes their Chinese-origin lots.
3. As agency dossier staff, I want the resolver to produce an originating amount per row rather than a yes/no on the material, so that a line partially covered by VN lots is credited exactly its VN portion.
4. As agency dossier staff, I want column (9) filled automatically at Tính, so that I stop hand-editing the exported workbook.
5. As agency dossier staff, I want to choose per client whether column (9) shows the country of origin or the qualification label ("Việt Nam"/"Không xuất xứ"), so that each client's filing convention is reproduced.
6. As agency dossier staff, I want to override the column-9 convention per dossier, so that one client can file both conventions across different markets/forms.
7. As agency dossier staff, I want the column-9 convention applied identically on the web grid and every export format, so that what I check on screen is what customs receives.
8. As agency dossier staff, I want lots with unknown origin to render a configurable label (default "Không xác định"), so that Johnson's historical "Không xuất xứ" convention can be matched without a code change.
9. As agency dossier staff, I want a real-but-unmapped country string to render as-is with a non-blocking warning, so that a display-vocabulary gap never blocks issuing a dossier whose numbers are correct.
10. As agency dossier staff, I want column (12) to read "Phụ lục X/<tên NCC>" on qualifying rows, so that the claim and its evidence reference ship together the way the agency already files them.
11. As agency dossier staff, I want a warning when column (13) is blank because no document date is on file, so that I know to attach the paper Phụ lục X when submitting.
12. As agency dossier staff, I want a BOM line whose lots resolve to different origins split into one row per origin, so that no single cell has to carry two contradictory origin statements.
13. As agency dossier staff, I want split rows to keep the merged-declaration behaviour within each part and to sum exactly to the line's total, so that the bảng kê totals and LVC do not change shape.
14. As agency dossier staff, I want my per-material edits (rename, code, delete, substitute) to survive recalculation and row-splitting, so that finishing work on a sheet is not lost when origin resolution lands.
15. As agency dossier staff, I want overrides bound to the BOM version they were made against, so that "line 3 of version 1" is never silently applied to "line 3 of version 2" after a version switch.
16. As agency dossier staff, I want a per-client supplier screen listing every BCCT supplier with row counts, origin mix, and its current evidence flag, so that I can curate flags against the data instead of typing free-text names.
17. As agency dossier staff, I want to flag a supplier by choosing the evidence kind (Phụ lục X or import C/O), so that the bảng kê evidence column composes the correct label now and phase-2 in-bloc work has its slot reserved.
18. As agency dossier staff, I want two suppliers with visibly similar names (e.g. a VN company and its HK namesake) treated as distinct entries, so that flagging one never silently flags the other.
19. As agency dossier staff, I want to be able to flip a supplier flag at any time in either direction, so that the app records current evidence reality instead of forcing a knowingly false flag.
20. As agency dossier staff, I want turning a flag OFF to show me the locked sheets whose snapshots relied on that supplier (case, sheet, originating amount) before I confirm, so that I can see the legal exposure I am accepting.
21. As agency dossier staff, I want turning a flag ON to tell me which locked sheets could benefit from re-opening and recalculating, so that understated dossiers can be found without auditing by hand.
22. As agency dossier staff, I want every flip logged append-only with who did it and when, so that a customs verification years later can reconstruct what the agency knew.
23. As agency dossier staff, I want locked sheets to remain exactly as filed no matter what flags, configs, or modes change afterwards, so that the app's record always matches the submitted paper.
24. As agency dossier staff, I want flipping the column-9 mode to mark affected calculated-but-unlocked sheets stale and show a mismatch chip on locked ones, so that a dossier never silently mixes two conventions.
25. As agency dossier staff, I want a sheet with shortage (consumption exceeding matched lots) to be blocked from chốt and export with a reason that names the shortage, so that I cannot accidentally issue an unlawful bảng kê.
26. As agency dossier staff, I want the shortage remedy to be "supply the missing document" (match the declaration / enter the VAT invoice), never an estimated price, so that every value on the bảng kê cites a document.
27. As agency dossier staff, I want a material with no matched lot at all to stop receiving a fallback price from the BOM/catalog, so that RVC is never computed from a number no document backs.
28. As an agency admin, I want the DNCX preset to include E13 alongside E11/E15, so that onboarding a new DNCX client does not silently drop their on-spot domestic purchases.
29. As an agency admin, I want the client-config form to show per-declaration-type BCCT row counts and warn me at save time when my eligible-types list would exclude a type present in the client's data, so that a filtering mistake is visible before it produces false shortages.
30. As an agency admin, I want the country-name normalization table visible read-only in the UI together with my client's own unmapped origin strings, so that I can review the vocabulary without being able to corrupt it.
31. As agency dossier staff working on Growatt, I want to flag Mingjie VN and Minghui VN through the UI on day one, so that the feature's first beneficiary needs no seed script.
32. As agency dossier staff working on Johnson, I want zero behaviour change while Johnson has no flagged suppliers, so that dossiers that are legally correct today stay byte-identical.

## Implementation Decisions

All decisions below are settled ADRs (2026-07-10/11); the sequencing at the end is the
agreed build order.

**Resolution rule.** A material row is originating iff its lot's `origin_country`
normalizes to VN AND its supplier carries a current evidence flag. Conservative
default `non_origin`. Resolution runs per row at Tính and is never persisted onto the
material — moving the flag store later only changes where it is read from. The
resolver returns an originating **amount**, not a boolean (needed by split rows;
reused unchanged by ATIGA partial cumulation in phase 2).

**Row grain and splitting.** Bảng kê grain stays one row per BOM line (matches the
agency's submitted workbooks). When one line's lots resolve to different origins, the
line fans out at render time into one row per resolved origin — the source materials
list is unchanged. Split-row identity = `(material_sequence, origin_status,
column9_text)`; in qualification-label mode `column9_text` is a function of
`origin_status` alone so the key degenerates naturally, and in country mode CHINA vs
TAIWAN lots split correctly — one rule, no mode conditional.

**Override identity.** Per-material overrides re-key from the positional render index
to `material_sequence` (manually added rows keep `added_<n>`). No new persisted UUID —
a BOM version is an immutable artifact, so (version, position) is the robustness
ceiling. The binding becomes version-aware (keyed with the BOM version artifact id, or
overrides drop on version switch), which also closes the pre-existing bug where an
override made against one version misapplies to the same position of another. Legacy
positional keys migrate deterministically (index+1).

**Column (9).** Two modes: `country` (Vietnamese country name; default) and
`qualification_label` ("Việt Nam"/"Không xuất xứ"). Scope = client-config default +
per-case override; deliberately no per-sheet knob (a dossier is one C/O). One
resolver function owns the precedence. The mode is read once per Tính, threaded down
the existing product→material funnel, and materialized onto each row as
`bang_ke_origin_text` (plus the mode stamped on the product). All three export
renderers and the web-grid cell become pure readers of the materialized text —
export == web holds by construction. The `column9_text` function must not touch
`origin_status`: money columns (7)/(8) and LVC are identical across modes.
Mode flips mark mismatched calculated sheets stale, leave draft/bom_loaded alone,
never touch locked sheets (mismatch chip + warning instead), and get a three-belt
re-check against the save-route status hardcode.

**Country normalization.** A new code-owned normalization module: raw BCCT
string → ISO, ISO → Vietnamese display name, seeded from the observed BCCT vocabulary
(~30 entries). Applied at Tính, country mode only. Unmapped string → render the raw
string + non-blocking material warning; never a lock/export block. The table is
git-versioned and tested, not admin-editable; a read-only UI view shows the mapping
plus the client's own unmapped strings.

**Unknown-origin label.** New client-config key `bang_ke.unknown_origin_label`,
free-text input on the existing client-config form, code default "Không xác định".
Applies to the unknown bucket only (UNKNOWN / KHONG XAC DINH / blank) — it must not
swallow present-but-unmapped country strings. One more input to the column-9
materialization; renderers stay pure, so editing it never rewrites locked sheets.

**Supplier evidence store.** One append-only Postgres table via the standard
migration chain: `co_supplier_evidence_events(client_id, supplier_key, supplier_name,
action on|off, evidence_kind phu_luc_x|co_import, actor_id, actor_email, note,
created_at)`. Current state = latest event per `(client_id, supplier_key)`; the table
is itself the flip log. `doc_no`/`doc_date` are deferred by user directive (additive
migration later); until then column (12) composes "Phụ lục X/<NCC>" from
`evidence_kind` + supplier name, column (13) renders blank with a non-blocking warning
at Tính. Supplier key = one shared, code-owned, whitespace-only normalization of
`consignee_name`, used identically on the curation write path and the Tính read path.
No branch/parent auto-merge — the same real supplier under two spellings is flagged
twice, explicitly. CO-side placement is settled (the flag feeds no Data Hub
computation; the damage list needs CO snapshots; append-only audit precedent exists in
CO); the DH migration path and its triggers are recorded in the ADR — do not design
for them now.

**Snapshot enrichment.** Tính materializes onto each row the `supplier_key` and the
exact (12)/(13) text used. Locked sheets are therefore self-contained: later flips or
document corrections never rewrite them, and the ON→OFF damage list is computable on
demand from snapshots with no extra persistence.

**Flip lifecycle.** Both directions always allowed. ON→OFF requires an explicit
confirm rendering the computed damage list (locked sheets whose snapshots counted
this supplier's rows as originating: case, sheet, originating amount). OFF→ON shows
an info note ("N locked sheets could benefit — mở chốt + Tính lại"). Actor comes from
the DH JWT. No effective-dating or validity windows — validity-dated evidence is the
recorded trigger for the future DH migration, not something CO builds now.

**Curation screen.** New per-client screen. Supplier list derived live from BCCT
(row counts, origin mix, current flag, flip control with the confirm flows above).
Any authenticated operator may flip; every flip is logged; the DH `role` claim is
available for gating later. The BCCT per-supplier/per-type aggregation sweep is
shared with the config-form counts.

**Shortage guard.** Shortage blocks issuance via the established three-belt pattern:
(1) flagged in the calculated-sheet-status derivation, (2) re-checked in the lock
gate, (3) added to the export blockers — plus a shortage-specific lock-block reason
so the user is not looped through "press Tính → re-block". The fallback-price path
for no-lot materials is removed (such a line is 100% shortage → blocked anyway).
HARD constraint from adversarial review: this change must not remove or ride with
removing the status-downgrade branches — `missing_price` is enforced only by that
downgrade today, and deleting it without a re-check would make missing-price sheets
lockable through the save-route bypass. The status-enum refactor is out of scope.

**Declaration-type preset.** The `dncx` preset becomes `["E11","E13","E15"]`. No
live client config is edited (`[]` = no filter is correct for the current clients).
The client-config form gains per-declaration-type BCCT counts and a non-blocking
save-time warning when a type present in the client's data would be excluded.

**Data contract.** No Data Hub change. Both inputs (`origin_country`,
`consignee_name`) already reach CO from BCCT rows; they are plumbed from the lot into
the sheet material dict at Tính. All DH access stays behind the existing adapter.

**Migration behaviour.** No backfill. Previously persisted sheets keep rendering
blank column (9) (materialized text → legacy field → empty fallback); the first Tính
after deploy materializes them. Config migration auto-adds the new defaults. Locked
pre-feature sheets are untouched until a human re-opens them.

**Build order (7 tickets, dependencies respected):**
1. Plumb `origin_country` + `consignee_name` + `supplier_key` into the sheet material
   dict at Tính (column (9) is blank in prod today; the damage list and (12)/(13)
   need `supplier_key`).
2. Re-key overrides positional-index → `material_sequence`, version-aware; render-split
   fan-out.
3. Shortage three-belt guard + lock-block reason (ships independently — legal urgency).
4. Column-9 mode + origin-country normalization module + `bang_ke.unknown_origin_label`
   config field + (12)/(13) text materialization into the snapshot.
5. `co_supplier_evidence_events` migration + curation screen + flip flow (ON→OFF
   damage-list confirm, OFF→ON info) + shared normalization function.
6. Per-row VN resolver (`origin_country`→VN AND supplier flag) — the feature.
7. Independent, any time: `dncx` preset +E13 + config-form per-type counts.

## Testing Decisions

A good test asserts external behaviour at the highest seam that exercises the rule —
what a case produces, what a route returns, what an export contains — never internal
call shapes. Three seams (confirmed with the user 2026-07-11):

1. **Tính recompute seam (primary).** Build a case (BOM + stock lots + client config +
   supplier evidence), run the sheet recompute, assert on the produced sheet context:
   the AND rule (flagged supplier + non-VN lot stays non-originating; unflagged
   supplier + VN lot stays non-originating; both → originating amount), split-row
   fan-out and identity, split parts summing to the line total, materialized
   `bang_ke_origin_text` and (12)/(13) text, unknown-label and unmapped-raw-string
   behaviour, warnings. Regression pins: the same case in both column-9 modes yields
   identical (7)/(8) money totals and LVC; a client with zero flagged suppliers
   (Johnson) yields byte-identical sheet context before/after the feature.
2. **Route seam (TestClient).** The shortage guard's three belts individually — status
   derivation, lock gate, export blockers — including the save-route hardcode bypass
   (prior art: the `declarable_unmatched` guard tests). Curation screen: list
   derivation, flip ON/OFF, ON→OFF damage-list contents computed from locked
   snapshots, OFF→ON info payload, append-only event log with actor, evidence_kind on
   the event. Config form: unknown-label save/load, per-type counts, save-time
   exclusion warning. Mode flip: calculated sheets go stale, locked sheets untouched +
   mismatch surfaced.
3. **Pure-function seam.** The origin-country normalization module (raw→ISO→VN label)
   and `column9_text(mode, origin_status, country_label_vi)` tested directly as
   vocabulary tables; `column9_text` proven independent of anything but its inputs.

Export parity is an assertion, not a seam: renderers read only materialized fields,
so tests compare rendered export output against the web-grid data for the same sheet
(prior art: the 2026-06-25 export==web work). Override re-key migration gets a
deterministic legacy-key → `material_sequence` test plus a version-switch case
proving an override no longer crosses versions.

Prior art to mirror: the `declarable_unmatched` guard test file for three-belt
structure; the substitute-stock/claims route tests for TestClient patterns; the
events-store precedent for the append-only table (file-mode no-op, DB-mode real).
The default suite runs file-mode with no `.env`; DB-backed tests for the new events
table follow the existing DB-test conventions.

## Out of Scope

- **Phase 2 — in-bloc cumulation** (Form D/AK/etc.). Deferred until a client actually
  files or concretely plans a preferential dossier. Three pinned constraints phase 1
  must not violate: in-bloc resolution is form-scoped; in-bloc evidence is
  consignment-grain (per-lot); ATIGA partial cumulation changes only the number in the
  amount-based resolver.
- **`doc_no`/`doc_date` on evidence events** (deferred by user directive; additive
  migration later). Until then (13) is blank + warning.
- **Status-enum refactor / readiness-chip work.** The shortage guard must not touch
  the status-downgrade branches. The chip is a separate, optional ticket.
- **Per-row editing of column-9 text.** Rejected after adversarial review (key-space
  category error against material-scoped overrides). If ever requested, it is a
  separate sub-row-keyed `origin_text_overrides` map applied at a split-off
  materialization step — recorded, not built.
- **Admin-editable normalization table**; branch/parent supplier-name auto-merge;
  DH-side supplier entity (triggers recorded in the ADR).
- **The two standing non-grill action items**, tracked separately, not gated on this
  spec: audit already-locked SHORTAGE sheets in prod (claims written — legal
  exposure); deliberate resolution of the `missing_price` one-belt hole.
- **Form X parity** (BACKLOG FX1).
- **Backfill of historical sheets** — first re-Tính materializes; locked sheets stay
  as filed.

## Further Notes

- **Seeding is manual, by design.** Growatt: flag `CONG TY TNHH MINGJIE VIET NAM` and
  `CONG TY TNHH MINGHUI VIET NAM` via the curation UI (both pure E15; 81 + 61 BCCT
  rows). Confirm the exact `consignee_name` spellings against BCCT at build time (the
  query is recorded in the knowledge addendum). Johnson: zero flags. Name trap that
  validates no-auto-merge: `MINGJIE INDUSTRIAL (HK) LIMITED` is a different legal
  entity and must NOT be flagged.
- **Direction of legal risk.** This is the first CO change that moves value out of
  VNM and pushes RVC up — the direction an ex-post customs verification challenges.
  That is why evidence composition at supplier grain, snapshot self-containment, the
  damage list, and the append-only log are load-bearing, not polish.
- **Legal grounding** (verified against promulgating texts, see the two knowledge
  files): NĐ 31/2018 Điều 15.1.g (Phụ lục X is the origin evidence; a VAT invoice
  alone is not), TT 33/2023 Điều 6.1.c, TT 05/2018 Phụ lục VIII columns (7)-(13) and
  Điều 6.4.b (no lawful value for undocumented quantities). Phụ lục X carries a date
  but no number, and excludes Form D.
- **Glossary discipline.** "Xuất xứ" is three different things — column (9) fact,
  columns (7)/(8) money judgment, product-level tiêu chí. Column (9)'s real content
  under the agency's alternate convention is a qualification label, not a country;
  the two modes exist because both conventions are filed in practice.
- **Ticket 7 (`dncx` preset) and ticket 3 (shortage guard) are independent** of the
  rest and of each other; everything else follows the listed order.
