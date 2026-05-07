# BCCT product identity resolver — shipped

**Date:** 2026-05-07
**For:** CO + BCQT
**Data Hub commits:** TBD (3-commit series — mig 032 + resolver core + endpoint wire-up)

## What shipped

Additive `product_identity` field on:
- `GET /v1/hub/bcct` (default `include_product_identity=false`)
- `GET /v1/hub/bcct/invoice-matches` (default `include_product_identity=true`)

Resolves which Data Hub canonical material/product (any kind: TP, BTP,
NVL, CCDC) a BCCT row refers to — via 5-stage logic:
1. `structured_field` — `customs_code` exists in `hub.materials`
2. `goods_name_embedded_code` — Growatt parses `(PV*.*)` paren codes
3. `reviewed_line_mapping` — operator override (write API not yet shipped)
4. `code_mapping_candidate` — code_mappings produce CANDIDATES ONLY (never auto-resolve)
5. `missing`

## Response shape

```json
{
  "product_identity": {
    "resolution_status": "resolved",        // | "ambiguous" | "missing" | "unverified"
    "resolved_code": "PV01.0117500",        // canonical hub.materials.customs_code (any kind)
    "bom_product_code": "PV01.0117500",     // ALIAS of resolved_code, ONLY set when material has alive BOM
    "product_kind": "tp",                   // tp | btp_sx | btp_nm | nvl | ccdc | unknown
    "selected_candidate_code": "PV01.0117500",
    "display_code": "BIENTAN.17",
    "declared_customs_code": "BIENTAN.17",
    "declared_internal_code": "BIENTAN.17",
    "line_key": {
      "client_id": "growatt-vn",
      "declaration_no": "307591379560",
      "line_no": "3",
      "transaction_key": "307591379560-3"
    },
    "resolution_source": "goods_name_embedded_code",
    "confidence": "high",
    "review_status": "system_resolved",
    "parser_adapter": "growatt_bcct",
    "parser_version": "2026-05-07",
    "evidence": {...},
    "candidates": [
      {
        "product_code": "PV01.0117500",
        "source": "goods_name_embedded_code",
        "confidence": "high",
        "reason": "Parsed from goods_name and matching BOM artifacts exist.",
        "product_kind": "tp",
        "bom_artifact_count": 3,
        "latest_flatten_status": "flattened"
      }
    ]
  }
}
```

## Consumer logic

### CO (origin sheet calculation)

CO already plans to read `bom_product_code` — that field still works
exactly as the original CO API request specified:

```python
if pid["bom_product_code"]:
    bom_artifacts = data_hub.list_bom_artifacts(pid["bom_product_code"])
    # ... origin sheet calc
```

**Important:** `bom_product_code` is now a conditional alias. It's set
only when the resolved material has an alive BOM artifact. If you get
`resolved_code='NVL.PE001'` but `bom_product_code=None`, that's
correct — NVL leaves don't have BOMs. Don't try to load a BOM for them.

For CO export rows you generally want `product_kind == 'tp'`. Filter:

```python
if pid["resolution_status"] == "resolved" and pid["product_kind"] == "tp":
    # safe to fetch BOM via pid["bom_product_code"]
```

### BCQT (settlement quantity allocation)

BCQT consumes `resolved_code` + `product_kind` to bind each BCCT line
to a canonical material:

```python
match pid["product_kind"]:
    case "tp" | "btp_sx" | "btp_nm":
        # finished/semi-finished: use BOM if exists
        ...
    case "nvl":
        # raw material consumption — track quantity for Mẫu 15a
        ...
    case "ccdc":
        # tools — different settlement track
        ...
```

Replace BCQT's homegrown `internal_code` parser with this resolver
output. Removes goods_name regex copies from BCQT codebase.

## Resolution rates on real data

After backfill (live dry-run 2026-05-07):

| Client | Total rows | Resolved | Resolution rate |
|---|---|---|---|
| Growatt | 23,080 | 22,200 | 96% |
| Johnson | 52,224 | 52,172 | 99.9% |

Unresolved buckets (Growatt): 821 missing (BCCT references codes
not in catalog — agency data quality), 57 unverified (parsed paren
codes referencing materials we don't have), 2 ambiguous (multi-paren
edge case).

## Auth

`hub:read` scope. Same auth pattern as other read endpoints —
service token or user JWT.

## Idempotency

Persisted in `hub.bcct_rows.product_identity jsonb`. Read returns the
persisted value verbatim (parser_version preserved). Lazy-fill at
read time covers rows ingested before this feature shipped.

Backfill runner: `uv run python -m scripts.resolve_bcct_product_identity --client-id <id>`.

## Migration steps for sister apps

### CO

1. Update `app/data_hub_client.py` to surface `product_identity` on
   list_bcct() + invoice_matches() normalization.
2. Filter for TPs in origin sheet flow:
   `if pid['product_kind'] == 'tp' and pid['resolution_status'] == 'resolved'`.
3. Remove temporary `code-mappings`-based BOM resolution.
4. Update `co_case.html` to surface `ambiguous` / `missing` /
   `unverified` states for operator action.

### BCQT

1. Add `data_hub_client.py` consumer for `product_identity`.
2. In settlement quantity-allocation pass: index BCCT rows by
   `resolved_code` for both imports (NVL consumption) and exports
   (TP production).
3. Deprecate any `goods_name` parsing in BCQT codebase.
4. Tests: pin BCQT settlement output unchanged after migration
   (parity check vs current homegrown parser).

## Known gaps

- Operator override write API deferred (Q1 in brief). Reviewed mappings
  table exists but no write endpoint yet — when CO/BCQT operators want
  to override resolver output, that's a future PR.
- `latest_row_count` in candidate spec example never populated (Minor).
- Lazy re-validation of persisted `resolved` rows on BOM tombstone
  not implemented (Minor — pre-MVP wipe + ingest fresh covers this).

## Contact

Issues / questions on the contract: file a note back to
`~/workspace/client/data-hub/.ai/sister-app-notes/` with a date-prefixed
filename, or ping in shared Slack.
