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
```

Forward-only (no `down.sql`). Pre-prod = OK.

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
