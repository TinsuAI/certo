# DH-side fix prompt — CRITICAL: declarations download endpoints serve customs files with no auth

Hand this prompt to the Data Hub AI agent. It is self-contained. This is a
critical, exploitable security defect in production — prioritize it.

---

```
You are working in the Data Hub codebase. Fix a CRITICAL authentication-bypass defect in production, reported by the CO (certificate-of-origin) service.

## Defect
On the PUBLIC Data Hub surface (https://ttdatahub.tinsu.ai), these two endpoints return the actual customs declaration files to an ANONYMOUS caller — no Authorization header, no cookie, no token:
  GET /v1/hub/clients/{client_id}/declarations/download.pdf
  GET /v1/hub/clients/{client_id}/declarations/download.zip

Both are supposed to require a Bearer token with scope hub:read and authorization for client_id (401 if missing, 403 if the token can't view the client). In prod they return 200 with the real documents.

## Evidence (anonymous curl, NO credentials)
  GET https://ttdatahub.tinsu.ai/v1/hub/clients/johnson-vn/declarations/download.pdf?direction=import&declaration_nos=107271918940
    -> 200 application/pdf 238186 bytes  (real merged tờ khai PDF)
  GET https://ttdatahub.tinsu.ai/v1/hub/clients/johnson-vn/declarations/download.zip?direction=import&declaration_nos=107271918940
    -> 200 application/zip 325359 bytes  (real .xls embedded)

The dev/local Data Hub returns 401 for the same no-auth request, so the auth check exists in code but is NOT enforced on the prod deployment for these routes.

## Impact
Customs declarations leak exporter/importer legal names, tax codes, trade values, HS codes, quantities, addresses. client_id is a public slug and declaration_nos are sequential customs numbers -> an anonymous actor can ENUMERATE and harvest any client's declarations. The per-client scoping check is bypassed because there is no token at all.

## Expected after fix
- No/invalid bearer -> 401.
- Valid bearer without authorization for client_id -> 403.
- Bearer with hub:read + authorized for client_id -> 200 + files.
- Identical for download.pdf AND download.zip. Also confirm GET .../declarations (metadata) is auth-gated on prod.

## Investigate (the 401-dev / 200-prod split = deploy/config gap, not missing code)
- Is the auth dependency that guards the rest of /v1/hub/* attached to these two download routes? (Maybe added locally but the prod image predates it, or the route declares the dependency but a router include drops it.)
- Is there a reverse-proxy / gateway / middleware rule that excludes paths matching `download.*` or `*.pdf`/`*.zip` from auth? Check the prod ingress/proxy config.
- Confirm the deployed prod build == the code that returns 401 in dev.

## Acceptance
- Anonymous GET to download.pdf and download.zip on https://ttdatahub.tinsu.ai -> 401 (not 200).
- Authorized hub:read bearer for the client -> 200 + files (unchanged happy path).
- Wrong-client bearer -> 403.

## Provider/integration tests (add; must exercise the prod auth path)
- No-auth download.pdf -> 401. No-auth download.zip -> 401. (Regression tests for this exact leak.)
- Wrong-client bearer -> 403 for both.
- Authorized bearer -> 200 + files for both.
- Metadata declarations route: no-auth -> 401.
- A deploy/smoke check asserting the auth dependency is active on the public surface, not only in unit tests.

## CO side
None. CO consumes these endpoints with a valid operator/service token via its adapter; it is unaffected by adding enforcement. After you deploy the fix, CO will re-run an anonymous probe against the public surface to confirm 401.

Report back: root cause (code vs proxy/deploy), the fix, and the test results.
```
