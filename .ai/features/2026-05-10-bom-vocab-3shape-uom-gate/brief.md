# Feature: BOM vocab cleanup + 3-shape grouping + UoM ingest-time gate

Captured 2026-05-10 sau session audit BOM UI. Ba tracks độc lập về scope
nhưng cùng theme "BOM UI/ingest phải phản ánh đúng design hiện tại
(post-mig-031 vocab + project_bom_3_shapes + UoM standardization)".

## Scope

Ba tracks. Mỗi track ship riêng 1 commit (hoặc 1 PR khi gộp lại). Không
bundle vì độ rủi ro + reviewer effort khác nhau.

### Track A — Vocab cleanup (templates + i18n)

**In:**
- `app/templates/clients/bom.html` — đổi cột "Versions", badge
  "×N variants" (xem track B cho semantic fix), label "v{n}".
- `app/templates/clients/bom_artifacts.html` — h2 "Lịch sử phiên bản"
  → "Bản lưu", cột "v#" → "Bản lưu #" hoặc "Artifact #",
  ẩn cột "variant" khi mọi row = 'default' (toggle theo data, không
  hard-hide).
- `app/templates/clients/bom_artifact_detail.html` — h2 + Provenance
  table "Variant" row ẩn khi 'default'.
- `app/templates/clients/_bom_macros.html` — `lineage_node` ẩn variant
  span khi 'default'.
- `app/templates/clients/bom_preview.html` — cột "Variant" ẩn khi
  'default'.
- `app/templates/clients/bom_presets.html` — option text drop "default"
  string khi không có giá trị thực.
- `app/templates/clients/bom_flatten_preview.html` — i18n keys
  `flatten.stat.versions`, `flatten.versions.title`,
  `flatten.action.materialize`, `flatten.versions.variants`.
- `app/i18n.py` — `bom.col.versions`, `bom.versions_title`,
  `bom.versions_back`, `bom.versions_immutable`, `bom.bom_variant`,
  `bom.subtitle`, `bom.upload_help`, `bom.adapter.*.desc`,
  `flatten.stat.versions*`, `flatten.versions.*`,
  `flatten.dec.choose_btp_variant.*` — review từng key, đổi VN sang
  vocab "bản lưu" / "shape" / "preset"; EN giữ "artifact" / "shape" /
  "preset".

**Out:**
- Đổi tên column DB (`bom_variant_id`, `n_versions` SQL) — đụng
  schema, để track riêng nếu cần.
- Xoá 308 redirect aliases — đã có entry BACKLOG riêng.

**Effort:** 2-3h (label-only, không đụng logic). Test: snapshot
test ~3-5 templates đảm bảo không regress strings.

### Track B — Group 3 shapes thành 1 phiên bản logical (list page)

**Vấn đề gốc:** `app/stores/bom.py:432 list_products_with_bom` aggregate
theo `product_code` only. Không phân biệt phiên bản logical (tuple
`(client, product, variant, lineage_root)`) vs bản lưu (artifact rows).
Kết quả: list page show `n_versions = total artifacts`, badge
"×N variants" misuse `count(distinct flatten_strategy)`.

**Design mục tiêu:**

List page row = 1 phiên bản logical. Cột:
- Mã sản phẩm
- Kind (TP/BTP)
- Số phiên bản (= count distinct lineage roots)
- Số bản lưu / phiên bản latest (= 3 typical cho phiên bản đầy đủ)
- Shape availability (raw_graph ✓ / shallow ✓ / full_flat ✓)
- Trạng thái phiên bản latest (flattened/non_flattened/mixed)
- Last published

Click row → `bom_artifacts.html` (đã có), nhưng artifacts cũng group
theo phiên bản (collapsible).

**Schema option:**
- Option 1 (no schema change): compute `lineage_root_id` qua recursive
  CTE walking `parent_artifact_id` backward. Group key =
  `(client_id, product_code, bom_variant_id, lineage_root_id)`. Đắt
  query — phải walk recursive cho mỗi product khi list page render.
- Option 2 (schema): add `lineage_root_id` stored column trên
  `bom_artifacts`, populate trigger on insert (root = parent's root
  hoặc self khi parent NULL). Backfill via recursive CTE 1 lần.
  Index `(client_id, product_code, lineage_root_id)`. Query rẻ.
  ~1 mig + backfill + index.

**Recommendation:** Option 2. List query chạy mỗi pageview, recursive
CTE per product không scale. Migration cost ~1-1.5h, backfill 1 lần.

**Out (Phase 2):**
- Group artifacts page (bom_artifacts.html) cũng theo phiên bản —
  defer; track A đã sửa h2 + cột là đủ usability cho mức hiện tại.
- `case_id` dimension (per glossary tuple) — chưa có cột, CO chưa
  ship; defer.

**Effort:** Option 2 = ~4-6h. Mig + backfill + store query rewrite
+ template + 3-5 tests + screenshot.

### Track C — UoM ingest-time gate (BOM + BCCT preview)

**Vấn đề gốc:** Drift UoM giữa BOM/BCCT/catalog chỉ lộ ra ở:
- View time: catalog detail `_uom_drift` warning panel.
- Materialize time: flatten engine emit decisions
  (`global_uom_conversion`, `non_alias_uom_conversion`, etc.) trên
  flatten preview.

Upload preview của BOM raw + BCCT thì silent — file ghi 'gam', catalog
ghi 'kg' → vào DB raw không có warning.

**Design mục tiêu:**

Thêm helper `compute_uom_drifts(client_id, rows: list[parsed_row])` →
list `{material_code, source_uom, catalog_uom, bcct_uom, canonical_a,
canonical_b, severity}`.

Wire vào:
- `app/routes/bom.py` upload preview path (sau `_stash_pending`,
  trước render). Render banner trên `bom_preview.html`.
- `app/routes/bcct.py` upload preview path (tương ứng).

Banner mỗi mã có drift: ô warning "Mã X: file ghi 'gam' (mass), catalog
ghi 'kg' (mass) — sẽ convert factor 0.001 khi materialize. ✓ confirm
hoặc skip mã này."

**Severity rules:**
- Same canonical (alias dùng equivalent) → không show.
- Same dimension/family, different canonical → "convertible" banner
  (info, info-level).
- Different dimension (mass vs count) → "incompatible" banner
  (warn, requires acknowledgement before confirm upload).
- One side missing canonical → "unknown unit" banner (info).

**Out:**
- Auto-convert at ingest (= rewrite parsed rows). Quá xâm lấn,
  flatten engine đã làm tại materialize time và staff confirm explicit.
  Ingest gate chỉ surfaces, không mutate.
- BCCT-side BCCT-vs-BCCT drift across upload batches — defer; này là
  dossier-level concern.

**Effort:** ~3-4h. Helper + 2 route wires + 2 banner blocks + tests.

### Track D — Dependency staleness / invalidation (post-MVP, defer)

**Vấn đề gốc:** BOM artifact (đặc biệt shallow + full_flat materialized)
chứa derived fields phụ thuộc external state. Khi external thay đổi,
artifact stale silently. Ví dụ user đưa ra:

> "Xuất hiện BOM BTP A. Trước đó chỉ treat BTP A as leaf (nvl), nhưng
> bây giờ có BOM của BTP A → A trở thành decomposable."

**Các chiều staleness đã xác định** (không exhaustive):

1. **Catalog category change.** A đang là `nvl` (leaf). Sau khi staff
   accept candidate hoặc bootstrap BTP roster, A → `btp_sx`. Shallow
   walking đáng lẽ stop tại A, nhưng artifact cũ đã walked through;
   full_flat đã explode A's children rolled vào parent. Hai shape đều
   stale.
2. **BTP BOM xuất hiện sau.** Trước: A có category `btp_sx` nhưng
   không có BOM riêng → flatten unresolved `missing_child_bom`. Sau:
   ingest BOM của A → A decomposable. Existing parent's full_flat
   stale (A's leaves vẫn là A bản thân thay vì A's children).
3. **Catalog Accept (mã chờ duyệt).** Code chưa trong catalog →
   classification engine treat as unknown. Sau accept → có category +
   uom + production_source. BCCT observed signals + flatten classification
   thay đổi.
4. **Code mappings thay đổi.** NB↔HQ mapping update → material
   identity resolution shift. BCCT observed counts (paren-extract)
   change. BOM artifact's referenced material_code có thể trỏ qua
   identity khác.
5. **Parser rules edit.** `client_parser_rules` thay đổi → derived
   `internal_code` cho BCCT rows shift. Ảnh hưởng cross-source
   warnings + candidate refresh.
6. **UoM standards / aliases mở rộng.** Mig 051 thêm 50 aliases. BOM
   raw đã ingest với UoM 'PIECES' = unknown alias trước mig; sau mig
   resolve về canonical 'pcs'. Flatten cũ stale (đã treat as
   unresolved); cross-source warning suppress nay đáng lẽ silent.
7. **`materials.uom` change.** Catalog edit UoM của 1 material → flatten
   convert factor thay đổi → full_flat qty drift.
8. **Sourcing decision change.** Catalog `btp_sourcing` per-BTP edit
   từ "purchased" sang "self_produced" → preset sourcing override
   logic thay đổi → resolved BOM khác.

**Current state — partial mitigations:**

- `scripts/materialize_shallow_and_full_flat.py` — manual re-run.
- `derive_btp_shallows.py` (BACKLOG "Phase 3c follow-ups") — manual.
- `post_ingest_hooks` adapter contract scaffolded nhưng chưa wire
  vào confirm flow.
- `material_observations.py` — request-time recompute cho catalog
  detail page (workaround per BACKLOG "v_material_roles paren-aware").
- `catalog_candidates` refresh — manual button click.
- 0 centralized "X depends on Y, Y changed → X stale" tracking.

**Design options (chưa pick):**

1. **Staleness flag + manual refresh button.** Mỗi artifact có
   `is_stale boolean` + `stale_reason text`. Triggers/event handlers
   set `is_stale=true` khi dependency thay đổi. UI hiện badge "⚠
   stale — refresh". Staff click → re-materialize.
   - Pros: simple, transparent, staff-controlled.
   - Cons: noisy nếu nhiều dependency churn; mỗi dependency cần
     trigger riêng.

2. **Eager invalidation cascade.** Mỗi write tới catalog/code_mappings/
   parser_rules/uom_aliases trigger materialize() async cho dependent
   artifacts. Background job queue.
   - Pros: artifact luôn fresh.
   - Cons: complex job infra; rebuild thrash khi staff edit liên tục;
     không transparent.

3. **Lazy compute on read.** Bỏ materialized shallow/full_flat hẳn,
   compute on-demand mỗi pageview/API call. Cache với TTL.
   - Pros: simple correctness; no staleness.
   - Cons: latency BCQT/CO consumer reads; không phù hợp khối lượng
     Johnson 246 TP × 3 shape × 10s recompute = 2h batch.

4. **Hybrid event-sourced staleness ledger.** Bảng
   `hub.dependency_invalidations` (artifact_id, invalidating_event_id,
   detected_at, resolved_at). Triggers append rows; UI surface,
   refresh = batch job dequeue.
   - Pros: full audit trail; aligns với "aggregate-data git-history"
     principle (BACKLOG).
   - Cons: thêm 1 table + job runner; design overhead lớn.

**Recommendation (preliminary):** Option 1 (staleness flag) MVP-mode +
roadmap → option 4 khi bandwidth có. Option 2 quá tham; option 3 quá
chậm.

**Why deferred from current session:**

- Scope >> A+B+C combined. 8 dependency dimensions × design decision
  per dimension → riêng discovery cần ~1-2 ngày.
- Cần audit toàn bộ "what reads from what" trong codebase trước khi
  pick design option (mapping dependency edges).
- Phụ thuộc Track B (lineage_root_id) nếu muốn invalidate group-wise.
- Không block MVP — current manual re-run + view-time recompute đủ
  cho pre-customer demo. Critical chỉ khi multi-customer, churn cao.

**Action:**
- Capture trong BACKLOG.md (entry mới "BOM dependency staleness").
- Cross-link với "Modular BOM ingest adapters" + "Aggregate-data git-
  history" + "v_material_roles paren-aware" — chúng overlap dimension.
- Bring lại sau khi A+B+C ship + khi user signal "có customer thật,
  cần fresh artifacts trên churn".

**Effort (rough estimate when scoped):** 1-2d discovery + design;
2-4d implement option 1 (flag + 8 triggers + UI badge + manual
refresh route); 1-2 week implement option 4.

## Decisions

1. **3 tracks ship sequential, không bundle.** Reviewer surface khác
   nhau (vocab = lint-style; group = schema mig; UoM = logic +
   route). Bundle = critic round 2 sẽ ăn pushback "uncoupled, split".

2. **Track A trước.** Cheapest, unblocks visual signal cho user khi
   review track B/C trên cùng page.

3. **Track B Option 2** (lineage_root_id stored column). Recursive CTE
   per pageview rủi ro perf cho client lớn (Growatt 130+ products,
   852 non-default variants). Trigger + backfill once.

4. **Track C non-mutating.** Surface drift, không auto-convert tại
   ingest. Convert vẫn ở materialize time (flatten engine) +
   client_uom_overrides. Mất tính idempotent + provenance nếu
   convert sớm.

5. **`bom_variant_id` giữ nguyên.** Legacy column với production data
   thật (852 non-default rows). Hide-when-default là UI rule, không
   schema rule.

6. **`n_dual_variants` rename.** Đổi tên thành `n_strategies`
   (semantic chính xác — đếm flatten_strategy distinct), badge label
   thay đổi tương ứng. Nếu muốn badge thật cho dual-source supplier
   variants → query mới `count(distinct bom_variant_id) filter
   (where bom_variant_id is not null and bom_variant_id <> 'default')`.

## Risks

- **Track B mig backfill** trên prod (Growatt + Johnson clones): 4000+
  artifact rows, walking parent chain. Một lần backfill, chạy 30s.
  Test trên local DB trước.
- **Track A snapshot test brittle.** Đổi 1 string break test; chấp
  nhận vì reviewer cần see-diff.
- **Track C false positives** nếu canonical resolver chưa cover alias
  (ví dụ "viên" mới ship mig 051). Mitigation: severity "unknown
  unit" thay vì "incompatible" khi 1 bên không resolve được.
- **i18n VN vs EN drift.** VN block lock vocab "bản lưu" trong khi EN
  block giữ "artifact". Cross-check 2 keys side-by-side trước khi
  ship.
- **Sister apps (CO/BCQT)** không bị break — đụng template + i18n
  client-side, không đổi API surface. Schema mig (track B) chỉ thêm
  column non-null backfilled, không gãy contract.

## Resolved Questions

1. **Track B trigger pattern: BEFORE INSERT trigger.**
   - Computed column (`GENERATED ALWAYS AS`) loại — không reference
     được row khác (parent's root) trong generated expression.
   - Trigger BEFORE INSERT: nếu `NEW.parent_artifact_id IS NULL` →
     `NEW.lineage_root_id = NEW.artifact_id` (self-root); else
     SELECT parent's `lineage_root_id` và inherit.
   - Backfill 1-shot tại mig: recursive CTE walking parent chain,
     update tất cả existing artifacts. Sau backfill cột NOT NULL.
   - Index `(client_id, product_code, lineage_root_id)`.

2. **Track C ack checkbox: required khi severity=warn ONLY.**
   - severity=info (canonical missing, same family same canonical) →
     display-only banner, no checkbox.
   - severity=info (same family different canonical, e.g. gam→kg) →
     display-only banner, no checkbox. Convert sẽ xảy ra tại flatten,
     không cần block ingest.
   - severity=warn (cross-family, e.g. mass vs count) → checkbox
     required "Tôi xác nhận drift này dù không tương thích đơn vị" +
     button "Confirm upload" disabled cho đến khi tick.
   - Lý do: cross-family drift là red-flag (data corruption hint),
     không nên silent-pass; same-family drift là routine convert.

3. **Track A column rename: drop "v" letter entirely.**
   - Badge: `v{artifact_no}` → `#{artifact_no}` ở mọi nơi
     (`bom_artifacts.html`, `bom_artifact_detail.html`, lineage_node
     trong `_bom_macros.html`).
   - Column header: "v#" → "STT" (số thứ tự) trong
     `bom_artifacts.html`.
   - Lý do: "v" là letter của legacy "version", contradict glossary.
     "#" trung tính, match pattern BCCT row_index. h2 đã carry vocab
     ("Bản lưu của <code>") nên column header có thể terse.

4. **Shipping cadence: 3 commits, same session, sequential A → B → C.**
   - Bundle PR-level critic-rejection nguy cơ cao (uncoupled scopes).
   - Same-session OK vì tổng ~10-13h fit 1 working block.
   - Stop-condition: nếu track B mig backfill chậm hơn 60s trên
     Johnson+Growatt clone, hoặc track C surface false-positive
     >5% test set, pause + reassess scope.
   - Order: A (cheap unblock visual signal) → B (schema mig + group
     query) → C (new helper + ingest wire).

## Manual test plan

### Track A
- Login → `/clients/johnson-vn/bom`. Confirm h2/cột không còn
  "version" lone-word. Badge "×N strategies" (hoặc "×N shapes")
  thay vì "×N variants" (semantic giữ count cũ).
- Click product → `/bom/<p>/artifacts`. Confirm h2 = "Bản lưu của
  <code>", cột "variant" hidden (Johnson mọi row variant=
  'agency_2026-04-23' nên KHÔNG hidden — confirm hiển thị).
- Pick artifact → `/bom/artifact/<id>`. Provenance row "Variant"
  hide khi 'default', show khi non-default.
- `/bom/<p>/presets`. Option text không có "default" trống.
- Smoke EN: switch lang → confirm "artifact" / "shape" / "preset"
  vocab.

### Track B
- `/clients/johnson-vn/bom`. Confirm: 1 row = 1 phiên bản logical.
  Số phiên bản match thực tế Johnson (1 phiên bản / TP, có 246 TP).
- Click → confirm artifacts page liệt kê 3 bản lưu của phiên bản đó.
- Growatt: products có nhiều variant → check số phiên bản tăng theo
  count distinct variant.

### Track C
- Tạo BOM file test với 1 mã có UoM khác catalog (ví dụ Johnson
  catalog có mã X = 'PCS', test file ghi X = 'kg'). Upload → preview.
  Confirm banner xuất hiện.
- Test severity: same canonical = silent; same family = info; cross-
  family = warn + checkbox.
- BCCT version: tương tự, upload BCCT có dòng UoM lệch.

## Done criteria

- [ ] Track A: 0 chữ "version/variant" mis-applied trong template
  bom.* (grep + manual check). i18n keys updated. Hide-when-default
  rule wired ở 5 chỗ (bom_artifacts.html cột, bom_artifact_detail
  Provenance row, bom_preview.html cột, _bom_macros lineage_node,
  bom_presets option text).
- [ ] Track B: list page row = phiên bản logical. Badge semantic
  match label. Mig + backfill + index. Test list query <500ms p95
  trên Johnson + Growatt.
- [ ] Track C: drift detect helper + 2 route wires + banner. Severity
  3-tier (info/info/warn). Acknowledgement checkbox khi severity=
  warn.
- [ ] Tests: A snapshot ~3, B store + route ~5, C helper + integration
  ~5. Total ~13 tests.
- [ ] Screenshots: 5-7 (bom list, artifacts, artifact detail,
  preview banner, flatten preview, presets, ingest-banner). Commit
  vào `.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/screenshots/`.
- [ ] Memory updates:
  - `feedback_bom_vocab.md` — mở rộng "How to apply" với Hide-when-
    default rule + n_strategies semantic.
  - Project memory mới: BOM phiên bản tuple identity + lineage_root_id
    column.
- [ ] STATUS.md + commit message reflect 3 tracks split.
