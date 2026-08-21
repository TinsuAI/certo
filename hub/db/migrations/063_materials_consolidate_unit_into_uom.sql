-- mig 063: consolidate hub.materials.unit + hub.materials.uom → uom only.
--
-- Why:
--   Two columns existed in parallel (`unit` since mig 002; `uom` added mig
--   047 for Mã chờ duyệt accept flow) with TWO distinct read paths in the
--   engine layer:
--     - `make_catalog_lookup` (app/stores/bom.py) reads `unit` — used by
--       flatten engine via ctx.catalog().
--     - `_convert_rows_to_catalog_uom` (app/stores/bom_staleness.py) reads
--       `uom` — used by refresh + initial materialize via Phase 2.
--   Auto-bootstrap from BCCT writes `unit` only; Mã chờ duyệt writes `uom`
--   only. Same material ends up partially populated, engine sees NULL on
--   one path, drift signals flood, materialize degrades.
--
--   Raw observation tokens are preserved at edge/row level:
--     - `hub.bcct_rows.unit` (raw token from BCCT XLSX)
--     - `hub.bom_edges.uom` (raw token from BOM source row)
--   So `hub.materials.unit` is redundant — catalog only needs ONE canonical
--   column for the engine to consume.
--
-- This migration:
--   1. Backfills `uom` from `unit` where uom IS NULL (one-shot data fix).
--      Normalization (alias resolution) is deferred to subsequent app-layer
--      writes — backfill preserves raw values verbatim so downstream
--      `make_uom_lookup` still applies aliases at read time.
--   2. Drops the legacy `unit` column.
--
-- After this mig:
--   - All write sites must write `uom`. See pipeline fixes in
--     `bootstrap_catalog_from_bcct.py`, `fixup_johnson_btp_sx_after_bom.py`,
--     etc.
--   - API JSON output keeps emitting `unit` AS AN ALIAS of `uom` during the
--     grace window (see `app/routes/api.py` _MATERIALS_SELECT_WITH_ROLES).
--     Sister-app consumers (CO) read `unit` from the JSON; they migrate
--     async during the grace window declared in `docs/API_CONTRACT.md`.

begin;

-- Step 1: backfill `uom` from `unit` where missing. Verbatim copy — alias
-- normalization happens at read time via `hub.uom_aliases` lookup in
-- `app/stores/uom.py::make_uom_lookup`. No silent transformation here.
update hub.materials
   set uom = unit
 where uom is null
   and unit is not null;

-- Step 2: drop the legacy column.
alter table hub.materials drop column unit;

commit;
