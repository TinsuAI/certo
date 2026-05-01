-- 017_sso.sql
-- SSO settings — issuer URL + active key id (kid). Keys themselves
-- live on disk under keys/ (gitignored, 0400 perms). The kid in
-- app_settings tells the issuer which file to sign with; rotation
-- = generate new file with new kid + flip this setting once consumers
-- have refetched JWKS.

-- SSO settings — issuer URL + active key id (kid). Keys themselves
-- live on disk under keys/ (gitignored, 0400 perms). The kid in
-- app_settings tells the issuer which file to sign with; rotation
-- = generate new file with new kid + flip this setting once consumers
-- have refetched JWKS.

insert into hub.app_settings (key, value) values
  ('sso_issuer_url', 'http://localhost:8754')
on conflict (key) do nothing;

insert into hub.app_settings (key, value) values
  ('sso_active_kid', 'k1')
on conflict (key) do nothing;

insert into hub.app_settings (key, value) values
  ('sso_token_ttl_seconds', '600')
on conflict (key) do nothing;
