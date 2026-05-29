-- 073_service_account_token_expiry.sql
-- Persist the minted token's expiry on the service-account row so the
-- admin UI can show "when does this token expire" + flag expired/near-expiry.
--
-- exp still lives in the JWT (verify_token enforces it). This column is
-- operational metadata for the UI list view, set at mint time. Nullable:
-- legacy rows minted before this migration have no recorded expiry.
alter table hub.service_accounts
  add column if not exists token_expires_at timestamptz;
