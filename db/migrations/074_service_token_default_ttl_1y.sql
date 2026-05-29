-- 074_service_token_default_ttl_1y.sql
-- Default service-token lifetime: 30 days → 1 year. Service accounts are
-- long-lived static keys (machine-to-machine), rotated on a yearly cadence
-- rather than monthly. The admin UI / CLI still allow a custom expiry per
-- mint; this only changes the blank-default. Bumps the existing value only
-- if still at the original 30d default (won't clobber a custom setting).
update hub.app_settings set value = '31536000'
  where key = 'service_token_ttl_seconds' and value = '2592000';

-- Drop the abandoned sliding-expiry column (auto-renew was prototyped then
-- dropped in favour of plain 1-year static keys). No-op on fresh installs.
alter table hub.service_accounts drop column if exists auto_renew;
