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
  date at mint (`<input type=date>`, blank = default from
  `service_token_ttl_seconds`, now **1 year** — mig 074); chosen date → ttl
  passed to `make_service_token` so the JWT `exp` and the stored
  `token_expires_at` agree. List shows the expiry (UTC, normalized from the DB
  session tz) with "đã hết hạn" / "sắp hết (<7d)" badges. Past/invalid dates
  rejected.
- **1-year static keys** (mig 074, 2026-05-29): default token lifetime bumped
  30d → 1 year. Service accounts are long-lived static M2M keys, rotated yearly
  by re-mint, not auto-renewed.

  *Design note:* a sliding "auto-renew" mechanism was prototyped (registry-
  enforced expiry + extend-on-use) then **dropped** in favour of plain 1-year
  static keys — the more conventional M2M pattern (cf. GitHub PAT / Stripe key:
  long-lived bearer + revocation list). Sliding expiry on M2M API tokens is
  non-standard; the "proper" zero-touch alternative is OAuth2 client-credentials
  (durable secret ↔ ephemeral token), which needs CO-side work and is overkill
  at this scale. Static-key + revocation registry (delete / revoke-jti) + a
  yearly rotation reminder is the pragmatic norm here. mig 074 also drops the
  abandoned `auto_renew` column.
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
