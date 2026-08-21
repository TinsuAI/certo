# Notes for BCQT repo (BCQT-System)

**Provider:** Data Hub  ·  **Consumer:** BCQT (settlement)  ·  **Date:** 2026-05-02

Posted from Data Hub side. Add a one-line entry to `BCQT-System/.ai/DECISIONS.md` pointing here.

## What's new for BCQT

Data Hub now exposes a master `client-config` endpoint with fields BCQT cares about:

```text
GET /v1/hub/dncxs/{client_id}/client-config

{
  "preset_key": "dncx" | "sxxk" | "gia_cong" | "manual" | <user-defined>,
  "eligible_import_declaration_types": ["E31", ...],
  "relevant_export_declaration_types": ["E62", ...],
  "fiscal_year_start_month": 1..12,   // for non-calendar fiscal years
  "config_version": int,
  "config_hash": string
}
```

When BCQT does Mẫu 15 / 15a / 16 settlement, use:
- `eligible_import_declaration_types` to filter input BCCT rows.
- `relevant_export_declaration_types` for the export-side aggregation.
- `fiscal_year_start_month` to compute settlement-period boundaries (default 1 if absent or `config_version=0`).

## What stays in BCQT

- Mẫu 15 / 15a column mappings (`app/config/clients/{slug}/settlement.yaml` + `app/config/settlement_defaults.yaml`).
- `path_type` (1 SXXK / 2 DNCX) — derivable from `preset_key` if needed but BCQT can keep this local.
- Anything specific to settlement runtime.

## Read API auth

BCQT will need a JWT token from Data Hub. Two options:
- User JWT via `/v1/auth/token` (works today).
- Service-account JWT — not implemented yet, see Data Hub `BACKLOG.md`.

## Next coordination point

When Data Hub adds `customs_unit_code` or other shared-master fields, watch for new `Breaking:` entries in `docs/API_CHANGELOG.md` of the Data Hub repo. The notification system (kind = `api_contract_changed`) will ping BCQT operator dev/admin accounts when they sign in.

## Action

Add to `BCQT-System/.ai/DECISIONS.md`:

> **2026-05-02 — Data Hub client-config endpoint available.** Use `GET /v1/hub/dncxs/{id}/client-config` for `eligible_import_declaration_types` + `relevant_export_declaration_types` + `fiscal_year_start_month` when implementing the Data-Hub-consumer settlement path. Keep Mẫu 15/15a column mappings in BCQT local YAML. See `<data-hub repo>/docs/API_CONTRACT.md` and `API_CHANGELOG.md`.
