-- Operator-confirmed ĐVT conversion factors, per client.
--
-- CO allocates a BOM demand (in the BOM's đơn vị tính) against customs lots counted
-- in whatever unit the declaration states. Same-unit spellings (EA/PIECES/CÁI) and
-- same-family scales (KG→G) are resolved in code (app/uom_conversion.py). A pair that
-- crosses quantities (EA ↔ SETS, KG ↔ PIECES) is a fact about the material and must be
-- confirmed by a person, on the row, with who and when recorded — a filed bảng kê has
-- to be able to answer why 4 SETS became 20 PIECES.
--
-- material_code = '' applies client-wide. A row naming a material wins over it.
--
-- See app/uom_factor_store.py.

create table if not exists co_uom_factor (
  client_id     text not null,
  bom_uom       text not null,
  lot_uom       text not null,
  material_code text not null default '',
  factor        numeric(20,9) not null,
  confirmed_by  text not null default '',
  confirmed_at  timestamptz not null default now(),
  note          text not null default '',
  primary key (client_id, bom_uom, lot_uom, material_code),
  constraint chk_co_uom_factor_positive check (factor > 0)
);
