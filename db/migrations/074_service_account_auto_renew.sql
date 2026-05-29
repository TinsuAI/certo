-- 074_service_account_auto_renew.sql
-- Sliding-expiry ("auto-renew") for service accounts. When on, the JWT is
-- minted with a long hard-ceiling exp and token_expires_at (mig 073) is the
-- live gate: each use within the idle window pushes it forward, so the token
-- string never changes and consumers never rotate their secret. The token
-- dies only on idle (no use for the window) or at the hard ceiling.
-- Off (default) = current behaviour: token_expires_at == JWT exp, no sliding.
alter table hub.service_accounts
  add column if not exists auto_renew boolean not null default false;
