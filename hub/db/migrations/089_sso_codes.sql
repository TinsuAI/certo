-- One-time browser-SSO codes, moved out of process memory.
--
-- These lived in a per-process dict (`_SSO_CODES` in app/routes/auth_api.py),
-- which meant /v1/auth/authorize could mint a code on one uvicorn worker while
-- the consumer's /v1/auth/exchange POST landed on another and got a spurious
-- `401 invalid or expired code`. Measured at 2 failures in 12 attempts with
-- --workers 4. The Docker image runs --workers 1 so production never saw it,
-- but deploy/systemd/data-hub.service (--workers 2) and local dev (--workers 4)
-- both did.
--
-- Only sha256(code) is stored, matching hub.sso_refresh_tokens: a dump of this
-- table yields nothing exchangeable. The code is single-use — `used_at` is set
-- by an atomic consume, so two concurrent exchanges of the same code resolve to
-- exactly one winner.
--
-- `session_id` is the SSO session that authorized the code; it rides through to
-- /exchange so the minted refresh token can be bound to it. NULL only when no
-- session cookie was present, which /authorize does not allow in practice.
-- Deleting the session (logout) cascades here, which transitively covers user
-- deletion too — hence no FK on user_id, which would otherwise be redundant.

create table if not exists hub.sso_codes (
  code_hash     text primary key,
  user_id       text not null,
  session_id    text references hub.sessions(session_id) on delete cascade,
  email         text not null,
  role          text not null,
  display_name  text not null,
  redirect_uri  text not null,
  issued_at     timestamptz not null default now(),
  expires_at    timestamptz not null,
  used_at       timestamptz
);

create index if not exists idx_sso_codes_expires on hub.sso_codes(expires_at);
create index if not exists idx_sso_codes_session on hub.sso_codes(session_id);
