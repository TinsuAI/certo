# Project Status

## Current State
- Active branch: `sprint/postgres-source-indexes-20260430`.
- Worktree was clean after the latest commit; handoff artifacts are being updated at session end.
- CO has Data Hub consumer mode plus a standard CO-side User UI:
  - Top-right user dropdown shows Data Hub user name, role, Settings, Technical Settings for dev users, and Logout.
  - `/user` shows current Data Hub session and client access context.
  - `/settings` links User Account and Technical Settings.
  - `/settings/technical` configures CO <-> Data Hub runtime link settings and is dev-only when `CO_AUTH_REQUIRED=1`.
- Local runtime config currently has `CO_AUTH_REQUIRED=1` and `DATA_HUB_ENABLED=0` in `data/local/runtime/data-hub-link.json`. SSO is active; Data Hub-backed source/master data mode is off.
- CO accepts local loopback JWT issuer aliases (`localhost` and `127.0.0.1`) for local Data Hub SSO, and caches JWKS in memory so an already authenticated session can continue if Data Hub is temporarily offline until the JWT expires.
- Shared source/master data remains Data Hub-owned in Data Hub mode. Raw `/v1/hub/*` endpoint literals are still guarded by `tests/test_data_hub_policy.py` and should stay inside `app/data_hub_client.py`.
- Dev server `npm run co:serve` was stopped during handoff.

## Recent Changes
- Added CO User/Auth UI and Data Hub technical settings:
  - `app/templates/base.html` now has the top-right user dropdown.
  - New templates: `user.html`, `settings.html`, `data_hub_settings.html`, `sso_logout.html`.
  - `app/main.py` adds `/user`, `/settings`, `/settings/technical`, Technical Settings save/test routes, SSO callback failure handling, and SSO logout bridge.
  - `app/data_hub_settings.py` centralizes env + local override configuration.
  - `app/data_hub_client.py` and `app/portfolio.py` use centralized runtime settings and dynamic portfolio service selection.
- Fixed Data Hub SSO redirect loop:
  - Root cause was local issuer mismatch: CO expected `http://127.0.0.1:8754`, Data Hub issued `iss=http://localhost:8754`.
  - CO now accepts the local loopback alias pair and callback failures return `401` instead of redirecting back into login.
- Fixed logout behavior:
  - CO clears `co_data_hub_session` and serves a small intermediate page that POSTs to Data Hub `/logout`.
  - This avoids immediately re-authenticating via an existing Data Hub session.
- Added review fixes:
  - Technical Settings token source now respects env precedence over local override.
  - Settings save validates both the local payload and effective env-precedence configuration.
  - JWKS fetch rejects non-object JSON responses.
  - User dropdown uses an opaque menu surface after screenshot review found text bleeding through on mobile.
- Added documentation and artifacts:
  - `docs/co-data-hub-link.md`
  - `config/co-data-hub.env.example`
  - `.ai/features/2026-05-02-data-hub-link-settings-ui.md`
  - UI screenshots under `.ai/screenshots/co-user-sso-settings/`
  - `AGENTS.md` now requires UI/browser screenshots to be saved under `.ai/screenshots/<feature-slug>/`.
- Commits created:
  - `12123d5 Add CO user SSO settings UI`
  - `7880aae Cache Data Hub JWKS for offline auth`
  - `d4dc2e0 Fix CO settings review issues`
  - `0eccea2 Document UI screenshot artifacts`

## Verification
- `uv run pytest -q` -> `130 passed`.
- Playwright UI smoke passed against local CO + local Data Hub:
  - SSO login to `/user`
  - top-right user dropdown on desktop and mobile
  - `/settings`
  - `/settings/technical`
  - Technical Settings `Test connection`
  - logout ending at Data Hub login
- Technical Settings connection check with current runtime config:
  - JWKS success with `1 signing keys`
  - Source API warning because `DATA_HUB_ENABLED=0`
- Data Hub source adapter smoke with a temporary Data Hub user token:
  - `data_hub_client_from_env().list_clients()` returned `4` clients.
- `npm test` still fails 3 unrelated legal lookup tests expecting `raw-binary` source links. No files in the CO User/Auth/Data Hub settings changes touch the legal lookup server/tests.

## Next Steps
1. Fix or triage the existing legal lookup `raw-binary` test failures if a fully green `npm test` is required.
2. Decide production stance for browser-editable `DATA_HUB_API_TOKEN`; current docs frame it as local/demo only.
3. For any new Data Hub data need, create a `.ai/api-requests/YYYY-MM-DD-<slug>.md` artifact first and do not add raw Data Hub calls outside `app/data_hub_client.py`.
4. If `DATA_HUB_ENABLED=1` is turned on in CO, provide a valid Data Hub service token or rely on user JWT context for requests that support it.

## Blockers
- Full JavaScript test suite is not green because of pre-existing legal lookup `raw-binary` expectation failures.

## Notes for Next AI Session
- User prefers Vietnamese replies when writing Vietnamese. Project docs and handoff artifacts should remain English unless client-facing.
- The user explicitly asked that every UI/browser test screenshot go into a feature-specific subdirectory under `.ai/screenshots/`.
- Current screenshot set for this feature is in `.ai/screenshots/co-user-sso-settings/`.
- Use `/rev` before committing risky/auth/UI work; screenshot-check UI changes with Playwright, including mobile.
- Do not modify the sibling Data Hub repo from CO for provider-side endpoint work. Use API request artifacts when the existing Data Hub contract is insufficient.
