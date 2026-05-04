# Data Hub API Request: customs-exchange-rates

## Use Case
CO needs customs-published exchange rates to normalize foreign-currency customs declaration values by declaration date. The same reference table can be reused by BCCT, invoice valuation, origin calculations, and future apps, so it should be owned by Data Hub instead of CO.

Current temporary CO behavior keeps refreshing and storing this data in the CO app-level cache while Data Hub has no approved exchange-rate contract.

## Existing Endpoint Gap
Checked the current CO Data Hub adapter in `app/data_hub_client.py`. Approved endpoints cover clients, materials, BCCT, code mappings, products, BOM versions/proposals, CO config, source summary, and invoice matches.

No existing Data Hub endpoint provides customs exchange rates, latest applicable rate lookup, refresh metadata, or a refresh trigger. Existing BCCT endpoints may contain declaration values and currencies, but they do not own the customs exchange-rate reference table.

## Proposed Contract
Method and path:

- `GET /v1/hub/customs-exchange-rates`
- `GET /v1/hub/customs-exchange-rates/latest`
- `POST /v1/hub/customs-exchange-rates/refresh`

Query parameters:

- `currency_code`: optional ISO-like currency code, uppercase, for example `USD`, `JPY`.
- `effective_date_from`: optional `YYYY-MM-DD`, inclusive.
- `effective_date_to`: optional `YYYY-MM-DD`, inclusive.
- `declaration_date`: required for `/latest`; `YYYY-MM-DD`; returns the latest rate where `effective_date <= declaration_date`.
- `source`: optional; default `customs.gov.vn`.
- `limit`: optional page size, default `100`, max `1000`.
- `cursor`: optional pagination cursor.

Request body:

- `POST /refresh`: optional JSON object:

```json
{
  "source": "customs.gov.vn",
  "language": "TIENG_VIET"
}
```

Response body:

- `GET /customs-exchange-rates`:

```json
{
  "items": [
    {
      "row_key": "USD-2026-04-27",
      "currency_code": "USD",
      "currency_name": "Do-la My",
      "effective_date": "2026-04-27",
      "rate_vnd_per_unit": "26130",
      "rate_text": "26.130 VND",
      "rate_display": "26.130 VND",
      "source": "customs.gov.vn",
      "source_endpoint": "GetListUSDRate",
      "fetched_at": "2026-05-04T00:00:00Z",
      "version_id": "customs-fx-2026-05-04T000000Z"
    }
  ],
  "next_cursor": "",
  "summary": {
    "row_count": 1,
    "currency_count": 1,
    "latest_effective_date": "2026-04-27",
    "latest_refresh": {
      "created_at": "2026-05-04T00:00:00Z",
      "fetched_row_count": 1,
      "saved_row_count": 1,
      "upserted_row_count": 1
    }
  }
}
```

- `GET /customs-exchange-rates/latest`:

```json
{
  "item": {
    "currency_code": "USD",
    "effective_date": "2026-04-27",
    "rate_vnd_per_unit": "26130",
    "rate_display": "26.130 VND",
    "source": "customs.gov.vn",
    "version_id": "customs-fx-2026-05-04T000000Z"
  }
}
```

- `POST /customs-exchange-rates/refresh`:

```json
{
  "status": "ok",
  "source": "customs.gov.vn",
  "version_id": "customs-fx-2026-05-04T000000Z",
  "fetched_row_count": 28,
  "saved_row_count": 28,
  "upserted_row_count": 0,
  "currency_count": 28,
  "latest_effective_date": "2026-04-27"
}
```

Error cases:

- `400 invalid_currency_code`: invalid currency code.
- `400 invalid_date`: invalid date format or `effective_date_from > effective_date_to`.
- `404 rate_not_found`: no applicable rate for `/latest`.
- `409 refresh_in_progress`: another refresh job is already running.
- `422 unsupported_source`: requested source is not supported.
- `502 source_unavailable`: upstream customs source failed or returned invalid payload.
- `503 refresh_temporarily_disabled`: Data Hub operator disabled live refresh.

## Auth
Required scope:

- Read/list/latest: `hub:read:customs_fx`.
- Refresh: `hub:refresh:customs_fx`.

Client scoping rule:

- Global Data Hub reference data, not scoped to `client_id` or `dncx_id`.
- Any CO user allowed to prepare C/O may read rates.
- Refresh requires Data Hub admin/service permission because it changes shared reference data.

Token type:

- Read: user bearer token or service token accepted by Data Hub.
- Refresh: service token or Data Hub admin user token with explicit refresh scope.

## Data Semantics
Source of truth:

- Data Hub owns the normalized customs exchange-rate table after this contract is approved.
- Upstream source is the public customs.gov.vn exchange-rate lookup API used by `https://www.customs.gov.vn/index.jsp?pageId=18&cid=116`.
- Use `POST /customs/api/GetListRateByNameOrDate` through the customs bridge for historical rows by currency/date range; the current-list endpoints do not return full history for non-USD currencies.
- CO keeps only temporary local cache behavior until migration.

Precision requirements:

- `rate_vnd_per_unit` must be a decimal string, never a float.
- Preserve `rate_text` and `rate_display` for Vietnamese customs-form parity.
- Effective dates are calendar dates in `YYYY-MM-DD`.

Pagination:

- Cursor-based pagination for list endpoint.
- Stable ordering defaults to `effective_date desc, currency_code asc`.

Idempotency:

- Refresh upserts by `(source, currency_code, effective_date)`.
- Re-running refresh with unchanged upstream data must return `upserted_row_count: 0`.

Versioning or pinning:

- Every refresh creates or reuses a `version_id`.
- CO origin snapshots and workbook exports should persist `currency_code`, `effective_date`, `rate_vnd_per_unit`, `source`, and `version_id` when a declaration value is converted.

## Tests Required In Data Hub
Provider tests:

- List rates with pagination and filters.
- Latest applicable lookup returns the newest row whose `effective_date <= declaration_date`.
- Refresh parses USD and other-currency customs payloads.
- Refresh upserts idempotently and records refresh metadata.
- Response preserves decimal strings and display text.

Negative tests:

- Invalid currency/date filters return 400.
- Latest lookup with no applicable rate returns 404.
- Refresh without `hub:refresh:customs_fx` returns 403.
- Concurrent refresh returns 409 or deduplicates through a lock.
- Upstream invalid/non-object payload returns 502 and does not corrupt existing rows.

Edge cases:

- Currency code present in rate payload but missing from currency-name payload.
- Duplicate rows in upstream payload.
- Thousand separators and Vietnamese `VND`/`VNĐ` text.
- Declaration date before first known effective date.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:

- `list_customs_exchange_rates(**query) -> list[dict]`
- `latest_customs_exchange_rate(currency_code: str, declaration_date: str) -> dict | None`
- Optional after approval: `refresh_customs_exchange_rates(source: str = "customs.gov.vn", language: str = "TIENG_VIET") -> dict`

Call sites that will consume the adapter:

- `/customs-exchange-rates` table view.
- BCCT/customs value normalization helpers.
- C/O origin snapshot and workbook export paths that need declaration-date conversion.

Consumer tests:

- Data Hub mode reads customs FX through the adapter.
- CO no longer writes local customs FX rows when Data Hub customs FX is enabled.
- Raw `/v1/hub/*` literals remain confined to `app/data_hub_client.py`.
- Local cache fallback remains available only when Data Hub source mode is disabled or the new FX contract is explicitly disabled.

## Approval
Data Hub contract owner:

Approval date:

Data Hub commit:
