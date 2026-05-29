# Feature: Service-account admin UI

Discovery + build 2026-05-29. Web UI for minting/listing/revoking
service-account tokens, replacing the CLI-only path
(`scripts/mint_service_token.py`) for interactive use. Precursor to the
C.1/C.2 cutover (see `.ai/features/2026-05-29-api-auth-strict-cutover/brief.md`)
— minting via the prod web UI naturally binds the token to the prod
issuer + signing key, avoiding the "minted on localhost" footgun.

## Scope

**In:**
- `GET /admin/service-accounts` — list accounts (name, scopes, clients,
  created_by, created_at, last_used, **token expiry**) + create form.
- **Expiry selection + display** (mig 073, added 2026-05-29): pick an expiry
  date at mint (`<input type=date>`, blank = default 30d from
  `service_token_ttl_seconds`); chosen date → ttl passed to
  `make_service_token` so the JWT `exp` and the stored `token_expires_at`
  agree. List shows the expiry (UTC, normalized from the DB session tz) with
  "đã hết hạn" / "sắp hết (<7d)" badges. Past/invalid dates rejected.
- **Auto-renew / sliding expiry** (mig 074, added 2026-05-29): opt-in checkbox.
  When on, the JWT is minted with a long hard-ceiling `exp` (chosen date, else
  365d) and the registry `token_expires_at` is the **live gate** (idle window =
  `service_token_ttl_seconds`, 30d). `_validate_service_token` enforces the
  registry expiry and, on each use within the window, pushes `token_expires_at`
  forward (capped at the ceiling) via `extend_token_expiry`. The token **string
  never changes** → sister apps never rotate their `.env`. It dies only on idle
  (unused for the window) or at the hard ceiling. Off (default) = unchanged
  behaviour (`token_expires_at == JWT exp`, no sliding). Revocation (delete /
  revoke-jti) still kills it instantly. List shows a "↻ auto" badge.

  **Reverses** the 2026-05-02 sister-app note ("no refresh flow") — chosen by
  user 2026-05-29 because Data Hub cannot push a new token to CO's `.env`, so a
  sliding never-rotating token is the only fully hands-off option. Additive, not
  breaking: a sliding token behaves to CO like a long-lived one. Sister-app note
  + DECISIONS entry to follow.
- `POST /admin/service-accounts/new` — create row + mint token; render the
  list page with a **one-time token reveal** box (status 200, no redirect —
  the token is never persisted, so it cannot survive a redirect).
- `POST /admin/service-accounts/{name}/delete` — soft revoke (delete row →
  all its tokens reject).
- `POST /admin/service-accounts/{name}/revoke-jti` — blacklist a specific
  leaked jti (CLI parity; the jti is shown in the reveal box at mint time).
- Dev-only gating (`user.role != "dev"` → 403), matching
  `/admin/settings/technical`. Service tokens grant cross-client reads —
  same sensitivity as LLM/embedding settings.

**Explicitly OUT:**
- No auto-delivery of the token to CO/BCQT — the operator still pastes it
  into the sister app's `.env`. UI helps minting, not distribution.
- No edit-in-place of scopes/clients (the registry row is the authz source;
  editing it is a CLI/SQL op for now — rare). Delete + re-create instead.
- CLI (`mint_service_token.py`) stays — needed for headless/cron/scripted
  re-mint. UI complements, doesn't replace.

## Decisions

- **One-time reveal, no persistence.** Token shown once inline in the POST
  response, never stored, never logged, never put in a redirect/flash. Mirrors
  the CLI's stdout-once behaviour. DB keeps only the account row (authz);
  the JWT is authn and is the caller's to safeguard.
- **Reuse `sa_store` + `jwt_issuer.make_service_token` verbatim** — the UI is a
  thin wrapper over the exact functions the CLI calls. Same create-row-then-mint
  order.
- **Scopes as fixed checkboxes** (`hub:read`, `bom:propose`) — the only scopes
  the API enforces today. Clients as a multiselect from `hub.clients`; empty
  selection = `null` = all clients.
- **Hardcoded Vietnamese copy, neutral/passive** (matches recent admin
  templates e.g. `declaration_types.html`; no `t()` keys, no pronouns per
  `feedback_no_pronouns_in_ui`).

## Risks

- **Token on the wire.** Reveal travels over the response body. Over
  `https://ttdatahub.tinsu.ai` (prod) it's TLS-protected; over plain
  `http://100.84.189.87:8754` (demo) it's plaintext on a private Tailscale
  net — acceptable, noted.
- **No CSRF on the POSTs** — consistent with every other admin POST in this
  repo (pre-existing gap, BACKLOG E.4). Not introduced here.
- **Accidental disclosure via browser history/back button** — the reveal page
  is a POST response, so back/refresh re-POSTs (browser warns) rather than
  re-showing. Acceptable; the box warns "lưu ngay, không hiển thị lại".

## Done criteria

- pytest green (new `tests/test_admin_service_accounts.py`: list renders,
  dev-gate 403 for non-dev/anon, create mints + shows token + writes row,
  bad-name/duplicate/no-scope rejected, delete removes row, revoke-jti
  blacklists).
- Committed screenshots: list (empty + populated), create form, one-time
  reveal.
- `/rev` clean (bundle minors).
