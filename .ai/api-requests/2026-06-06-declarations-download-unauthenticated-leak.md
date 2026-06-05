# Data Hub Defect (CRITICAL / SECURITY): declarations download endpoints serve customs files with NO authentication

**Type:** Security defect against shipped contracts
(`2026-05-28-bcct-declarations-download-bearer.md`,
`2026-06-05-declarations-merged-pdf.md`).
**Severity:** Critical — unauthenticated, enumerable access to third-party
customs declaration documents (TKX/TKN) on the public surface.
**Endpoints:**
- `GET /v1/hub/clients/{client_id}/declarations/download.pdf`
- `GET /v1/hub/clients/{client_id}/declarations/download.zip`
**Date:** 2026-06-06
**Reported by:** CO (barry-CO), during prod verification of the merged-PDF feature.

## Symptom
On the **public** Data Hub surface `https://ttdatahub.tinsu.ai`, both
declaration download endpoints return the actual customs files to an
anonymous caller — **no `Authorization` header, no cookie, no token**.

Both contracts require `401 bearer token required` when auth is missing
(`hub:read` scope). Prod returns `200` with the real documents instead.

## Evidence (prod, anonymous curl — no credentials of any kind)
```
GET https://ttdatahub.tinsu.ai/v1/hub/clients/johnson-vn/declarations/download.pdf?direction=import&declaration_nos=107271918940
→ 200  application/pdf  238186 bytes   (real merged tờ khai PDF)

GET https://ttdatahub.tinsu.ai/v1/hub/clients/johnson-vn/declarations/download.zip?direction=import&declaration_nos=107271918940
→ 200  application/zip  325359 bytes   (real .xls customs file embedded)
```
The local/dev Data Hub correctly returns `401` for the same no-auth request —
so the auth check exists in code but is **not enforced on the prod
deployment** for these two routes.

## Impact
- Customs declarations expose sensitive commercial data: exporter/importer
  legal names, tax codes (MST), trade values, HS codes, quantities, addresses.
- `client_id` is a public slug (e.g. `johnson-vn`, `growatt-vn`) and
  `declaration_nos` are sequential customs numbers → **enumerable**. An
  anonymous actor can harvest other clients' declarations by guessing IDs.
- Cross-tenant: the per-client scoping check (`token can view client_id`) is
  bypassed entirely because there is no token.

## Expected
- No/invalid bearer → `401`.
- Valid bearer not authorized for `client_id` → `403`.
- Only a bearer with `hub:read` scope AND authorization for `client_id` gets
  `200` + files.
- Same for BOTH `download.pdf` and `download.zip`, and confirm the metadata
  `GET …/declarations` route is also auth-gated.

## Likely root cause (confirm in code/deploy)
The auth dependency that guards the rest of `/v1/hub/*` is missing on these two
download routes in the prod build (or a router-level dependency was added
locally but not deployed, or a reverse-proxy/auth-middleware exclusion lets
`download.*` through). The 401-vs-200 split between dev and prod points to a
deployment/config gap, not missing code.

## Required Data Hub tests (must run against the prod config path)
- No-auth `download.pdf` / `download.zip` → `401` (regression test for this leak).
- Wrong-client bearer → `403`.
- Authorized `hub:read` bearer → `200` + files.
- Same matrix for the metadata `declarations` route.
- A deploy/integration check that the auth dependency is actually active on the
  public surface, not only in unit tests.

## CO side
No CO change required or possible — this is entirely a Data Hub enforcement
defect. CO continues to consume the endpoint through `app/data_hub_client.py`.
CO will re-probe the public surface after the fix to confirm `401` for no-auth.

**Action: fix before the merged-PDF / dossier feature is announced to the
customer — the same endpoints are currently leaking.**
