# Session 2026-06-18 — Client feedback batch + criterion-config redesign

Source: client feedback PDF `Barry CO - Trang tính1.pdf` (6 items, screenshots in cols 3-4).
5 commits: `f4c145a` `cf0c192` `54bbd1f` `cb3504b` `afea9db` (pushed at session end → auto-deploy).

## What Was Done

**Triage of 6 feedback items** (4 parallel Explore agents mapped the code):
1a tên NVL hiện thiếu · 1b đề xuất mã không đủ tồn · 2 xuất chứng từ chậm · 3 tiêu chí cấu hình không vào
bảng kê (ra "tiêu chí tổng") · 4 (4a auto phân bổ chi phí trực tiếp, 4b RVC dạng %, 4c CTH không cần tỷ lệ) ·
5 file TKN nặng khó đính Ecosys · 6 BOM mặc định + chốt/chạy-tồn 1 lần.

**Shipped:**
- **Mục 3 (keystone) `f4c145a`** — `hq_sheet_codes_for_product` (`workbook_io.py`) was using fixed
  precedence LVC>RVC>CTSH>CTH (`if "RVC" in …` before `if "CTH" in …`). The CPTPP recommendation
  `"CTH hoặc RVC 30/40/50 tùy công thức"` (co_forms.py) contains both → matched RVC first → exported the
  RVC value-buildup sheet ("tiêu chí tổng") for a CTH dossier. **Fix: first-listed token wins** (positional
  `.find`), PSR keeps absolute priority. +9 tests; full suite 602. **This also resolves mục 4** (4b/4c were
  symptoms of getting an RVC sheet when criterion is CTH; 4a = separate RVC-only feature, deferred).
- **Mục 1a/1b `cf0c192`** — drop `.origin-material-name` 2-line clamp (full NVL name); substitute modal
  `reorderRecommendedByStock()` floats in-stock candidates above out-of-stock after tồn loads;
  `hasEnoughStock` prefers `usable_lot_count`.
- **Mục 2/5 `54bbd1f`** — DH prompt artifact only (CO has no PDF tooling; the merged tờ-khai PDF is DH-owned).
  Asks: per-declaration render cache, `quality=compact` profile, `max_part_bytes` size-bounded split.
- **Criterion config REDESIGN `cb3504b`** (user-requested, backlog B7) — replaced the free-text
  `<input list=datalist>` (black native dropdown) with a **segmented primary-criterion picker** + "hoặc Y"
  alts, over a hidden `criteria_override` input (save/reset endpoint unchanged). Primary written FIRST so it
  aligns with the keystone server fix. Ngưỡng % + cost-buildup reveal only for RVC/LVC; self-matching alt
  hidden; inline read-only summary chip opens the ⚙ panel. `co_case.html` + `app.css`.
- **Mục 4 column M-N `afea9db`** — found the export was writing `source_document_ref/date` into bảng kê
  column M-N (demo leaked "Seed import row 1/3"). M-N = "C/O ưu đãi nhập khẩu / bản khai NCC" = origin-doc
  column (XX1, not built). **Blanked both export paths** until XX1. Backlog XX1 + new EX1.

**Verification done:**
- Unit: 9 new hq_sheet_codes tests; full file-mode suite **602 pass** (+ 205 on export-wiring/renderer/demo).
- UI component harness (puppeteer): segmented picker parse/compose, contextual reveal, 0 JS errors.
- **End-to-end in REAL app**: seeded demo case into a temp store, auth-off server, opened the real
  server-rendered origin sheet + ⚙ modal — CTH→hide threshold/cost, RVC→reveal, 0 JS errors (screenshots
  `.ai/screenshots/2026-06-18-criteria-redesign/`).
- **Export file**: ran `create_hq_bang_ke_workbook` — compound "CTH hoặc RVC…" → sheet title `…ĐẠT TIÊU CHÍ
  "CTC"` (CTH); "RVC 40%" → `…"RVC"`. M-N blank; K=số TK, L=ngày (auto when material has date), O=dòng (hidden).

## Decisions Made
- **Criterion config: unified ⚙ panel + segmented picker** (user picked via AskUserQuestion over polished-inline /
  minimal-restyle, and segmented-buttons over combobox / grouped-select). Lowest-risk integration: hidden input
  keeps the existing save flow; segmented control is a "view" that parses/composes the criterion string.
- **Column K = số tờ khai only** (no line) for now — verified the official form (print_area A:N) has NO visible
  line column; "dòng hàng" is a hidden helper (O). User: keep số-only now, **make it configurable later (EX1)**.
- **Column M-N blanked**, not deleted — header kept; will be filled by XX1 (origin-materials' preferential C/O).
- DH-owned work (PDF perf/size) → request artifact, not CO code.

## What Didn't Work
- **Initial CSS harness looked broken** (flat buttons): NOT a real bug — CSS vars are on `body[data-theme]`,
  not `:root`; harness lacked the attr. Diagnosed via CDP `CSS.getMatchedStylesForNode`.
- **Real `[hidden]` bug found**: `.origin-config-row{display:flex}` / `.criteria-alts label{display:inline-flex}`
  override the `[hidden]` attribute (equal specificity, author wins) → threshold row + self-alt stayed visible.
  Fixed with `setShown()` (inline `style.display`).
- **Server/infra thrash (exit 144)**: foreground `sleep` is blocked by the harness; `pkill -f "8003"` self-kills
  the running shell (its cmdline contains "8003"). Switched to `fuser -k <port>/tcp` + `setsid … & disown`.
- File-mode has auth gating + the demo case isn't persisted by default (KeyError until seeded with record
  fields `case_id`/`updated_at`). Seeded into temp `CO_CASE_STORE_ROOT` (never the live `data/` symlink).

## Open Items
- Mục 6 (BOM default per-client + batch lock/stock) — cheap, infra exists; not started.
- Mục 4a (auto cost-allocation fixed-ratio, RVC clients) — not started.
- Mục 2/5 — blocked on Data Hub (prompt sent).
- EX1 (configurable column-K ref) — noted, not started.
- XX1 (origin NVL → M-N + branch) — M-N now reserved/blank; L date wired.
- Optional: add `import_declaration_date` to demo materials so demo exports show column L.
