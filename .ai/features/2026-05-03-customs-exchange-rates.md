# Feature: Customs Exchange Rates

## Scope
- Add a web-app surface for customs FX rates used by C/O valuation work.
- Reuse the prior `customs.gov.vn` JSON endpoints discovered in the older `barry-CO` repo:
  - `GetListDongTienTyGia`
  - `GetListUSDRate`
  - `GetListOtherRate`
- Store fetched rows in a durable local table when Postgres is configured, with JSON fallback for local/offline mode.
- Show the rate table as an app-level surface while storing the canonical rates under a shared `global` scope.
- Provide a CLI refresh command so the same update can be run manually or from a scheduler.

Out of scope for this pass:
- Do not add or assume a Data Hub API endpoint for customs FX rates.
- Do not wire rate lookup into C/O valuation calculations yet.
- Do not migrate historical generated Growatt artifacts.

## Decisions
- Treat customs FX rates as app-level shared reference data, not company-owned workflow state.
- Upsert by `client_id='global'`, `currency_code`, and `effective_date`.
- Keep old rows if a later customs refresh returns only a recent window.
- Block refresh writes when `DATA_HUB_ENABLED=1`, matching existing shared-source write rules.
- Store machine values in English field names; render Vietnamese labels in UI only.

## Risks
- The customs public JSON endpoints are undocumented and may change field names or availability.
- Rate text uses Vietnamese formatting; parsing must preserve `26.130 VNĐ` as `26130`, not `26.130`.
- The current table is a local CO reference table. If Data Hub later owns this data, CO must consume it through `app/data_hub_client.py` after an approved Data Hub contract.

## Open Questions
- Whether customs FX rates should become Data Hub-owned shared master data.
- Whether C/O valuation should always use the latest table by declaration date, or snapshot the exact FX version into each case.
