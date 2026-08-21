-- 082_nxt_inventory_tier.sql
-- New shared data tier: NXT (Nhập-Xuất-Tồn period flow) + year-end inventory
-- snapshot (chốt tồn kho). Data Hub owns parse+store+read; BCQT-System consumes.
-- See .ai/features/2026-06-14-nxt-inventory-tier/brief.md.
--
-- Both entity pairs are IMMUTABLE (edit = new artifact; tombstone allowed) per
-- the BOM immutable principle. `superseded_by` chains versions; null = current.
--
-- Classification is NOT duplicated here: the authoritative NVL/TP/BTP class of a
-- code lives in the catalog and resolves at runtime. `reported_role` on nxt_lines
-- is PROVENANCE only ("the role the source declared this line under") — it earns
-- its place because multi-role codes (cải chế) can appear under two roles in one
-- report and the catalog's single category can't disambiguate them.

-- ── NXT movement ────────────────────────────────────────────────────────
create table if not exists hub.nxt_artifacts (
    id            text primary key,
    client_id     text not null references hub.clients(client_id) on delete cascade,
    period_from   date,
    period_to     date,
    source_kind   text not null default 'manual',
    adapter_name  text,
    file_sha256   text,
    file_path     text,
    note          text,
    created_by    text,
    created_at    timestamptz not null default now(),
    superseded_by text references hub.nxt_artifacts(id) on delete set null
);

create index if not exists idx_nxt_artifacts_client_period
    on hub.nxt_artifacts (client_id, period_to)
    where superseded_by is null;

create table if not exists hub.nxt_lines (
    id              bigint generated always as identity primary key,
    artifact_id     text not null references hub.nxt_artifacts(id) on delete cascade,
    line_no         integer not null,
    internal_code   text,
    customs_code    text,
    name            text,
    uom             text,
    reported_role   text,  -- provenance: nvl|tp|btp|null (source sheet/section)
    opening         numeric,
    inbound_total   numeric,
    out_tai_xuat    numeric,  -- tái xuất
    out_chuyen_mdsd numeric,  -- chuyển mục đích sử dụng / tiêu thụ nội địa / tiêu hủy
    out_xuat_sx     numeric,  -- xuất kho để sản xuất
    out_xuat_khac   numeric,  -- xuất kho khác
    closing_reported numeric, -- value as reported; closing_implied derived at runtime
    note            text,
    raw             jsonb     -- unmapped cells, for audit/provenance
);

create index if not exists idx_nxt_lines_artifact
    on hub.nxt_lines (artifact_id);

-- ── Year-end inventory snapshot (chốt tồn) ──────────────────────────────
create table if not exists hub.inventory_snapshots (
    id            text primary key,
    client_id     text not null references hub.clients(client_id) on delete cascade,
    snapshot_date date,
    source_kind   text not null default 'manual',
    adapter_name  text,
    file_sha256   text,
    file_path     text,
    note          text,
    created_by    text,
    created_at    timestamptz not null default now(),
    superseded_by text references hub.inventory_snapshots(id) on delete set null
);

create index if not exists idx_inventory_snapshots_client_date
    on hub.inventory_snapshots (client_id, snapshot_date)
    where superseded_by is null;

create table if not exists hub.inventory_snapshot_lines (
    id            bigint generated always as identity primary key,
    snapshot_id   text not null references hub.inventory_snapshots(id) on delete cascade,
    line_no       integer not null,
    code          text,
    name          text,
    uom           text,
    warehouse     text,
    batch         text,
    qty_book      numeric,  -- số lượng sổ sách
    qty_physical  numeric,  -- số lượng thực đếm; variance = physical - book derived at runtime
    note          text,
    raw           jsonb
);

create index if not exists idx_inventory_snapshot_lines_snapshot
    on hub.inventory_snapshot_lines (snapshot_id);
