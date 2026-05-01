-- Rename DNCX → Clients (per user terminology preference 2026-05-01).
-- The semantic role is unchanged: the customs-export-processing enterprise
-- whose data the agency manages. "Client" is the user-facing label.

alter table hub.dncxs rename to clients;
alter table hub.clients rename column dncx_id to client_id;

alter table hub.materials rename column dncx_id to client_id;
alter table hub.code_mappings rename column dncx_id to client_id;
alter table hub.code_mapping_resolutions rename column dncx_id to client_id;
alter table hub.bcct_rows rename column dncx_id to client_id;
alter table hub.bom_versions rename column dncx_id to client_id;
alter table hub.bom_change_requests rename column dncx_id to client_id;
alter table hub.bom_audit_events rename column dncx_id to client_id;
alter table hub.material_audit_events rename column dncx_id to client_id;
alter table hub.file_uploads rename column dncx_id to client_id;
