# Feature: Johnson Onboarding + 3 New Features

**Date:** 2026-05-10
**Scope owner:** user (dennis.anh@gmail.com)
**Status:** discovery complete, awaiting user sign-off before code

Bundles Johnson real-data ingest with three new features that should ship
*before* the ingest so we don't have to reset Johnson twice. New features:
**TKX/TKN file management**, **Catalog-from-BCCT**, **NVL Substitute (hybrid
trigram + embedding)**.

---

## Audit findings (relevant)

### Data Hub current state
- Mig **058** applied (`058_d9_catalog_insert_trigger.sql`). Next mig = 059.
- BCCT lives in `hub.bcct_rows` (composite PK `(client_id, year, transaction_key, line_no)`,
  `transaction_key = direction||declaration_no||line_no||item_code`). Direction
  enum: `import|export`. **No file attachment column.** No header table —
  row-level grain.
- Materials in `hub.materials`, PK `material_code` (renamed from `customs_code`
  at mig 042), `category` enum (`nvl|tp|btp_sx|btp_nm|ccdc`), `source` enum
  (`client_declared|bcct_observed|bom_observed|system`). Multi-role computed
  by view `v_material_roles` — no stored column.
- Audit shared via `hub.bom_audit_events` — reuse pattern enforced
  (memory `feedback_reuse_audit_events`). New event types = new `event_type`
  string, **no new audit table**.
- `post_ingest_hooks` infra exists at `app/parsers/bom_adapters/__init__.py:100-241`.
  HOOKS dict + `_set_hooks()`. Currently only `derive_btp_shallows`. Wire-up
  into upload flow is BACKLOG-tracked, not yet shipped.
- `FileBackend` Protocol at `app/storage/__init__.py`. `LocalFSBackend` ready,
  S3 deferred. Key format: `module/client_id/token_hex8_filename`.
- **Postgres extensions:** neither `pg_trgm` nor `pgvector` enabled. Need
  migrations to enable both.
- `johnson-vn` client_id **already exists** via `auto_seed_demo_if_empty()`
  (`app/seed.py:35`). Has seed BCCT data — needs wipe before real ingest.
- BOM adapter `sap_exploded_levels` already exists for Johnson SAP profile
  (`app/parsers/bom_adapters/sap_exploded_levels.py`). Legacy key
  `johnson_sap_exploded` mapped at `__init__.py:78`.

### Johnson source data (`/mnt/p/Downloads/Johnson-20260507T123554Z-3-001/Johnson/`)
- BCCT NK: 60,177 rows, 54 cols. Header row 9. **Số TK** col[1], 12-digit
  integer. **Tên hàng** rich (avg 136 chars, mixed Vi+En, structured).
- BCCT XK: 5,673 rows, identical schema.
- TECHNICAL BOM: 106 XLSX files (1/product). Multi-level "Explosion level"
  hierarchy. SAP-exploded format → maps to existing adapter.
- TKN.rar: 144MB (PDF scans of import declarations).
- TKX.rar: 19MB (PDF scans of export declarations).
- Completed CO Dossiers: 12 sample dossiers — reference only, **not for
  ingest**.
- Declaration cardinality: 1 declaration → 1-50 line items (776 declarations
  hit the 50-row max — investigate ceiling).

### CO codebase (audit-only, code seed reference)
- BCCT parser at `app/source_store.py:697-753` (`parse_bcct_workbook()`).
  Header aliases include Vietnamese (`so_tk → declaration_no`). Auto-detects
  sheet by required headers.
- Catalog upload separate XLSX flow at `source_store.py:534-573`.
- BOM profiles include `johnson_sap_exploded` — already ported to Data Hub.
- CO does **not** manage TKX/TKN files. Use case is read-only consumer of
  Data Hub's future API.
- CO has `allocation_code` extracted via per-client regex from BCCT
  description — different concept from substitute (it's stock-lot tracing,
  not material-similarity).

---

## Decisions (locked with user)

1. **Sequence:** Phase 0 (Johnson client reset + BCCT ingest) → Feature 6
   (TKX/TKN) → Feature 3 (Catalog-from-BCCT) → Feature 4 (Substitute) →
   Phase 4 (BOM ingest + flatten). Rationale: features 3+4 affect catalog
   shape, so ingest BCCT-only first, run features, then catalog/BOM ingest
   on the new shape — avoids second Johnson reset.
2. **Catalog source-of-truth:** BCCT-derived default + XLSX override
   (parallel sources, client-confirmed wins on conflict).
3. **TKX/TKN:** separate table `customs_declaration_files`, link to BCCT
   rows via `declaration_no + direction + client_id`.
4. **Substitute rules (5 priorities):** P1 client-confirmed + P2
   same-customs-different-internal + P3 prefix-rule (deferred) + P4 same-HS
   + P5 hybrid (trigram + embedding). Each rule **toggleable per client**
   via `hub.clients.substitute_rules` JSONB. Johnson defaults: P2 OFF
   (because `customs_code = internal_code`), P4 ON, P5 ON.
5. **Embedding pipeline:** Postgres `pgvector` + OpenRouter, pre-built
   vectors at ingest, runtime SQL only (no API call at search time).
   Embedding text composes **multi-field**:
   `{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.` — not just
   `name`. Audit confirmed description avg 136 chars mixed Vi+En with
   structure → high embedding value-add.
6. **Embedding settings — 2-tier config:** global default in
   `data_hub_settings.py`, per-client override via
   `hub.clients.embedding_config JSONB NULL`. Materials track
   `embedding_text_hash`, `embedding_model`, `embedding_at` →
   self-invalidating re-embed on config change.
7. **Audit table:** reuse `hub.bom_audit_events` for any new events. Don't
   propose new audit tables.
8. **Johnson-specific data shape:** `internal_code = customs_code` always.
   BTP_SX without NP/XK do not appear in BCCT — they enter the catalog
   only via BOM ingest with `source='bom_observed'` (Phase 4). This is
   expected, not a gap.

---

## Phase 0 — Johnson BCCT ingest (1 day)

### Source data

**Path:** `data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/`
- `BaoCaoHangChiTietNK - JOHNSON - ALL (06.05.2026).xls` — 60,177 rows,
  2,354 declarations
- `BaoCaoHangChiTietXK JOHNSON - ALL (06.05.2026).xls` — 5,673 rows,
  869 declarations
- `TKN/` — 2,351 per-declaration XLS files (extracted)
- `TKX/` — 834 per-declaration XLS files (extracted)
- `TECHNICAL BOM - JOHNSON/` — 106 BOM XLSX (Phase 4)

### 50-line cap is VNACCS hard limit — NOT truncation

Initial distribution analysis spotted a cliff at exactly 50 lines/declaration
(776 NK declarations capped at 50, none above). Cross-checked against
per-TK XLS files in `TKN/`: every per-TK file has ≤50 goods entries, line
count matches BCCT exactly for sampled cases (50→50, 49→49). No declaration
spans multiple TKN files.

→ The 50/declaration cap is **VNACCS system-enforced**. Brokers (here
Trong Tin Logistics) pack declarations to max for filing efficiency,
producing the natural spike at 50. **No data loss, no agency follow-up
needed.**

### TK file ↔ BCCT row mismatch (acceptable)

- NK: 4 BCCT declarations have no TKN file; 1 TKN file is orphan.
- XK: 37 BCCT declarations have no TKX file; 2 TKX files are orphan.

Mismatches expected (legacy data, partial archive supply). Surface in UI
via Feature 6 (TKX/TKN management): material/declaration views show file
availability badge per declaration. Agency can supplement missing files
later.

### Steps

1. Delete `_seed_johnson()` function (per resolved open question 1).
   Replace with `scripts/seed_dev_clients.py` invoked manually for dev only.
2. Wipe seed data: `DELETE FROM hub.bcct_rows WHERE client_id='johnson-vn'`
   + materials seeded under that client + relevant `source_uploads` rows.
   Keep client row.
3. Ingest BCCT XK + NK via existing CLI:
   ```
   uv run python scripts/ingest_curated_xlsx_direct.py \
       --client johnson-vn --kind bcct \
       --file "data/source_inventory/.../BaoCaoHangChiTietNK*.xls"
   uv run python scripts/ingest_curated_xlsx_direct.py \
       --client johnson-vn --kind bcct \
       --file "data/source_inventory/.../BaoCaoHangChiTietXK*.xls"
   ```
4. Verify: NK 60,177 rows / 2,354 decl, XK 5,673 rows / 869 decl.

### Verify checklist

- Row counts match XLSX exactly.
- `direction` distribution: import 60,177 / export 5,673.
- `declaration_no` cardinality matches expected per direction.
- Spot-check 10 random rows: Tên hàng, customs_code, Mã HS, đơn vị tính
  consistent with XLSX cells.

---

## Feature 6 — TKX/TKN management (2-3 days)

### Schema (mig 059)

```sql
CREATE TABLE hub.customs_declaration_files (
    id              BIGSERIAL PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES hub.clients(client_id),
    declaration_no  TEXT NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('import','export')),
    file_kind       TEXT NOT NULL CHECK (file_kind IN ('xls','pdf','scan','other')),
    backend_key     TEXT NOT NULL,        -- FileBackend key
    original_filename TEXT NOT NULL,
    declaration_date DATE,
    sha256          TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    uploaded_by     TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT,
    UNIQUE (client_id, declaration_no, direction, sha256)
);
CREATE INDEX ix_decl_files_lookup
    ON hub.customs_declaration_files (client_id, declaration_no, direction);
```

Why composite uniqueness on `sha256`: same declaration may have multiple
files (PDF + XLS + scan), but identical bytes uploaded twice = no-op.

### Parser

Filename regex extract: `(?P<num>\d{12})_(STK|TKN|TKX)\.(xlsx?|pdf)` —
extract number from filename. Then **cross-validate** with content:
- For XLS: read `Số TK` cell (per BCCT format, top-right area, header rows).
- For PDF: skip content extraction MVP; trust filename + manual confirm.
- Mismatch filename vs cell → reject with clear error, don't auto-resolve.

### FileBackend integration

- Module name: `customs_declarations`
- Backend key: `customs_declarations/{client_id}/{declaration_no}_{direction}_{sha256[:8]}.{ext}`
- LocalFS day 1; S3 untouched.

### API endpoints

```
GET  /api/v1/clients/{client_id}/declarations
       ?direction=import|export&from=YYYY-MM-DD&to=YYYY-MM-DD&q=<num>
GET  /api/v1/clients/{client_id}/declarations/{declaration_no}/files
       ?direction=import|export
GET  /api/v1/clients/{client_id}/declarations/{declaration_no}/files/{id}/download
POST /clients/{client_id}/declarations/upload    (multipart, web upload)
```

`GET /declarations` returns the **list of declaration_no the client has**
(distinct from `bcct_rows`), with file count. `GET /files` returns metadata
list. Sister-app C/O composes its own logic for "TKX of shipment + TKN of
constituent NVL" — not Data Hub's responsibility in MVP.

### UI file-availability indicator

BCCT row list (and material detail BCCT panel from Feature 3) shows a
badge per row: ✅ "Có TK" if file present, ⚠️ "Thiếu TK" if not. Click
badge → file detail or upload prompt. Acceptable that some declarations
have no file (legacy data).

### Auth (sister-app access)

Reuse existing service-account token from CO write-back design (see
`data_hub_client.py` Bearer token pattern in CO repo). Scope: `declarations:read`.

### TKN.rar / TKX.rar bulk import

Day-1 tooling: `scripts/import_declaration_archive.py` — extract RAR,
parse filenames, validate, batch upload via FileBackend. RAR extraction:
use `unrar` CLI (system dep) — confirm available on dev + demo server.

---

## Feature 3 — Catalog from BCCT (3-4 days)

### Item-unique key

`(client_id, customs_code, internal_code)` — both required. Memory
`project_bom_code_multirole` confirms 1 customs_code can map to multiple
internal_codes for clients like Growatt. Use both as composite identity.

**Johnson specifics (per user 2026-05-10):**
- `internal_code = customs_code` always → composite key naturally collapses
  to single field. No schema change needed.
- BTP_SX without imported NP and not exported are absent from BCCT
  entirely. Catalog-from-BCCT for Johnson will be incomplete on this slice
  — closed by Phase 4 BOM ingest writing materials with `source='bom_observed'`.

### Representative picker

Per `(customs_code, internal_code)` group, pick representative row by:
1. **Frequency desc** (most-occurring exact value combo).
2. **Tie-break: most recent** `registration_date`.
3. **Tie-break 2: import direction preferred** (NK has more rows, more
   reliable for NVL catalog).

Stored as a **view** `hub.v_catalog_bcct_derived` (no derived in source
per memory `feedback_no_derived_in_source`). Materialize only if perf
requires (defer until measured).

### Schema delta (mig 060)

Add provenance distinguish on `hub.materials.source`:
- Existing values: `client_declared`, `bcct_observed`, `bom_observed`, `system`
- BCCT-derived items get `bcct_observed` (already exists). XLSX upload
  flow already uses `client_declared`. **No new value needed.**

Add column `hub.materials.bcct_representative_row_key` TEXT NULL —
references the chosen `(transaction_key, line_no)` from `bcct_rows` for
"đại diện" linkage. Enables UI to jump to the canonical row.

### Inconsistency detection

Per `(customs_code, internal_code)` group, compute drift across BCCT rows
on these fields, mirror UoM drift gate severity tiers:

| Field | Severity | Notes |
|---|---|---|
| `unit` (đơn vị tính) | **CRITICAL** | UoM mismatch breaks BOM math; reuse existing UoM drift logic |
| `hs_code` (Mã HS) | **WARN** | Often legitimate (HS code variants per declaration) |
| `name` (Tên hàng) | **INFO** | Typos / language drift; show count of distinct values |
| `unit_price` | **INFO** | Price varies by shipment, expected drift |
| `country_origin` (Xuất xứ) | **INFO** | Multi-source supply normal |

Stored as part of view `v_catalog_bcct_derived` — computes on read.

### UI — catalog material detail

New panel: **"Phân tích từ BCCT"** below existing material details.
- Header row: count of source BCCT rows + "đại diện" pointer.
- Table: distinct values for each drift-tracked field (`unit`, `hs_code`,
  `name`, `unit_price` ranges, `country_origin`) with row count per value.
- Severity styling:
  - CRITICAL: red border + tooltip explaining impact (UoM breaks BOM math).
  - WARN: amber border, tooltip.
  - INFO: gray, just count.
- Filter button: "Show all BCCT rows for this code" → links to BCCT search
  pre-filtered by `(customs_code, internal_code)`.

### Override mechanism (XLSX)

Existing XLSX catalog upload flow stays. When a row exists from XLSX
(`source='client_declared'`), it shadows the BCCT-derived view entry
(view does LEFT JOIN, prefers stored row).

### Migration safety (Growatt)

- Growatt catalog is upload-XLSX-driven currently. View is **additive** —
  doesn't change existing reads.
- Validate on Growatt that `v_catalog_bcct_derived` produces sensible
  output for at least 5 sample products before showing UI panel.

---

## Feature 4 — NVL Substitute hybrid (5-6 days)

### Schema (mig 061)

```sql
-- enable extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- per-client toggles
ALTER TABLE hub.clients
    ADD COLUMN substitute_rules JSONB NOT NULL DEFAULT
        '{"p1_client_confirmed":true,"p2_same_customs_diff_internal":true,
          "p3_prefix_rule":false,"p4_same_hs":true,
          "p5_trigram":true,"p5_embedding":true}'::jsonb,
    ADD COLUMN embedding_config JSONB NULL;   -- null = use global default

-- Johnson opt-out for P2
UPDATE hub.clients
   SET substitute_rules = substitute_rules || '{"p2_same_customs_diff_internal":false}'::jsonb
 WHERE client_id = 'johnson-vn';

-- substitution edges
CREATE TABLE hub.material_substitutes (
    id              BIGSERIAL PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES hub.clients(client_id),
    material_a_code TEXT NOT NULL,        -- (client_id, material_code) FK to materials
    material_b_code TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN
                       ('client_confirmed','same_customs_diff_internal',
                        'same_hs','prefix_rule',
                        'trigram','embedding','manual_user')),
    score           NUMERIC(5,4),         -- 0..1; null for client_confirmed
    confirmed_by    TEXT,                 -- user_id; null if auto-suggested
    confirmed_at    TIMESTAMPTZ,
    rejected_by     TEXT,                 -- user marked NOT a substitute
    rejected_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, material_a_code, material_b_code, source)
);
CREATE INDEX ix_subs_lookup
    ON hub.material_substitutes (client_id, material_a_code);

-- material embedding storage + tracking
ALTER TABLE hub.materials
    ADD COLUMN description_embedding vector(1536),
    ADD COLUMN embedding_text_hash    TEXT,           -- sha256 of generated text
    ADD COLUMN embedding_model        TEXT,           -- model used (e.g. openai/text-embedding-3-small)
    ADD COLUMN embedding_at           TIMESTAMPTZ;
CREATE INDEX ix_materials_embedding ON hub.materials
    USING hnsw (description_embedding vector_cosine_ops)
    WHERE description_embedding IS NOT NULL;

-- trigram index on internal code
CREATE INDEX ix_materials_code_trgm ON hub.materials
    USING gin (material_code gin_trgm_ops);
```

Edge is **directed** (`a → b`). Symmetric pairs stored as 2 rows. Some
substitutions may be 1-way (B substitutes for A, not vice versa) — depends
on cost/quality.

### Per-client rule toggles

Each rule reads `clients.substitute_rules` before running:
- **P1 client_confirmed** — always honor uploaded pairs (rule cannot be
  disabled, only the auto rules below).
- **P2 same_customs_diff_internal** — same `customs_code`, different
  `internal_code` → substitute. Default ON. **Johnson: OFF** (because
  `customs_code = internal_code` always; rule would self-match noise).
- **P3 prefix_rule** — code prefix grouping (Phase 5+, deferred). Default OFF.
- **P4 same_hs** — same `hs_code` → substitute candidate. Default ON.
- **P5 trigram + embedding** — similarity. Default ON.

### P1 — client-confirmed table (input flow)

**File format:** XLSX with columns `material_a_code`, `material_b_code`,
optional `notes`. Upload via web route `POST /clients/{cid}/substitutes/upload`.

Insert with `source='client_confirmed'`, `confirmed_by=request.user.id`,
`confirmed_at=now()`. Conflict resolution: if pair already exists with auto
sources (`trigram`, `embedding`, `same_hs`, etc.), the `client_confirmed`
row **coexists** as a separate UNIQUE on `(client_id, a, b, source)` — UI
shows all matching sources; client_confirmed always wins on combined score.

### P2 — same customs, different internal

For clients where `customs_code` and `internal_code` legitimately differ
(Growatt and most), rows sharing `customs_code` but with distinct
`internal_code` are equivalent goods declared under same HS classification
with different internal SKUs. Strong substitute signal.

SQL:
```sql
SELECT client_id, m1.material_code AS a, m2.material_code AS b,
       0.95 AS score, 'same_customs_diff_internal' AS source
FROM hub.materials m1
JOIN hub.materials m2 USING (client_id)
WHERE m1.customs_code = m2.customs_code
  AND m1.internal_code <> m2.internal_code
  AND m1.material_code <> m2.material_code;
```

**Skipped for Johnson** (rule toggled off).

### P4 — same HS code group

SQL view `v_substitute_candidates_same_hs`:
```sql
SELECT client_id, m1.material_code AS a, m2.material_code AS b,
       1.0 AS score, 'same_hs' AS source
FROM hub.materials m1
JOIN hub.materials m2 USING (client_id, hs_code)
WHERE m1.material_code <> m2.material_code
  AND m1.hs_code IS NOT NULL;
```

Materialize via background job `refresh_substitute_candidates(client_id)`
that writes into `material_substitutes` with `source='same_hs'`. Run on
catalog change (post_ingest_hook). Honors `clients.substitute_rules.p4_same_hs`.

### P5a — trigram (always-on)

Background job per material:
```sql
SELECT m2.material_code,
       similarity(m1.material_code, m2.material_code) AS score
FROM hub.materials m1, hub.materials m2
WHERE m1.client_id = m2.client_id
  AND m1.material_code <> m2.material_code
  AND m1.material_code % m2.material_code  -- pg_trgm `%` operator
ORDER BY score DESC
LIMIT 20;
```

Insert top 10 per material with `source='trigram'`, `score=similarity`.
Threshold: 0.4 (tunable). Pure code-based — fast, zero cost, runs on every
catalog change.

### P5b — embedding (offline batch)

**Embedding text composition (multi-field, not just `name`):**

```python
def build_embedding_text(material, template):
    return template.format(
        name=material.name or "",
        hs_code=material.hs_code or "",
        unit=material.unit or "",
        country_origin=material.country_origin or "",
        category=material.category or "",
        notes=material.notes or "",
    )
```

Default template:
```
{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.
```

Why multi-field over name-only:
- Same name across origins = NOT same material for substitute (origin matters
  for RVC).
- Same HS code carries categorical signal independent of name wording.
- UoM differentiates form (cuộn vs cái vs kg).
- Material code excluded — handled by trigram layer separately.

**Settings — 2-tier config:**

Global default in `data_hub_settings.py`:
```python
EMBEDDING_DEFAULT = {
    "provider": "openrouter",
    "model": "openai/text-embedding-3-small",   # dim 1536
    "text_template": "{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.",
    "batch_size": 100,
    "score_threshold": 0.7,
    "min_text_chars": 8,            # below = skip embed (too sparse)
}
```

Per-client override via `hub.clients.embedding_config JSONB NULL`:
- NULL → use default
- Partial JSON → merge over default

**Self-invalidating re-embed:**
- On embed: store `embedding_text_hash = sha256(text)`,
  `embedding_model = config.model`, `embedding_at = now()`.
- Re-embed condition: `text_hash` recomputed from current state ≠ stored
  OR `model` changed in config.
- Background nightly job + manual trigger button (admin/settings page) call
  same `enqueue_dirty_embeddings(client_id)` which scans condition and
  enqueues batch.

**Pipeline:**
1. **Batch script** `scripts/embed_materials.py` — query materials where
   `description_embedding IS NULL` OR text/model dirty, build text per
   client config, batch 100/req, call OpenRouter, write vector + tracking.
2. **Post-ingest hook** `derive_embeddings` — registered in `HOOKS` dict,
   wired to bcct + bom + catalog upload completion. Hook enqueues
   embedding job (non-blocking).
3. **Search runtime:**
   ```sql
   SELECT material_code,
          1 - (description_embedding <=> :a_vector) AS score
   FROM hub.materials
   WHERE client_id = :cid
     AND description_embedding IS NOT NULL
   ORDER BY description_embedding <=> :a_vector
   LIMIT 20;
   ```
   No API call — vector is from DB.
4. Insert top 10 with `source='embedding'`, `score=cosine_similarity`.

**OpenRouter setup:**
- Env: `OPENROUTER_API_KEY`. Add to `data_hub_settings.py`.
- Model: `openai/text-embedding-3-small` (dim 1536, $0.02/1M tokens) default.
- Failure mode: log + graceful skip. Material remains substitute-eligible
  via trigram + same_hs only.

**Cost estimate Johnson (multi-field text):**
- Avg text length: ~180 tokens (name 136 chars + HS + UoM + origin
  metadata ≈ 180 tokens).
- ~5K materials × 180 tokens = 900K tokens batch initial ≈ **$0.018**.
- Edit churn 10/day × 180 tokens × $0.02/1M ≈ $0.00004/day.
- Annual: **< $0.50** even with conservative re-embed churn.

### Scoring formula (hybrid)

When showing candidates to user, dedupe across sources and combine score:

```
combined_score = max_per_pair(
    if source='client_confirmed':           1.00  (always top)
    if source='same_customs_diff_internal': 0.90
    if source='same_hs':                    0.85
    if source='manual_user':                0.80
    if source='embedding':                  0.30 + 0.70 * cosine
    if source='trigram':                    0.20 + 0.50 * trgm_sim
    if source='prefix_rule':                0.40 + 0.40 * rule_match
)
```

Final: highest single source wins (not weighted avg — sources are
independent signals). UI shows ALL sources that flagged the pair, not
just winning one. Tunable post-ship.

### UI — material detail "Vật tư thay thế" panel

```
┌─────────────────────────────────────────────────────────┐
│ Vật tư thay thế cho [JOHN-001 / Bracket steel]          │
├─────────────────────────────────────────────────────────┤
│  Code         | Tên hàng         | Reasons     | Score  │
├─────────────────────────────────────────────────────────┤
│  JOHN-001A    | Bracket steel V2 | [client] [HS]| 1.00  │
│  JOHN-001B    | Bracket aluminum | [HS] [trgm] | 0.85   │
│  JOHN-XYZ     | Bracket alt      | [emb 0.78]  | 0.84   │
│  ...                                                    │
├─────────────────────────────────────────────────────────┤
│  [Đề xuất thêm thủ công]    [Báo không phải thay thế]   │
└─────────────────────────────────────────────────────────┘
```

- Click row → navigate to that material's detail.
- Reason badges colorized: client=green, HS=blue, trgm=gray, emb=purple.
- Reject action writes `rejected_by`, `rejected_at` — auto-suggest doesn't
  re-show rejected pairs.
- Manual add: search input → pick → insert with `source='manual_user'`.

### API for sister-apps (C/O)

```
GET /api/v1/clients/{cid}/materials/{material_code}/substitutes
    ?min_score=0.5&include_rejected=false
```

Returns ranked list with sources + scores. C/O uses for LVC/RVC tweaking
in CO declaration prep.

---

## Phase 4 — Johnson BOM ingest + flatten (1-2 days)

After Features 6+3+4 ship.

1. Ingest 106 Technical BOM XLSX via existing `sap_exploded_levels` adapter.
   CLI:
   ```
   for f in /mnt/p/.../TECHNICAL\ BOM\ -\ JOHNSON/*.xlsx; do
       uv run python scripts/ingest_bom.py --client johnson-vn \
           --profile johnson_sap_exploded --file "$f"
   done
   ```
2. Trigger `derive_btp_shallows` post-ingest hook.
3. Confirm 4-shape coverage: raw_graph (always) + shallow (auto) + full_flat
   (on demand). manual_flat not applicable to Johnson SAP.
4. Verify: spot-check 5 products, compare line count to source XLSX.

---

## Manual test plan

**Phase 0:**
- [ ] BCCT NK row count = 60,177; XK = 5,673. Fail if drift > 0.1%.
- [ ] Direction distribution sane.
- [ ] 10 random rows match XLSX exactly on Tên hàng, Số TK, customs_code.

**Feature 6:**
- [ ] Upload 1 XLS file via web → appears in `customs_declaration_files`.
- [ ] Upload duplicate (same sha256) → no-op, returns existing ID.
- [ ] Filename mismatch with cell value → upload rejected with clear error.
- [ ] Bulk import TKN.rar → file count matches archive content.
- [ ] `GET /declarations/{num}/files` returns expected files.
- [ ] Sister-app token can call API (curl with Bearer token).

**Feature 3:**
- [ ] After BCCT ingest, `v_catalog_bcct_derived` returns ~N rows where N =
      distinct `(customs_code, internal_code)` in BCCT.
- [ ] Material detail page shows "Phân tích từ BCCT" panel with row count.
- [ ] Inject UoM drift in test data → CRITICAL severity shown.
- [ ] Click "đại diện" link → jumps to canonical BCCT row.
- [ ] XLSX-uploaded material shadows BCCT-derived (verify on Growatt).

**Feature 4:**
- [ ] `pg_trgm` + `pgvector` extensions enabled (regression test).
- [ ] Upload P1 XLSX (10 confirmed pairs) → all stored.
- [ ] Same-HS view returns expected pairs for sample HS code.
- [ ] Trigram suggestions for `JOHN-001` include `JOHN-001A` with score > 0.5.
- [ ] Embed batch script processes 5K materials without API errors.
- [ ] Embedding search returns semantic matches (test: pair with similar
      Vietnamese descriptions, different codes).
- [ ] UI panel renders, badges correct color, reject action persists.
- [ ] C/O API call returns ranked results with `min_score` filter.

**Phase 4:**
- [ ] All 106 BOM files ingest without errors.
- [ ] 5 random products: shallow flatten count matches expected.
- [ ] No UoM drift CRITICAL on BOM rows after ingest.

---

## Done criteria

- All migrations 059-061 applied on dev + demo server.
- All manual test plan items pass.
- Tests added: ≥30 new tests across the 4 phases (parser, schema, API, UI smoke).
- UI smoke screenshots committed under
  `.ai/features/2026-05-10-johnson-onboarding/screenshots/` for Features 3, 4, 6.
- Memory updates: substitute-table contract, embedding pipeline, drift gate
  extensions for catalog inconsistency.
- BACKLOG.md entries struck through.
- Sister-app notes published for new APIs (TKX/TKN, substitutes).

---

## Risks / open questions

### Open questions — RESOLVED 2026-05-10 with user

1. ✅ **Seed cleanup:** delete `_seed_johnson()` entirely. Replace with
   explicit `scripts/seed_dev_clients.py` (dev-only, never auto-runs).
2. ✅ **Internal_code Johnson:** `internal_code = customs_code` always for
   Johnson. BTP_SX without NP/XK absent from BCCT — fill via Phase 4 BOM
   ingest.
3. ✅ **Per-client substitute rule toggle:** `hub.clients.substitute_rules`
   JSONB column. Default = all auto rules ON except `prefix_rule`. Johnson
   sets `p2_same_customs_diff_internal=false` (not P4 — P4 stays ON).
4. ✅ **TKX/TKN cross-validate:** XLS reads `Số TK` cell, PDF MVP trusts
   filename only, OCR deferred Phase 5+.
5. ✅ **Re-embed schedule:** nightly batch + manual trigger button on
   admin/settings page.
6. ✅ **Substitute API scope:** new scope `substitutes:read`.

### Open questions remaining (need answer before/during implementation)

A. ✅ **Johnson 50-line cap RESOLVED:** confirmed VNACCS hard limit, not
   truncation. Phase 0 NK + XK both unblocked. TKN/TKX-vs-BCCT mismatch
   (4 NK + 37 XK missing files, 3 orphans) accepted as legacy data
   completeness — surface in UI per Feature 6, agency supplements later.
B. ✅ **TKN/TKX file format RESOLVED:** files are XLS (per-declaration
   form export), naming `<seq>_<decl_no>.xls`. Parse `decl_no` from filename
   tail; cross-validate against cell content via `Số TK` field.
C. **Embedding text fields beyond default 4:** start with
   `{name, hs_code, unit, country_origin}`. After dev measure, decide
   if `supplier`, `notes` add signal or noise. Tunable post-ship.

### Risks

- **OpenRouter dependency:** if API down at ingest time, embedding column
  stays NULL for new materials — substitute hybrid degrades gracefully to
  trigram + same_hs (acceptable).
- **776 Johnson declarations capped at 50 lines:** unclear if XLSX export
  truncation. If real cap, BCCT may be incomplete. **Block ingest until
  user confirms.**
- **Vector index size:** 5K materials × 1536 dim × 4 bytes ≈ 30MB.
  Negligible. HNSW build time < 1min.
- **Catalog view perf at scale:** Growatt has ~3K materials, Johnson
  similar. View on read may be slow on cold cache. Materialize if measured
  > 200ms p95.
- **Description embedding multilingual quality:** `text-embedding-3-small`
  is multilingual but Vietnamese coverage less proven than English. If
  similarity scores look noisy in dev, swap to `cohere/embed-multilingual-v3`
  via OpenRouter (~same cost).
- **Memory `feedback_no_derived_in_source`:** view-based catalog respects
  this; embedding column on `materials` is the one exception (cached
  derived value). Justification: HNSW index needs storage. Acceptable
  trade-off, document in memory.
- **Cross-app schema impact:** new columns on `hub.materials` and new
  tables `hub.customs_declaration_files`, `hub.material_substitutes` —
  sister apps (BCQT, CO) read-only consumers; document in
  `.ai/sister-app-notes/2026-05-10-johnson-features.md` after build.

---

## Suggested next step

**Resolve 6 open questions with user → start Phase 0** (Johnson reset +
BCCT ingest, lowest-risk warm-up). Then per-feature: each gets `/tdd`
cycle → `/rev` → commit → UI smoke screenshot. Bundle 3 features into 1
PR or split — defer that decision until Feature 6 is in.
