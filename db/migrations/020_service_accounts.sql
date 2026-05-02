-- 020_service_accounts.sql
-- Service-account JWTs — non-human identities for sister-app integration
-- (CO write-back, BCQT consumer reads, future cron jobs).
-- See .ai/features/2026-05-02-service-account-jwts.md
--
-- Two tables:
-- 1. hub.service_accounts — registry of named service identities. Token
--    sub becomes 'svc:<name>'. scopes[] enforced per endpoint;
--    client_ids[] is an optional whitelist (null = all clients).
--    Revoke = delete row; the verifier looks up by name on every call.
-- 2. hub.revoked_service_tokens — jti blacklist for emergency revocation
--    of a specific token before its 30d natural expiry.

create table if not exists hub.service_accounts (
  name          text primary key,
  description   text not null default '',
  scopes        text[] not null default '{}',
  client_ids    text[],
  created_at    timestamptz not null default now(),
  created_by    text not null,
  last_used_at  timestamptz
);

create table if not exists hub.revoked_service_tokens (
  jti          text primary key,
  revoked_at   timestamptz not null default now(),
  revoked_by   text not null,
  reason       text not null default ''
);

insert into hub.app_settings (key, value) values
  ('service_token_ttl_seconds', '2592000')   -- 30 days
on conflict (key) do nothing;
