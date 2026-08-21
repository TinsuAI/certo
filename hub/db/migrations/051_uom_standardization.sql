-- 051_uom_standardization.sql
--
-- Extends existing hub.uom_canonical + hub.uom_aliases tables (mig 021)
-- with missing canonicals + aliases for real BCCT/BOM data.
--
-- Existing schema (mig 021):
--   uom_canonical (uom_code text PK, family text, base_factor numeric)
--   uom_aliases   (alias_norm text PK, uom_code text → canonical)
--
-- Aliases stored lowercase + ASCII-folded ideally; resolver normalizes
-- input the same way before lookup.
--
-- Real BCCT data (Growatt) has 18 distinct unit values; current alias
-- table covers 2/18. This mig fills the gap so `_uom_drift` warning
-- de-noises (PIECES/SETS/METRES/etc are NOT a drift, just synonyms).

begin;

-- ── Add canonicals not in the existing 16 ────────────────────────────────

insert into hub.uom_canonical (uom_code, family, base_factor) values
  ('roll',   'count_packaging', 1),
  ('pair',   'count_packaging', 1),
  ('box',    'count_packaging', 1),
  ('sheet',  'count_packaging', 1),
  ('bottle', 'count_packaging', 1),
  ('bag',    'count_packaging', 1),
  ('cay',    'count_packaging', 1),  -- cây (rod/bar/stick)
  ('thanh',  'count_packaging', 1),  -- thanh (bar/strip)
  ('vien',   'count_packaging', 1),  -- viên (pellet/granule)
  ('thung',  'count_packaging', 1)   -- thùng (drum/barrel)
on conflict (uom_code) do nothing;

-- ── Add missing aliases ──────────────────────────────────────────────────

insert into hub.uom_aliases (alias_norm, uom_code) values
  -- pcs synonyms found in real BCCT
  ('st',        'pcs'),
  ('unit',      'pcs'),
  ('un',        'pcs'),
  ('ps',        'pcs'),

  -- sets plural
  ('sets',      'set'),

  -- mass synonyms
  ('kilo-grammes', 'kg'),
  ('kilo-gramme',  'kg'),

  -- metres plural
  ('metres',    'm'),

  -- liter plurals
  ('litres',    'l'),

  -- new packaging canonicals
  ('roll',      'roll'),
  ('rolls',     'roll'),
  ('cuon',      'roll'),
  ('cuộn',      'roll'),

  ('pair',      'pair'),
  ('pairs',     'pair'),
  ('doi',       'pair'),
  ('đôi',       'pair'),

  ('box',       'box'),
  ('boxes',     'box'),
  ('hop',       'box'),
  ('hộp',       'box'),
  ('carton',    'box'),
  ('ctn',       'box'),
  ('kiện',      'box'),
  ('kien',      'box'),

  ('sheet',     'sheet'),
  ('sheets',    'sheet'),
  ('tam',       'sheet'),
  ('tấm',       'sheet'),
  ('mieng',     'sheet'),
  ('miếng',     'sheet'),

  ('bottle',    'bottle'),
  ('bottles',   'bottle'),
  ('chai',      'bottle'),
  ('tuýp',      'bottle'),
  ('tuyp',      'bottle'),
  ('lọ',        'bottle'),
  ('lo',        'bottle'),

  ('bag',       'bag'),
  ('bags',      'bag'),
  ('bao',       'bag'),
  ('gói',       'bag'),
  ('goi',       'bag'),

  ('cay',       'cay'),
  ('cây',       'cay'),

  ('thanh',     'thanh'),
  ('mảnh',      'thanh'),
  ('manh',      'thanh'),

  ('vien',      'vien'),
  ('viên',      'vien'),
  ('hat',       'vien'),
  ('hạt',       'vien'),

  ('thung',     'thung'),
  ('thùng',     'thung'),

  -- ton aliases extension
  ('metric-ton',  't'),
  ('metric-tons', 't')
on conflict (alias_norm) do nothing;

commit;
