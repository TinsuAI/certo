-- SSO refresh tokens — silent access-token renewal for sister apps (CO).
--
-- The access token stays short-lived (`sso_token_ttl_seconds`, 600s) and
-- JWKS-verifiable. This table holds the long-lived secret that lets a
-- consumer mint a fresh one without bouncing the operator through
-- interactive /v1/auth/authorize.
--
-- Only sha256(token) is stored — a dump of this table yields no usable
-- credential. The plaintext exists solely in the response that mints it.
--
-- Two independent deadlines:
--   expires_at           sliding idle deadline, pushed forward on rotation
--   absolute_expires_at  hard ceiling fixed at family birth, never extended
--
-- `session_id` binds the token to the DH SSO session that authorized it.
-- Logout deletes that row, and the cascade below revokes every refresh
-- token minted from it.
--
-- `granted_role` / `granted_client_ids` freeze the scope the operator
-- consented to at login. A refresh returns the live ACL intersected with
-- this grant, never the union: per RFC 6749 §6 a refresh token must not
-- yield an access token broader than the one originally issued. Widening
-- requires a fresh trip through /authorize. NULL granted_client_ids means
-- the grant was unrestricted (dev/admin).

create table if not exists hub.sso_refresh_tokens (
  token_hash          text primary key,
  family_id           text not null,
  user_id             text not null references hub.users(user_id) on delete cascade,
  session_id          text not null references hub.sessions(session_id) on delete cascade,
  granted_role        text not null,
  granted_client_ids  text[],
  redirect_origin     text,
  issued_at           timestamptz not null default now(),
  expires_at          timestamptz not null,
  absolute_expires_at timestamptz not null,
  used_at             timestamptz,
  replaced_by         text,
  revoked_at          timestamptz,
  revoked_reason      text
);

create index if not exists idx_sso_refresh_family on hub.sso_refresh_tokens(family_id);
create index if not exists idx_sso_refresh_user on hub.sso_refresh_tokens(user_id);
create index if not exists idx_sso_refresh_session on hub.sso_refresh_tokens(session_id);
create index if not exists idx_sso_refresh_absolute_expires on hub.sso_refresh_tokens(absolute_expires_at);
