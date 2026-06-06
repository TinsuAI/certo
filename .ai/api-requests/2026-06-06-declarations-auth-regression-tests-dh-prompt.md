# DH-side prompt — regression tests to lock in declarations-download auth

Hand this to the Data Hub AI agent. Self-contained. The leak is already fixed;
this is purely about adding tests so it can never silently regress.

---

```
You are working in the Data Hub codebase. You recently fixed a CRITICAL leak: GET /v1/hub/clients/{client_id}/declarations/download.pdf and download.zip served real customs declaration files to ANONYMOUS callers (no Bearer token) in production, even though the auth check existed in dev. Root cause was a dev-passes / prod-enforces gap (the auth dependency was not active on the deployed/public surface).

Add regression tests so this can never recur. The important lesson: a plain unit test that imports a handler is NOT enough — the bug lived in how the app was assembled/deployed, so tests must exercise the REAL ASGI app with the auth layer active, plus a post-deploy smoke against the public surface.

## Tests to add

1) App-level auth enforcement (run against the real ASGI app, e.g. FastAPI TestClient on the actual app object, not a hand-built router):
   - No Authorization header:
       GET /v1/hub/clients/{cid}/declarations/download.pdf?direction=import&declaration_nos=<known>  -> 401
       GET /v1/hub/clients/{cid}/declarations/download.zip?direction=import&declaration_nos=<known>  -> 401
       GET /v1/hub/clients/{cid}/declarations?direction=import&declaration_nos=<known>               -> 401  (metadata route too)
   - Invalid/garbage Bearer -> 401.
   - Valid Bearer (hub:read) but NOT authorized for {cid} -> 403.
   - Valid Bearer (hub:read) authorized for {cid} -> 200 + files (happy path unchanged).
   Assert the 401 body is the standard {"detail":"bearer token required"} shape.

2) Cross-tenant guard:
   - Bearer authorized only for client A requesting client B's declarations -> 403, and the response body contains NO file bytes.

3) Broad guard against future unauthenticated routes (catch the whole class, not just these two paths):
   - Enumerate the app's routes; assert every /v1/hub/* route has the auth dependency attached (or is on an explicit, reviewed allowlist of intentionally-public paths). This fails if someone adds a new /v1/hub route without auth.

4) Deploy/public smoke (the gap that caused the incident — dev was fine, prod was not):
   - A smoke check that runs against the deployed/public base URL asserting an anonymous GET to download.pdf and download.zip returns 401 (not 200). Wire it into the deploy pipeline so a misconfigured deployment fails fast instead of silently leaking.

## Acceptance
- All four groups pass.
- Test 1 and 3 run in the normal test suite against the real app object.
- Test 4 runs post-deploy against the public surface (https://ttdatahub.tinsu.ai) and is required (not continue-on-error).

## Context (for the regression assertions)
- Prod evidence of the original leak (anonymous curl, no creds):
    GET https://ttdatahub.tinsu.ai/v1/hub/clients/johnson-vn/declarations/download.pdf?direction=import&declaration_nos=107271918940  -> was 200 (238KB PDF), now 401.
- Auth model: Bearer with scope hub:read + authorization for client_id. CO consumes these with an operator JWT; the metadata, download.zip and download.pdf routes must share the same auth dependency.

Report back the test names/locations and confirm the post-deploy public smoke is wired in.
```
