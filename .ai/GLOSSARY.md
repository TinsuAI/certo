# Glossary

<!-- Format: **Term** — Definition -->

## BOM selection

**BOM version precedence** — The ordered rule that decides which product BOM
version a sheet actually calculates against: **explicit pin (case override) >
client default > DH aggregate composition > DH latest usable version**. A pinned
choice is honoured even after Data Hub publishes a newer version — the newest
version does *not* silently win. Single source of truth: the resolver
`resolve_selected_product_version(product, …) -> (version, source)`; both the
snapshot writer and the per-sheet row selector call it (before the 2026-07-08
unify these had drifted, causing the client-default layer to be shadowed).

**Case override (BOM)** — A BOM version chosen for **this dossier only**
(`bom_product_artifact_overrides`). Beats the client default. This is what a
per-SP "pin" in the batch picker records.

**Client default (BOM)** — A BOM version a client prefers across **all** their
dossiers (`bom_default_store`, keyed by `client_id`). Applies when this dossier
has no case override.

**source / provenance (BOM version)** — Which precedence step won the selection
(`pin` / `case_override` / `client_default` / `dh_latest` …). Returned by the
resolver and rendered as the picker's "why" label (e.g. *"#N · mặc định khách"*,
*"#N · mới nhất (chưa ghim)"*, *"user chọn"*).

## Material & lot codes — the vocabulary (see `docs/co-stock-architecture.md §4`)

The trừ-lùi/stock pipeline uses **seven distinct code concepts**; each wears several
names as it crosses the DH→CO→BOM boundary. This table is the single source of truth
for which name means what. **The golden rule: an *identity* code is immutable and
safe as a key; the *derived* `allocation_code` is recomputed from config and must
never be a persisted key.**

| # | Concept | Canonical name | Other names in code (same value, different stage) | Kind |
|---|---|---|---|---|
| 1 | Code declared on the customs line (**lot identity**) | `customs_item_code` | DH `customs_code`; CO `item_code`; `co_stock_claims`/`co_stock_events`.`customs_code`; material-row `customs_material_code` | **identity** — immutable, part of lot key `(declaration_no, line_no, customs_item_code)` |
| 2 | The agency's own material code (mã NPL) — BOM leaf + catalog | `material_code` | `internal_code`, `internal_material_code`, `material_identity.internal_code` | source (BOM/catalog identity) |
| 3 | DH-resolved identity dict on a BCCT line | `material_identity` | sub-keys `resolved_code`, `internal_code`, `customs_code`, `resolution_status`, `bom_product_code` | source (nested contract) |
| 4 | Finished good / BOM parent (thành phẩm) | `product_code` | `bom_product_code`, `sheet_product_code`, `product["code"]` | identity (one level **above** the material) |
| 5 | BOM structure/version id | `bom_code` | `ma_bom` | identity (**defaults to `product_code`** when absent) |
| 6 | CO's computed bridge declared→BOM code | `allocation_code` (+ `_status/_source/_confidence/_reason`) | — | **derived — mutable; NEVER a persisted key** |
| 7 | The strategy that computes #6 (CO-owned config, #14) | `config["allocation_code"]` = `{strategy, description_regex, fallback}` | form fields `allocation_code_strategy` / `_fallback` / `description_regex` | config |

**item_code / customs_item_code** (concept 1) — The material code **as declared on
the customs-declaration line**. Immutable, **identity-bearing**: part of the lot key
`(declaration_no, line_no, customs_item_code)`. Whether it **equals** the internal
NVL code (concept 2) is **per client**: for Johnson the declared code and the
internal code are the same string, so all names collapse and the distinction never
shows; for **growatt-vn they differ** (declared `DIOT` vs internal `008.0006100`,
embedded in the lot `goods_name` parentheses) — which is the entire reason concept 6
exists. Named `item_code` on a raw/normalized BCCT row, `customs_item_code` in
`co_stock_rows`, and `customs_code` again on claims/events — a silent re-spelling at
the persistence boundary that is only correct because the value is copied 1:1
(guard it with an invariant test: claim.`customs_code` == source lot.`customs_item_code`).

**material_code** (concept 2) — The stable BOM/catalog identity for a material.
**Overload warning:** on a **`co_stock_rows`** row, `material_code` is NOT the
catalog code — `co_stock_derivation.py:53` / `co_stock_workbook.py:362` set it to the
**derived `allocation_code`** (blank when not usable). So `material_code` means the
catalog identity in a case/BOM context but the mutable bridge on a stock row. Do not
assume the two are the same field.

**allocation_code** (concept 6) — The **CO-derived, normalised** material code,
computed by `resolve_allocation_code(client_config)`. It maps a declared
`customs_item_code` lot onto the code the BOM uses, collapsing several declared codes
into **one logical material**. An **attribute, not identity — mutable**: re-editing
the strategy re-derives it, so it must NEVER be used as a lot/claim key. The claim
ledger is safe (its `claim_id` hashes `source_row` + the stable BOM `material_code`
— neither derived from the strategy); the one live exposure is
`allocation_line_matches_stock` (`co_case_context.py:1097`), which
compares a **persisted** saved-line `allocation_code` against a re-derived one — a
strategy change (e.g. onboarding growatt-vn per #14) can stop a saved line re-binding
to its lot. `_status` is boolean: `resolved` / `unresolved` (one spelling for the
negative state, matching `co_stock_eligibility`'s `unresolved_allocation_code`; distinct
from the config knob `allocation_code.fallback: requires_review`, concept 7). `_source`
is provenance — one of `material_identity`, `strategy_customs`, `strategy_regex`,
`fallback_customs`, `manual` (`""` when unresolved by a regex miss) — so a fallback
resolution is distinguishable from a primary one. `_confidence` is a pure quality ordinal
(`high` / `low`); provenance tags never leak into it (#21).

**stock key candidates** — The set `{material_code, allocation_code,
customs_item_code}` under which the allocation pool aliases each lot
(`co_stock_key_candidates`, `co_case_context.py:1952`; pool built `:2174-2188`). A
code matching **any** of the three resolves to that lot at both preview and calc time
— which is why a substitute identified by any one key still receives its stock when
recalculated. In-memory only (rebuilt each render), so the mutable `allocation_code`
member is safe here; it is NOT safe when persisted (see concept 6).

**substitute candidate identity** — The grain at which the substitute picker
presents a swap-to material. Substitution is chosen at the **logical-material**
level, so the identity is `allocation_code` **when resolved** (one row per logical
NVL, tồn aggregated across its declared lots), falling back to `customs_item_code`
when unresolved. Grouping is display-only; it does not touch lot identity.

**declarable_unmatched** — A Data-Hub **catalog classification**
(`customs_relevance == "declarable_unmatched"`), meaning "a real, declarable-class
material with **no BCCT import match** (no HS/CIF)". CO only echoes DH's value — it
never manufactures it. DC3c hard-blocks lock/export while any active material
carries it (it would be export-excluded yet add 0 to VNM → inflate LVC).
**Crucially it is NOT "missing catalog metadata".** A substitute sourced from
`co_stock_rows` has a BCCT import match *by construction* (stock IS materialised
import lots, carrying `hs_code`/`unit_value`/`customs_item_code`), so it is the
opposite of unmatched: a stock code absent from the catalog gets an empty
`customs_relevance` → **not** declarable_unmatched → not blocked. Build a
stock-sourced substitute's row from the **stock lot's** name/HS/value; the catalog
join is enrichment (canonical name, origin_status), never a precondition for
declarability.

## Xuất xứ (three distinct things, one Vietnamese word)

Verified against the promulgating forms of TT 05/2018 (Phụ lục VIII, RVC). Do not
collapse these — they are three different columns answering three different questions.

**nước xuất xứ** — Column (9) of the bảng kê. A **fact**: the country the material
came from, taken from the import declaration (`origin` in `hub.bcct_rows` → CO's
`origin_country`). Free text, not ISO (`VIETNAM`, `CHINA`, `UNKNOWN`, `HG.KONG`…).
A non-member country is written as itself — writing "không có xuất xứ" here is wrong,
because the qualification is expressed by columns (7)/(8), not by this cell.

**trị giá có / không có xuất xứ FTA** — Columns (7)/(8), both **money**, under the
merged header *Trị giá (USD)*. The **judgment**: whether the material qualifies as
originating *for the FTA of the C/O being issued*. "FTA" is form-relative — a Korean
input is originating for AK, not for D. `origin_status` in the code decides which
column the value lands in. In Phụ lục VII (LVC) the same pair reads *Trong nước /
Nước ngoài*.

**tiêu chí xuất xứ** — the finished product's rule (WO / CTC / RVC / LVC), a property
of the *product and form*, never of a material row. Rendered as *Tiêu chí áp dụng* in
the bảng kê header, not a column.

**Bản khai báo xuất xứ (Phụ lục X)** — The supplier's origin declaration; the client
calls it "PL X". The **evidence** that lets a domestic material's value sit in column
(7). Per NĐ 31/2018 Điều 15.1.g a VAT invoice alone is *not* origin proof (Điều 15.1.i
makes the invoice a cross-check document). The form is keyed to **one VAT invoice**
(fields: nhà sản xuất, mã số doanh nghiệp, số lượng, trị giá FOB, *hóa đơn GTGT*), carries
a **ngày but no số**, and its body certifies the goods were *produced at the signer's own
factory in Vietnam* and meet a named criterion. Its *Ghi chú* excludes **Form D**.
Referenced by bảng kê columns (12)/(13) — alongside *C/O ưu đãi nhập khẩu*, which is the
same slot's evidence for an imported originating input.

**tồn CO** — "inventory for C/O purposes", NOT "C/O documents on hand". The agency's
`BẢNG THEO DÕI TỒN CO.xlsx` (verified 2026-07-11) is a material-level import inventory:
one row per import-declaration line item with `Đã xuất`/`Tồn` draw-down columns — the
feed for the trừ-lùi engine. The agency keeps **no register of incoming C/O documents**;
do not read "tồn CO" as evidence tracking.

**Form X** — a second **non-preferential** VCCI C/O template the agency produces from the
trừ-lùi workbook (sheet `FORM X`, alongside `FORM B`). Not modeled in `app/co_forms.py`
(BACKLOG FX1). Not an FTA form; irrelevant to cumulation.

## Runtime modes

Two **independent, instance-wide** toggles plus one DH-side per-client field. There is
**no "DH-mode client"** — the source backend is global, so in a given CO instance either
all clients read from Data Hub or none do.

**Source backend** (Axis 1, global; `portfolio.py:247`) — where CO reads *source data*
(materials, BCCT/lots, BOM) and who owns `client_config`. **DH source-mode**
(`DATA_HUB_ENABLED=1`) → `DataHubPortfolioService`; source config incl. `allocation_code`
is owned by Data Hub and `save_client_config` from CO is read-only
(`data_hub_client.py:673`). **Local source-mode** (`CO_ALLOW_LOCAL_SOURCE=1`, DH off) →
`PortfolioService`, config CO-owned/writable. **Neither** → 503 `SourceBackendUnavailable`
(prod safety default; never silently serve stale local backup). Prod runs DH source-mode.

**Persistence backend** (Axis 2, global; env `BARRY_DATABASE_URL`) — where CO stores *its
own* state (cases, claims, **client overlay** `bang_ke_overrides`/`export_overrides`/
`co_stock_overrides`, stock ledger). **DB-mode** (URL set) → Postgres; **file-mode**
(unset) → on-disk `cases.json` (`co_case_store.py:1063`). Independent of Axis 1: local dev
and prod both run DH-source + DB simultaneously. The CO client overlay is writable in
DB-mode even while the Axis-1 source config is read-only — that is the seam a CO-side
per-client override (e.g. allocation strategy for growatt-vn) uses.

**code_resolution_mode** (DH-side, **per-client**; `hub.clients`) — `identity` /
`simple_mapping` / `batch_aggregate_resolution`. How Data Hub resolves material codes when
building BOM artifacts (growatt-vn = `batch_aggregate_resolution`). DH-internal; unrelated
to CO's `allocation_code.strategy`. The only genuinely per-client "mode".
