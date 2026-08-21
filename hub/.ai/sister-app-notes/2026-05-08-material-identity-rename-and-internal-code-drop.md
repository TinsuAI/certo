# Material identity rename + `internal_code` drop + configurable parser rules — shipped

**Date:** 2026-05-08
**For:** CO (`barry-CO-main`); BCQT forward-looking (no consumer yet)
**Data Hub commits:** `046601e..ab09d83` (6-commit series)
**Brief:** `.ai/features/2026-05-08-configurable-bcct-parsing/brief.md`
**Predecessor:** `.ai/features/2026-05-07-bcct-product-identity/brief.md` (mig 032 — superseded)

## TL;DR

Three coupled changes to BCCT identity surface. **Pre-production hard
cut** — no grace-period aliases. Same release window as your consumer
update PR.

1. **Rename**: `product_identity` → `material_identity` everywhere
   (column, jsonb field stays in inner shape; column + API params
   change).
2. **Drop**: `bcct_rows.internal_code` column gone. Computed at runtime;
   exposed only via `material_identity.declared_internal_code` /
   `display_code`.
3. **Configurable rules**: `bcct_adapters/{growatt,identity}.py`
   deleted. `parser_adapter` field in response now reads
   `"client_parser_rules"` (constant).

Bonus: 666 Growatt export rows now resolve to `PV01.xxxx` correctly
(were stuck at `BIENTAN.xx` from a buggy F1 anchor in the deleted
hardcoded regex).

## API contract changes

### Query params (BREAKING, hard cut)

| Old | New |
|---|---|
| `include_product_identity` | `include_material_identity` |
| `product_identity_candidate_limit` | `material_identity_candidate_limit` |

Old names return `400 invalid_parameter` with hint to the new name.

### Response field (BREAKING, hard cut)

`internal_code` field removed from BCCT row response items at every
level on:
- `GET /v1/hub/bcct`
- `GET /v1/hub/bcct/invoice-matches`

The legacy "what was filed" view is now
`material_identity.declared_internal_code`.

The canonical "best display identifier" is
`material_identity.display_code` — equals resolved code when
`resolution_status='resolved'`, else falls back to `customs_code`.

For invoice-matches `item_code` field: previously
`row.internal_code or row.customs_code`. Now
`material_identity.display_code or row.customs_code`. Semantically
identical when resolved; for non-resolved rows you get `customs_code`
either way.

### Top-level jsonb shape (NON-BREAKING, just renamed wrapper)

```json
{
  "material_identity": {                  // was: "product_identity"
    "resolution_status": "resolved",
    "resolved_code": "PV01.0117500",
    "bom_product_code": "PV01.0117500",   // unchanged — alias when material has BOM
    "product_kind": "tp",                 // unchanged
    "selected_candidate_code": "PV01.0117500",
    "display_code": "PV01.0117500",       // CHANGED semantic — see below
    "declared_customs_code": "BIENTAN.17",
    "declared_internal_code": "BIENTAN.17",
    "line_key": {...},
    "resolution_source": "goods_name_embedded_code",
    "confidence": "high",
    "review_status": "system_resolved",
    "parser_adapter": "client_parser_rules",  // CHANGED — was "growatt_bcct"
    "parser_version": "v1",                   // CHANGED — was a date string
    "evidence": {
      "match_rule": "parenthesized_product_code_exists_in_bom_products",
      "matched_text": "(PV01.0117500)",       // CHANGED — was "PV01.0117500"
      ...
    },
    "candidates": [...]
  }
}
```

**Notable `display_code` semantic change**: previously read from
`row.internal_code or row.customs_code`. Now equals `resolved_code`
when resolution succeeds; falls back to `customs_code` otherwise.
For Growatt export rows this matters: `display_code` used to be
`BIENTAN.17` (the customs prefix); now it's `PV01.0117500` (the
resolved canonical). The old value was a side-effect of the
F1-anchor bug; the new value is what your origin-cert flow probably
wanted anyway.

## Consumer migration in CO

Audit found 6 sites in `barry-CO-main` reading the old shape:

| File:line | Old code | New code |
|---|---|---|
| `app/data_hub_client.py:415` | `row.get("internal_code")` | `(row.get("material_identity") or {}).get("declared_internal_code")` |
| `app/data_hub_client.py:426` | same | same |
| `app/data_hub_client.py:438` | same | same |
| `app/data_hub_client.py:538` | same | same |
| `app/bom_service.py:266` | same | same |
| `app/main.py:1794` | same | same |

Or if your fallback chain was `product_code or customs_code or internal_code`,
swap the last clause for `display_code`:
```python
item.get("product_code")
  or (item.get("material_identity") or {}).get("display_code")
  or item.get("customs_code")
```

For any code branching on `parser_adapter` value: rename
`"growatt_bcct"` → `"client_parser_rules"` (or drop the branch — it's
now a constant).

For evidence consumers reading `matched_text`: the value now includes
parens (`"(PV01.0117500)"`), not just the inner capture
(`"PV01.0117500"`). Inner code is still in `product_code`/`resolved_code`.

For the `2026-05-07-co-product-identity-consumer-plan.md` plan file
in your repo: the field is `material_identity` not `product_identity`.
Update the plan + provider tests before merging the consumer PR.

## CI gate

**Don't deploy Data Hub mig 035 until your CO consumer PR merges.**
The break is intentional but coordinated. Both repos in the same
release.

## Schema migrations applied (in order)

```
035_material_identity_and_parser_rules.sql      — schema
036_seed_growatt_parser_rules.sql               — seed: internal_code
037_seed_growatt_material_identity_candidates_rule.sql  — seed: stage 2
038_drop_material_identity_column.sql           — mat_id column dropped
```

Forward-only (no `down.sql`). Pre-prod = OK.

## Update for mig 038 (later same day)

After mig 035 dropped `internal_code` column, the same architectural
principle was applied to `material_identity`: it's a deterministic
function over `(row_data, materials_catalog, parser_rules)` — same as
`internal_code`. Persisting it adds drift + backfill burden.

**Mig 038 drops `bcct_rows.material_identity` column entirely.**
Every API read resolves at runtime. Behavior on the wire is unchanged
(response shape includes `material_identity` per `include_material_identity`
flag) — but:

- **Bulk export performance**: pulling 23k rows now takes ~25-50s
  (vs near-instant when cached). Per-page reads (50 rows) ~50-100ms.
- **`parser_version` snapshot stability**: NOT guaranteed across rule
  edits. If staff change a rule, next read returns the new resolution.
  Previously the persisted value was a snapshot at ingest/backfill
  time. If your code branches on `parser_version` for cache busting,
  understand it's now "current rules version" not "version at row
  ingest time".
- **No column to query**: any SQL doing
  `bcct_rows.material_identity->>...` will fail. Use the API
  endpoint or compute via the resolver in Python.

Idempotency promise (per CO spec): "same query against unchanged
data and same parser version returns same product identity result"
— still holds, with "parser version" reinterpreted as "current rule
set".

## Update for migs 039/040/041 (later same day)

### Resolver stage order swap (mig non-schema, in-app)

Before: Stage 1 (customs_code in materials) → Stage 2 (paren-extract)
→ Stage 3 (reviewed) → ...

After: Stage 2 (paren-extract) → Stage 1 (customs_code in materials)
→ Stage 3 (reviewed) → ...

Rationale: paren-extracted code from goods_name is more specific
signal than customs_code-membership in materials. For Growatt
exports where customs_code is HQ-side (`BIENTAN.20`) and the
agency BOM code lives in goods_name parens (`(PV02.0228801)`), the
paren wins — material_identity now resolves to the BOM code.

Identity-mode clients (Johnson, DKE, Demo) unaffected: no rules
seeded for Stage 2 → empty extractions → falls through to Stage 1
naturally.

Behavior shift for some Growatt rows:
- BEFORE: `display_code = BIENTAN.20`, `resolved_code = BIENTAN.20`,
  `resolution_source = structured_field`.
- AFTER: `display_code = PV02.0228801`, `resolved_code = PV02.0228801`,
  `resolution_source = goods_name_embedded_code`.

### Currency-tag bug fix + payload promotion (migs 039/040/041)

User reported: Johnson row `308382318920-1` had `currency=USD` with
VND-magnitude `total_value=57,456,231.43` — domain mismatch. Root
cause: parser ALIASES conflated FX-domain ("Đơn vị tiền tệ", "Đơn
giá", "Trị giá NT") with VND-converted ("Đơn giá tính thuế", "Tổng
trị giá") into single `currency` / `total_value` / `unit_price` set.

**Schema changes (BREAKING for SQL consumers)**:

mig 039:
- Rename `currency` → `currency_nt` (FX-domain semantic).
- New columns:
  - `total_value_nt numeric(20,6)` — FX-domain total ("Trị giá NT").
  - `unit_price_nt numeric(20,6)` — FX-domain per-piece ("Đơn giá").
  - `total_tax numeric(20,6)` — "Tổng tiền thuế" (VND).
  - `unloading_location text` — "Địa điểm dỡ hàng" (was extracted
    via jsonb in invoice-matches, now first-class).

mig 040:
- New columns:
  - `contract_no text`, `contract_date date` — "Số hợp đồng",
    "Ngày hợp đồng" (sparse, useful for CO origin cert).
  - `internal_mgmt_no text` — "Số quản lý nội bộ".
  - `package_marks text` — "Ký hiệu và số hiệu bao bì".

mig 041:
- Prune 38 typed-already keys from `payload` jsonb (after Tier 1+2
  promotion). Saves ~2.86M jsonb entries across 75,304 rows.
- Surviving payload keys: 13 (sparse tax-detail + Ghi chú + STT).

**Field semantics post-mig 039**:

| Field | Domain | Source | Example (USD deal) |
|---|---|---|---|
| `currency_nt` | FX (transaction currency) | "Đơn vị tiền tệ" | `USD` |
| `total_value_nt` | FX (foreign currency total) | "Trị giá NT" | `2114.10` |
| `unit_price_nt` | FX per-piece | "Đơn giá" | `352.35` |
| `total_value` | VND (taxable, customs filing) | "Tổng trị giá" | `57,456,231.43` |
| `unit_price` | VND per-piece | "Đơn giá tính thuế" | `9,576,038.57` |
| `exchange_rate` | rate (VND per FX unit) | "Tỷ giá thanh toán" | `26,137` |
| `total_tax` | VND (tax due) | "Tổng tiền thuế" | varies |

For VND-only deals: `currency_nt='VND'`, `total_value_nt = total_value`
(or NULL if source has only one column).

**Consumer migration (CO + BCQT)**:

Old `currency` field → `currency_nt`. SQL refs need swap:
```sql
-- Before:
select customs_code, currency, total_value from hub.bcct_rows ...
-- After:
select customs_code, currency_nt, total_value_nt, total_value from hub.bcct_rows ...
```

For invoice-matches use case (CO origin cert): use FX-domain
(`total_value_nt`, `unit_price_nt`, `currency_nt`) to match
buyer's invoice in their currency.

For settlement use case (BCQT): use VND-domain (`total_value`,
`unit_price`) for tax aggregation.

Payload jsonb access for promoted keys also breaks:
```sql
-- Before:
select payload->>'Tên doanh nghiệp' as exporter ...
-- After: typed column directly
select exporter_name as exporter ...
```

The 38 promoted keys are listed in mig 041's SQL preamble. Surviving
payload keys (13) are unchanged.

### Final schema state

`hub.bcct_rows` now has **40 typed columns** (was 32):
- Identifiers: client_id, transaction_key, line_no, declaration_no,
  declaration_type, direction, registration_date.
- Material: customs_code, goods_name, hs_code.
- Quantity: quantity, unit, quantity_2, unit_2.
- Value/price (split FX vs VND): unit_price, unit_price_nt,
  total_value, total_value_nt, currency_nt, total_tax,
  exchange_rate.
- Misc: origin, invoice_ref, unloading_location.
- 12 CO-essential (mig 010): exporter_name, exporter_tax_code,
  consignee_name, incoterms, weight, weight_unit, package_count,
  package_unit, invoice_date, departure_date, destination_code,
  destination_name, transport_mode.
- Tier 2 (mig 040): contract_no, contract_date, internal_mgmt_no,
  package_marks.
- Bookkeeping: artifact_id, upload_id, payload, indexed_at, year.

## Bonus: configurable parser rules per client

`hub.client_parser_rules` is now the only place agency-specific regex
lives. Staff (dev role only) edit via:

- UI: `/clients/<client_id>/parser-rules` (Data Hub web UI)
- JSON CRUD: `/v1/hub/clients/<client_id>/parser-rules` (GET/POST/PATCH/DELETE/test)

Rule shape per client per `output_field` (`internal_code`,
`material_identity_candidates`, future fields):

```
priority         — int, ascending
pattern          — regex string (re2-compatible, ReDoS-safe)
source_field     — 'goods_name', 'customs_code', etc.
match_action     — 'capture' | 'reject'
no_match_action  — 'next_rule' | 'return_null'
match_group      — int, default 1
notes            — staff-authored; exposed via evidence.match_rule
```

You don't need to do anything with this — it's internal Data Hub
config. Just FYI in case staff change rules and your downstream
output shifts: re-run your provider tests and check
`evidence.parser_version` for cache busting (still `"v1"` until rule
schema changes).

## Questions / coordination

If your CO consumer PR has merge conflicts with these changes, ping
`dennis.anh@gmail.com` — happy to walk through the row-normalizer
diff together.
