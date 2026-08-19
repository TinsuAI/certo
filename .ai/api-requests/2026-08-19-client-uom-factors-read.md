# Data Hub API Request: client ĐVT conversion factors (read)

Status: needs-triage — awaiting Data Hub contract approval. CO side is NOT implemented.

## Use Case
A CO bảng kê subtracts a BOM demand from the import lots that fed it. The BOM counts a
material in one đơn vị tính and the tờ khai nhập counts the same material in another
(prod johnson-vn: 226 of 3,816 allocated lines). When the two units are the same
quantity (KG→G) CO derives the factor arithmetically; when they are different
quantities (EA↔CAY, EA↔SETS) the ratio is a fact about the material, so CO blocks Chốt
until a person confirms it on the row and stores it in `co_uom_factor`
(`app/uom_factor_store.py`).

The agency has already entered those facts on the Data Hub side. johnson-vn holds
**516 rows** in `hub.client_uom_overrides` (`/clients/johnson-vn/uom-factors`), including
the `EA → CAY` and `ROLL → PIECES` pairs the operator is being asked to re-enter in CO.
CO cannot see them, so after uploading BOM + BCCT the operator still gets "Cần hệ số
EA→CAY" on every affected row and cannot Chốt (client report 2026-08-19, items 1 and 5).

CO should read the client's factors from Data Hub and merge them under its own
operator-confirmed rows, so a factor entered once in Data Hub applies to every dossier.

## Existing Endpoint Gap
Checked in `app/data_hub_client.py` and in the `data-hub` repo:

- `app/data_hub_client.py` — no uom-factor call exists; the only `uom` references are the
  per-row `uom`/`unit` fields carried on catalog and BOM rows (`:1200`, `:1215`).
- `data-hub` `app/routes/client_uom_factors.py` — the factors are exposed ONLY as an
  HTML admin UI mounted at `/clients/{client_id}/uom-factors` (list / new / update /
  delete / CSV import), gated by `can_edit_client_config`. There is no `/v1/hub/*` route
  over `hub.client_uom_overrides`.
- `hub.materials` and the BOM artifact rows carry a single `uom` per row, not a
  conversion between two units, so no existing payload can be re-read for this.

## Proposed Contract
Method and path:

    GET /v1/hub/clients/{client_id}/uom-factors

Query parameters:

| name | type | default | meaning |
| --- | --- | --- | --- |
| `material_code` | string | — | optional exact filter; omit for the whole client |
| `cross_family_only` | bool | `false` | return only `is_cross_family` rows (the ones CO blocks on) |
| `updated_since` | ISO-8601 | — | incremental refresh |
| `limit` | int | `500` | page size, max 2000 |
| `cursor` | string | — | opaque page cursor |

Request body: none.

Response body:

```json
{
  "client_id": "johnson-vn",
  "rows": [
    {
      "material_code": "007173-00",
      "from_uom": "EA",
      "to_uom": "CAY",
      "factor": "1",
      "source": "staff_form",
      "is_cross_family": true,
      "notes": "Client confirmed 2026-05-21: 1 EA = 1 CAY (synonym in Johnson context).",
      "created_at": "2026-05-21T04:11:07Z",
      "updated_at": "2026-05-21T04:11:07Z"
    },
    {
      "material_code": null,
      "from_uom": "ROLL",
      "to_uom": "PIECES",
      "factor": "1",
      "source": "staff_form",
      "is_cross_family": true,
      "notes": "BCCT 2025 + M16/2025 confirm 1:1 — auto-applied 2026-05-14",
      "created_at": "2026-05-14T00:00:00Z",
      "updated_at": "2026-05-14T00:00:00Z"
    }
  ],
  "next_cursor": null,
  "total": 516
}
```

`material_code: null` (or `""`) is the client-wide row; a row naming a material wins over
it. This is the same precedence `app/uom_factor_store.py` already implements.

Error cases:

| status | when |
| --- | --- |
| 400 | `limit` out of range, malformed `updated_since`, unknown `cursor` |
| 401 | missing/expired token |
| 403 | token has no `hub:read` scope, or is scoped to another client |
| 404 | unknown `client_id` |

## Auth
Required scope: `hub:read` (read-only; CO never writes this table — a CO-side
confirmation stays in `co_uom_factor` unless a separate `hub:propose:uom` request is
approved later).

Client scoping rule: the token's client claim must match `{client_id}`, same rule the
existing `/v1/hub` catalog and BCCT reads use.

Token type: the CO service token (`current_data_hub_token`), same as every other
`data_hub_client` read.

## Data Semantics
Source of truth: Data Hub `hub.client_uom_overrides` (migration 055). Data Hub owns the
agency's confirmed factors; CO's `co_uom_factor` stays as the row-level fallback for a
pair Data Hub has not recorded yet.

Direction convention (must be stated in the contract, it is the one thing that silently
inverts the arithmetic): `factor` converts a quantity **from** `from_uom` **to** `to_uom` —
`qty(to_uom) = qty(from_uom) × factor`. This is what the Data Hub admin page already
states ("Từ = EA, Sang = KG, hệ số = 0.5 ⇒ 1 EA = 0.5 KG") and it matches
`app/uom_conversion.resolve_uom_factor`, which returns the factor that turns a BOM
quantity into the lot's unit. So CO maps `from_uom → bom_uom`, `to_uom → lot_uom` with no
inversion.

Precision requirements: `factor` as a decimal STRING, full stored precision, never a
float — it multiplies a consumed quantity that lands on a filed bảng kê.

Pagination: cursor-based, `limit` default 500 / max 2000. johnson-vn is 516 rows today,
so one page must be able to hold a whole client.

Idempotency: read-only.

Versioning or pinning: none needed. CO refreshes per Tính (the same point where it reads
`co_uom_factor` today) and caches per request.

Unit spelling: rows are stored as staff typed them (`EA`, `CAY`, `PIECES`). Data Hub
should return them verbatim; CO canonicalises with `app/uom_conversion.canonical_uom`,
which already matches raw and canonical spellings.

## Tests Required In Data Hub
Provider tests:
- returns every row for a client, client-wide (`material_code` null) and per-material;
- `factor` serialised as a string with the stored scale (`0.5`, `1`, `1000`), not a float;
- `material_code` filter returns the per-material row AND the client-wide row for the
  same pair, so the consumer can apply precedence;
- `cross_family_only=true` returns exactly the `is_cross_family` rows;
- `updated_since` returns only rows changed after the timestamp;
- pagination is stable across pages for a 2000-row client.

Negative tests:
- 403 for a token scoped to another client;
- 403 for a token without `hub:read`;
- 404 for an unknown client;
- 400 for `limit=0`, `limit=5000`, malformed `updated_since`.

Edge cases:
- client with zero factor rows returns `{"rows": [], "total": 0}`, not 404;
- both a client-wide and a per-material row exist for the same `(from_uom, to_uom)`;
- duplicate spellings (`EA` vs `ea`) are returned as stored.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:

```python
def list_client_uom_factors(self, client_id: str, *, cross_family_only: bool = False) -> list[dict]
```

Call sites that will consume the adapter:
- `app/routers/co_case.py::_uom_factors` — merge Data Hub rows UNDER the CO-local
  `uom_factor_store.factor_map` (a CO-side confirmation, which is per-case operator
  intent, keeps winning over the client-level Data Hub row);
- no other call site. `resolve_uom_factor` already consumes a `{(bom_uom, lot_uom[, material_code]): Decimal}`
  map, so no engine change is needed.

Consumer tests:
- a Data Hub row makes `uom_unconfirmed` false on a row that has no `co_uom_factor` entry;
- a `co_uom_factor` row wins over a Data Hub row for the same pair;
- a per-material Data Hub row wins over a client-wide Data Hub row;
- Data Hub unreachable/401 falls back to `co_uom_factor` alone and never blanks the map;
- `tests/test_data_hub_policy.py` still passes (call goes through the adapter only).

## Approval
Data Hub contract owner:

Approval date:

Data Hub commit:
