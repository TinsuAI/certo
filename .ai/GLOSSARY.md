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

## Stock / trừ-lùi codes (see `docs/co-stock-architecture.md §4`)

**item_code / customs_item_code** — The material code **as declared on the
customs-declaration line**. Immutable, **identity-bearing**: it is part of the lot
key `(declaration_no, line_no, customs_item_code)`. For Johnson/Growatt it equals
the internal NVL code (audited: trừ-lùi name-prefix "#&" == BCCT customs_item_code
1500/1500).

**allocation_code** — The **CO-derived, normalised** material code, computed by
`resolve_allocation_code(client_config)`. It collapses several declared
`customs_item_code` lots into **one logical material** ("these declared codes are
all really aluminium-100"). An **attribute, not identity — mutable**: re-editing
the mapping re-derives it, so it must NEVER be used as a lot/claim key (that would
orphan claims). May be `resolved` or `unresolved` (`allocation_code_status`); an
unresolved row has no logical-material grouping and falls back to
`customs_item_code`. For clients configured `same_as_customs_code` it happens to
equal customs_item_code, but that is a config special-case, not its nature.

**stock key candidates** — The set `{material_code, allocation_code,
customs_item_code}` under which the allocation pool aliases each lot
(`co_case_context.py:1896`). A code matching **any** of the three resolves to that
lot at both preview and calc time — which is why a substitute identified by any one
key still receives its stock when recalculated.

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
