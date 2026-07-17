-- 095_growatt_double_dot_placeholder.sql
-- Growatt writes '..' as well as '.' in the BCCT customs_code field to mean
-- "no HQ code on this line" (#52). One row carries it: declaration
-- 105187485911 line 34, 2022-12-26, a solder-sucker gun bought as a tool —
-- the same fixed-asset/tool case '.' already marks. Without this, '..' is
-- treated as a declared code: derive_from_bcct turns it into an 'nvl'
-- material and the discovery queue lists it as a code awaiting approval.
--
-- Extends mig 090's seed rather than replacing it. Idempotent, and a no-op
-- on a fresh DB where growatt-vn does not exist yet (CI) — app/seed.py
-- mirrors it for that case, same pattern mig 090 established.

update hub.clients
   set customs_code_placeholders = customs_code_placeholders || '{".."}'
 where client_id = 'growatt-vn'
   and not ('..' = any(customs_code_placeholders));
