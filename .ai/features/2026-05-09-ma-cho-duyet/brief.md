# Feature: Mã chờ duyệt — passive candidate feed

**Date:** 2026-05-09
**Status:** Discovery (decisions resolved 2026-05-09)
**Replaces:** `catalog_derive` wizard (mig 043 + `app/routes/catalog_derive.py` +
`app/templates/clients/catalog_derive.html`) — shipped 2026-05-08, user pivoted
post-shipping. No production data depends on this; `catalog_derive_configs` rows
are throwaway.

**Resolved decisions (2026-05-09):**
- Mig number: **047** (monotonic; reserved 044 stays unused).
- BCCT both-direction hint: **nvl + multi-direction badge** (warn, don't auto-classify).
- Accept form: **Full** — adds Phase 2 manual-field columns (`supplier_hint`,
  `production_source`, `uom`) to `materials` as part of mig 047. **Does NOT**
  pull `roles[]` or drop `category` — those stay on Phase 2 backlog.
- **Catalog scope: ALL codes (NB + HQ + unified)**. Catalog = source of truth
  cho cả BCQT và CO. `materials` thêm `code_kind` enum.
- **Single candidates table** (state machine: pending/accepted/rejected). Không
  có rejections table riêng. Refresh on render rebuilds stats từ truth.
- BCCT có 2 streams: customs_code (HQ) + paren-extract (NB via rules).
  Dedup khi NB.code == HQ.code (Johnson) → kind='unified'.
- BOM stream chỉ sinh NB candidates.
- Accept tự động tạo code_mappings rows cho cặp (HQ, NB) đã có trong materials
  (bidirectional, idempotent, retroactive).

## Scope

**In:**
- New page `/clients/<id>/catalog/candidates` ("Mã chờ duyệt").
- Watches BCCT + BOM continuously — no per-page rule authoring. Extraction
  rules already live in `hub.client_parser_rules` (per-client).
- Per-row Accept (insert into `materials`) / Reject (insert into
  `catalog_candidate_rejections`).
- Drop existing `catalog_derive` wizard infrastructure (mig + route + template
  + tests).

**Explicitly NOT in:**
- No regex authoring UI on this page. Authoring stays in the existing
  `/clients/<id>/parser-rules` page (already shipped).
- No bulk Accept-all (per item-by-item review intent — staff confirms each).
  Bulk Reject-by-pattern deferred.
- No conflicts page — that's a separate BACKLOG item (`/catalog/conflicts`).
- No new code mappings, no UoM resolution — Accept just inserts a stub
  material with `source=bcct_observed/bom_observed` + `status=under_review`.

## 3 client shapes

| Shape | Detection | NB resolution | Examples |
|---|---|---|---|
| **Unified** | không rules, không mappings | customs_code IS canonical | Johnson |
| **Embed** | parser_rules exist | regex paren trong goods_name | Growatt (also has BQD) |
| **BQD-only** | mappings exist, no rules | code_mappings JOIN customs_code | DKE-like |

`has_dual_system = rules_exist OR mappings_exist` — flag điều khiển code_kind
classification và candidate sourcing.

## 4-stream architecture

```
Source 1: BCCT.customs_code        → kind='hq' (dual) | 'unified' (single)
Source 2: BCCT.goods_name + rules  → kind='nb' (chỉ embed-shape)
Source 3: BOM edges                → kind='nb' (dual) | 'unified' (single)
Source 4: code_mappings rows       → 2 candidates per row:
                                      customs_code → kind='hq'
                                      internal_code → kind='nb'
       │
       ▼
   merge by (code, kind) — sources[] tracks origin {'bcct','bom','bqd'}
       │
       ▼
   anti-join materials (already in catalog → skip)
       │
       ▼
   UPSERT vào hub.catalog_candidates (status sticky)
       │
       ▼
   Feed query: SELECT * WHERE status='pending'
```

**Per-shape coverage:**
- Johnson (unified): chỉ Source 1 + 3 (tất cả 'unified', 1 stream sau dedup).
- Growatt (embed + BQD): cả 4 sources. Source 4 redundant với Source 2 nhưng
  ON CONFLICT no-op → an toàn.
- DKE-like (BQD only): Source 1 (HQ) + 3 (BOM nếu có) + 4 (BQD = source duy
  nhất sinh NB candidate). Source 2 empty.

**Why no regex form on this page:** rules ở `client_parser_rules`. Mappings ở
`code_mappings` (BQD upload). Cả 2 đều có UI authoring riêng. Candidate feed
chỉ DISCOVER, không AUTHOR.

## Decisions

### D1 — schema (mig 047)

Single migration that does 4 things:

**1. Drops `hub.catalog_derive_configs`** (table + index + comment).

**2. Creates `hub.catalog_candidates`** with state machine:
```sql
create table hub.catalog_candidates (
  candidate_id   bigserial primary key,
  client_id      text not null references hub.clients(client_id) on delete cascade,
  code           text not null,
  code_kind      text not null check (code_kind in ('nb','hq','unified')),

  -- Live observation snapshot (rebuild on refresh, not increment)
  sources        text[] not null default '{}',  -- subset of {'bcct','bom'}
  observed_count int not null default 0,
  first_seen     date,
  last_seen      date,
  sample_text    text,
  suggested_category text,
  multi_direction boolean default false,

  -- State machine
  status text not null default 'pending'
    check (status in ('pending','accepted','rejected')),
  decided_at  timestamptz,
  decided_by  text,
  decision_reason text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, code, code_kind)
);
```
- Unique key `(client_id, code, code_kind)` cho phép cùng 1 string code tồn tại
  như 2 candidate (`nb` + `hq`) — hiếm trong thực tế nhưng cover được.
- Status sticky: refresh không clobber `pending|accepted|rejected`.

**3. Extends `hub.materials`** with `code_kind` + Phase 2 manual fields:
```sql
alter table hub.materials
  add column if not exists code_kind text not null default 'unified'
    check (code_kind in ('nb','hq','unified')),
  add column if not exists production_source text
    check (production_source is null
           or production_source in ('nk','sx','mixed','unknown')),
  add column if not exists supplier_hint text,
  add column if not exists uom text;
```

**Backfill code_kind — pattern-aware (vì existing materials đã mix kinds):**
```sql
-- Dual-system clients: pattern-match material_code via parser rules + BQD lookup
with dual_clients as (
  select distinct client_id from hub.client_parser_rules
   where output_field='internal_code'
  union
  select distinct client_id from hub.code_mappings
)
update hub.materials m set code_kind = case
    -- (a) Match BQD's NB side → 'nb'
    when exists (select 1 from hub.code_mappings cm
                 where cm.client_id=m.client_id
                   and cm.internal_code=m.material_code) then 'nb'
    -- (b) Match BQD's HQ side → 'hq'
    when exists (select 1 from hub.code_mappings cm
                 where cm.client_id=m.client_id
                   and cm.customs_code=m.material_code) then 'hq'
    -- (c) Match parser rule pattern (NB-style) → 'nb'
    when m.material_code ~ '\d{3}\.[\w\-]+'
      or m.material_code ~ '[A-Z]{2,}\d{2}\.[\w\-]+'
      or m.material_code ~ '[A-Z]\d{3}\.[\w\-]+'
      or m.material_code ~ '\d{2}[A-Z]\.[\w\-]+' then 'nb'
    -- (d) Otherwise (dual-system but unmatched) → 'hq' (assume bucket)
    else 'hq'
  end
where m.client_id in (select client_id from dual_clients);

-- Single-system clients: stays 'unified' (default)
```

**Expected result trên data hiện tại:**
- Growatt 451: ~252 'nb' (paren-pattern) + ~129 'hq' (bucket-style) + ~70 'hq'
  (unmatched, fallback). Spot-check trước khi commit migration.
- Johnson 11129: tất cả 'unified' (default, không trong dual_clients).
- DKE: chưa có materials hiện tại; backfill no-op.

**Out of scope this mig:** `roles[]`, `category` drop, `hq_registration_*`,
`name_source`. Stay on Phase 2 BACKLOG.

**4. Constraint check on materials PK:** Existing PK is `(client_id, material_code)`.
Với `code_kind` mới, có thể cần PK mở rộng nếu cùng string code tồn tại như
`nb` + `hq` cho cùng client. Hiếm nhưng có thể (e.g. agency dùng `DIENTRO`
làm cả nhãn HQ và một SKU). **Quyết định**: giữ PK hiện tại; nếu xung đột thì
staff resolve bằng cách đổi code khi Accept (rare). Mở rộng PK = breaking
change cho consumers — defer.

Mig 044 was reserved for this; we use **047** to keep monotonic.

**BACKLOG impact:** Phase 2 BACKLOG item shrinks — `production_source`,
`supplier_hint`, `uom` shipped here. `roles[]` + drop `category` vẫn ở Phase 2.

### D2 — BCCT extraction: per-row classification (NB == HQ overlap aware)

Một dual-system client có nhiều material mà NB == HQ (cùng string). Per-row
classification phải detect overlap và emit 'unified' thay vì split sai thành
('X', 'hq') + ('X', 'nb').

```python
def candidates_from_bcct_row(row, rules, has_dual_system):
    hq = clean(row.customs_code)  # skip nếu '.', empty
    nbs = []
    if rules:
        nbs = [m["product_code"]
               for m in extract_all_matches_from_compiled(rules, row=row)]
        nbs = [c for c in nbs if c]  # filter empty

    if not hq and not nbs:
        return []  # noise row

    # Case 1: NB extract matches customs_code → unified (cùng 1 mã)
    if hq and hq in nbs:
        return [(hq, 'unified')]

    # Case 2: Có cả HQ + NB khác string → dual
    if hq and nbs:
        return [(hq, 'hq')] + [(nb, 'nb') for nb in nbs if nb != hq]

    # Case 3: Chỉ HQ, không paren-extract
    if hq and not nbs:
        kind = 'hq' if has_dual_system else 'unified'
        return [(hq, kind)]

    # Case 4: Chỉ paren, không customs_code (e.g. customs_code='.')
    return [(nb, 'nb') for nb in nbs]
```

**Quantified breakdown trên data Growatt thực:**

| Case | n_rows | % | Action |
|---|---|---|---|
| dual (NB != HQ) | 21,463 | 93% | emit (hq,'hq') + (nb,'nb') |
| no HQ (`customs_code='.'`) | 744 | 3.2% | emit nb only |
| unified (NB == HQ) | 616 | 2.7% | emit (hq,'unified') |
| HQ only (no paren match) | 257 | 1.1% | emit (hq,'hq') |

**Cross-row aggregation:**
Same `(code, kind)` từ nhiều rows → merge stats vào 1 candidate. Same string
xuất hiện với nhiều kinds (e.g. có row classify 'X' là unified, có row khác
classify 'X' là hq) → giữ 2 candidate rows riêng (unique key
`(client_id, code, code_kind)` cover). Staff resolve khi Accept.

**Per-client behavior với rule này:**

| Client | rules? | mappings? | dual_system | Typical output |
|---|---|---|---|---|
| Johnson | không | không | false | tất cả 'unified' |
| Growatt | có | có | true | mix 'hq'/'nb'/'unified' theo per-row |
| DKE-like | không | có | true | 'hq' (no NB stream từ BCCT vì no rules) |

### D3 — BOM stream: chỉ sinh NB candidates

Distinct codes from `bom_edges.parent_code` ∪ `bom_edges.child_code` for
non-tombstoned artifacts. **No regex applied** — codes in `bom_edges` always
canonical NB-level (BOM là internal supply chain, không có HQ-side codes).

`code_kind` cho BOM candidates:
- Client `has_dual_system` → `kind='nb'`.
- Client unified (không rules, không mappings) → `kind='unified'`.

BOM **không** sinh HQ candidates. HQ codes chỉ xuất hiện ở declaration time
(BCCT) hoặc BQD bridge.

### D3b — BQD (code_mappings) stream

Cho client BQD-shape (DKE-like) hoặc hybrid (Growatt cũng có BQD), source này
quan trọng vì BQD có thể chứa codes chưa từng xuất hiện trong BCCT/BOM hiện tại.

```python
def candidates_from_code_mappings(client_id):
    pairs = SELECT distinct customs_code, internal_code
            FROM code_mappings WHERE client_id = ?
    out = []
    for (hq, nb) in pairs:
        if hq == nb:
            # NB == HQ overlap (cùng 1 string) → unified candidate
            out.append((hq, 'unified', source='bqd'))
        else:
            out.append((hq, 'hq', source='bqd'))
            out.append((nb, 'nb', source='bqd'))
    return out
```

**Per-shape behavior:**
- Johnson: stream rỗng (no code_mappings).
- Growatt: stream ra 520 HQ + 2846 NB candidates. Phần lớn đã có trong materials
  (anti-join filter); phần chưa → bổ sung vào feed.
- DKE-like (BQD only): stream sinh **toàn bộ** NB candidates (vì BCCT goods_name
  không embed). 60 HQ + 242 NB từ DKE BQD → feed.

`sources[]` array sẽ chứa `'bqd'` cho candidates từ stream này. UI badge phân
biệt với BCCT/BOM origin.

### D4 — suggested category logic

Per row in feed, compute a hint (staff edits before Accept). Logic dùng chung
cho cả `nb`, `hq`, `unified` — chỉ khác phạm vi (1 SKU vs cả nhóm vs unified):

| Source | Evidence | Suggested category |
|--------|----------|--------------------|
| BCCT | only `direction='import'` rows | `nvl` |
| BCCT | only `direction='export'` rows | `tp` |
| BCCT | both directions | `nvl` (multi-direction badge) |
| BOM | code IS `bom_artifacts.product_code` of any artifact | `tp` |
| BOM | code is parent in edges but NOT a `bom_artifacts.product_code` | `btp_sx` |
| BOM | code is only ever `child_code` | `nvl` |
| Both BCCT + BOM | merge — prefer BOM's TP-root signal if present | (logic below) |

Merge: if BOM says TP and BCCT shows export, both agree → `tp`. If BOM says
BTP/NVL and BCCT shows import → `nvl`. Conflicts (BOM=TP, BCCT=import-only)
get suggestion=`nvl` + warning badge "BOM đánh dấu TP nhưng BCCT chỉ thấy nhập"
— staff Accept decision is the source of truth.

**HQ candidates dùng cùng logic**: e.g. `DIENTRO` chỉ thấy direction='import'
trong BCCT → suggested='nvl' (cả nhóm điện trở là NVL). `BIENTAN`-shape HQ
candidate với direction='export' → 'tp'. Hợp lý vì category của HQ bucket
phản ánh role chung của các SKU trong nhóm.

**Important nuance vs BACKLOG:** BACKLOG says "parent_code in BOM (TP root) →
`tp`". A parent_code is TP-root only if it equals an artifact's `product_code`.
Mid-tree parents are BTPs. The brief encodes this distinction.

### D5 — Accept tự động sinh code_mappings (bidirectional, idempotent)

Khi staff Accept một candidate, tự động tạo `code_mappings` rows cho mọi cặp
(HQ, NB) đã có trong materials:

```python
def on_accept_candidate(client_id, candidate):
    # 1. Insert/upsert vào materials
    INSERT materials (
      client_id, material_code=candidate.code, code_kind=candidate.code_kind,
      category, status, source=..., name, uom, supplier_hint, production_source
    ) ON CONFLICT (client_id, material_code) DO UPDATE ...

    # 2. Mark candidate as accepted
    UPDATE catalog_candidates SET status='accepted', decided_at=now(), decided_by=...
      WHERE candidate_id=candidate.candidate_id

    # 3. Auto-mapping
    if candidate.code_kind == 'hq':
        # Scan BCCT: tìm mọi NB co-occur với HQ này
        pairs = SELECT distinct customs_code, paren_extract_via_rules(goods_name)
                FROM bcct_rows
                WHERE client_id=? AND customs_code=candidate.code
                  AND paren_extract IS NOT NULL
        # Chỉ map những NB đã có trong materials
        for (hq, nb) in pairs:
            if exists(materials WHERE client_id=? AND material_code=nb):
                INSERT code_mappings (dncx_id=client_id,
                                      customs_code=hq, internal_code=nb)
                  ON CONFLICT DO NOTHING

    elif candidate.code_kind == 'nb':
        # Scan BCCT: tìm mọi HQ co-occur với NB này
        pairs = SELECT distinct customs_code, paren_extract_via_rules(goods_name)
                FROM bcct_rows
                WHERE client_id=? AND paren_extract = candidate.code
        for (hq, nb) in pairs:
            if exists(materials WHERE client_id=? AND material_code=hq
                                  AND code_kind='hq'):
                INSERT code_mappings (..., customs_code=hq, internal_code=nb)
                  ON CONFLICT DO NOTHING

    elif candidate.code_kind == 'unified':
        # Johnson-shape, no NB/HQ split, no mapping needed
        pass
```

**Tính chất:**
- **Order-independent**: Accept HQ trước hay NB trước đều ra cùng kết quả cuối.
- **Idempotent**: ON CONFLICT DO NOTHING. Re-Accept không tạo dup.
- **Conservative**: KHÔNG cascade-create materials rows. Staff vẫn kiểm soát.
- **Self-healing**: NB chưa có hôm nay → Accept HQ tạo materials.HQ + 0 mappings.
  Mai Accept NB → tạo materials.NB + mapping (HQ, NB) retroactive.
- **N-N supported tự nhiên**: 1 HQ co-occur với 100 NB → 100 mapping rows. 1 NB
  co-occur với 3 HQ → 3 mapping rows. Bảng `code_mappings` PK là `(dncx_id,
  internal_code, customs_code)` — đã design cho N-N.

**Performance**: Accept = 1 INSERT materials + 1 BCCT scan + N INSERT code_mappings
(N ≤ số distinct co-occurrences, thường <500). Sub-second per Accept.

### D6 — Accept form fields (resolved: Full)

Per row Accept opens an inline form with:

| Field | Source / default | Required |
|-------|-----------------|----------|
| `material_code` | from feed row, readonly | yes |
| `name` | sample_goods_name (BCCT) or empty (BOM) | yes |
| `category` | suggested hint (D6 below), staff edits | yes |
| `status` | `under_review` default; can pick `active` | yes |
| `uom` | empty default; staff fills | no |
| `production_source` | enum picker (nk/sx/mixed/unknown); empty default | no |
| `supplier_hint` | freetext; empty default | no |

`source` field on materials auto-set: `bcct_observed` if Accept came from a
BCCT-stream row, `bom_observed` from BOM-stream, `bcct_observed` if `source=both`
(BCCT signal is more authoritative — observed in customs filings).

Form submits POST → insert + 303 redirect back to feed. Failure (DB error,
duplicate code race) re-renders feed with error toast.

### D7 — feed UI shape

```
[Mã chờ duyệt — Growatt-VN]
[filter: kind=NB|HQ|Unified|all]   [filter: src=BCCT|BOM|both]   [filter: hint=...]

┌───────────────┬──────┬──────┬──────┬──────────┬─────────┬─────────────┬─────────┐
│ Code          │ Kind │ Src  │ Hint │ Obs      │ Last    │ Sample      │ Actions │
├───────────────┼──────┼──────┼──────┼──────────┼─────────┼─────────────┼─────────┤
│ DIENTRO       │ HQ   │ BCCT │ nvl  │ 2944 imp │ 2026-04 │ DIENTRO#&...│ [✓][✗]  │
│ 019.0023800   │ NB   │ BCCT │ nvl  │ 47 imp   │ 2026-04 │ DAUNOI#&... │ [✓][✗]  │
│ PV01.0117500  │ NB   │ BOM  │ tp   │ 3 art.   │ —       │ —           │ [✓][✗]  │
│ 1000527370    │ Unif │ BCCT │ nvl  │ 154 imp  │ 2026-03 │ Tấm đỡ...   │ [✓][✗]  │
└───────────────┴──────┴──────┴──────┴──────────┴─────────┴─────────────┴─────────┘
```

- **Sort:** observed_count desc by default.
- **Kind filter chips:** NB / HQ / Unified / all. Để staff focus theo loại.
- **Source filter:** BCCT / BOM / both.
- **Accept:** opens form prefilled (Code, Kind readonly; Category auto-hint;
  Name from sample_text; UoM/production_source/supplier_hint optional). POST →
  insert materials + auto-mapping (D5) + 303 redirect.
- **Reject:** POST update candidate.status='rejected' + decision_reason + 303.
  Row disappears.
- **Un-reject:** "Đã từ chối" collapsible section — list rejected candidates,
  button [↻] để UPDATE status='pending'.

### D8 — drop catalog_derive code

Files removed in same PR:
- `app/routes/catalog_derive.py`
- `app/templates/clients/catalog_derive.html`
- `tests/test_catalog_derive.py`
- Import line in `app/main.py` (`catalog_derive` import + `include_router`).
- Link from catalog list page (if any). Verify in `app/templates/clients/catalog.html`.

## Risks

1. **Performance — BCCT refresh = O(rows) regex scan + UPSERT.** Growatt 23k
   BCCT rows × ~2 rules → ~46k re2.search calls per refresh. Cộng UPSERT
   ~1000-2000 candidates. Acceptable (<2s) but đáng đo. Nếu chậm, chuyển sang
   post-ingest hook thay vì on-render refresh.
2. **BOM stream cần enumerate `bom_artifacts` để mark TP-roots.** Extra query.
   Rẻ — một set lookup per refresh.
3. **Auto-mapping per-Accept = 1 BCCT scan + N inserts.** Sub-second cho
   Growatt (≤500 distinct co-occurrences per code). Index on
   `(client_id, customs_code)` đã có (`idx_bcct_customs`).
4. **Drop of mig 043 in mig 047** — test data only. No production rows. Safe.
5. **`code_kind` backfill assumption**: Growatt parser_rules tồn tại ⇒ tất cả
   451 materials cũ là NB. Verify bằng manual spot-check trước khi ship — nếu
   có HQ-bucket lẫn lộn (rare) cần backfill khác.
6. **Materials PK xung đột potential**: nếu cùng client có code 'X' tồn tại
   vừa NB vừa HQ, PK `(client_id, material_code)` ngăn cản. Hiện không thấy
   trong data; nếu xuất hiện thực tế → mở rộng PK thành `(client_id,
   material_code, code_kind)` (breaking change cho consumers, defer Phase 2).
7. **`bcct_rows.customs_code='.'` hoặc rỗng**: 840 Growatt rows có
   `customs_code='.'`. Logic candidates phải skip these (không tạo HQ
   candidate cho mã rác).

## Known limitations

- **BOM-only candidate names blank**: Johnson BOM xlsx files có "Object description"
  column nhưng `sap_indented_walk.py` parser hiện tại không extract → sample_text
  blank cho 100% BOM-only candidates. Workaround: staff điền name khi Accept.
  Fix tương lai (backlog): enhance parser để lưu description vào
  `bom_edges.payload->>'description'`, refresh logic pull làm sample_text.

## Open Questions (carry-over)

1. **Auto-trigger feed badge in nav?** Show "Mã chờ duyệt: 47" badge in
   client sidebar like the bell? Could surface attention without staff
   visiting the page. **Default: NO** for v1 (one-render-per-page count
   query has cost; defer until staff requests).
2. **Reject reason — required or optional?** Schema has it nullable.
   Going with **optional + freetext** — required field adds friction for
   "obvious noise" rejects (test codes, typos).
3. **Multi-direction badge wording (D4):** `nvl` hint with badge "BCCT cả
   nhập và xuất — xét đa nguồn?" or shorter? Settle in implementation.

## Test plan

**Schema (mig 047):**
- Forward: drop catalog_derive_configs + create catalog_candidates +
  alter materials columns + backfill code_kind. Run on fresh DB + on existing
  Growatt/Johnson DB. Verify backfill: Growatt 451 materials → kind='nb';
  Johnson 11129 → kind='unified'.
- Test PK conflict: insert candidate with same (code, kind) twice → ON CONFLICT.

**Unit — extraction (4 cases per BCCT row):**
- Case 1 (dual, NB != HQ): Growatt row `customs_code='DAUNOI',
  goods_name='...(019.0023800)'` rules=[paren_rule] → [(DAUNOI, hq),
  (019.0023800, nb)].
- Case 2 (unified overlap, NB == HQ): row `customs_code='X',
  goods_name='...(X)'` rules → [(X, unified)] (single, NOT split).
- Case 3 (HQ only, no paren match): Growatt row `customs_code='ABC',
  goods_name='ABC#&Hàng XYZ'` (no parens) rules → [(ABC, hq)] vì dual_system.
- Case 4 (no HQ, paren only): row `customs_code='.',
  goods_name='...(019.X)'` rules → [(019.X, nb)].
- Johnson (single-system): row `customs_code='1000527370'` no rules →
  [(1000527370, unified)].
- BQD source — pair `(hq='X', nb='X')` (same string) → [(X, unified)] (single).
- BQD source — pair `(hq='DAUNOI', nb='019.X')` → [(DAUNOI, hq), (019.X, nb)].
- `candidates_from_bom_edges` — artifact P, edges P→Q→R, rules exist →
  [(P, nb), (Q, nb), (R, nb)]. Johnson: same edges → [(P, unified), ...].
- Suggested-category cho HQ kind: DIENTRO chỉ import → 'nvl'; BIENTAN chỉ
  export → 'tp'.

**Unit — refresh logic:**
- `refresh_candidates(client_id)` — fixture: 3 BCCT rows, 1 BOM artifact.
  Anti-join materials (1 existing). Verify candidates table populated với
  correct kind, sources, observed_count.
- Re-refresh — observed_count rebuild, không increment. Status sticky:
  pending stays pending; rejected stays rejected.

**Unit — auto-mapping:**
- `on_accept_hq` — Accept DIENTRO khi có 50/129 NB rows trong materials →
  50 code_mappings rows tạo. Idempotent: re-Accept không tạo dup.
- `on_accept_nb` — Accept 019.X khi DIENTRO trong materials → mapping
  (DIENTRO, 019.X) tạo retroactive.
- Order independence: Accept DIENTRO trước rồi 019.X sau vs Accept 019.X
  trước rồi DIENTRO sau → cùng kết quả mapping cuối.
- `on_accept_unified` (Johnson) — không tạo mapping (skip bidirectional logic).

**Integration:**
- POST `/clients/growatt-vn/catalog/candidates/<id>/accept` với form data →
  303 + materials row + auto-mappings.
- POST `/.../reject` với optional reason → 303 + candidate.status='rejected'.
- POST `/.../unreject` → 303 + candidate.status='pending'.
- Feed page render: assert filter chips work (kind, source, hint).

**Manual UI smoke:**
1. Login `admin@data-hub.local`.
2. Navigate `/clients/growatt-vn/catalog/candidates`.
3. Verify mix of NB + HQ candidates with kind chips.
4. Accept HQ candidate (DIENTRO) → materials grows + code_mappings populated.
5. Accept NB candidate → materials grows + retroactive mapping.
6. Reject candidate → disappears, in "Đã từ chối" section.
7. Un-reject → reappears.
8. Filter by kind=NB → only NB rows.
9. Navigate `/clients/johnson-vn/catalog/candidates` → all kind='Unified'.
10. Screenshot all states → commit to `.ai/features/2026-05-09-ma-cho-duyet/screenshots/`.

## Done criteria

- mig 047 applied; mig 043 + catalog_derive code deleted; tests green
  (~644 → adjust for removed catalog_derive tests + new candidates tests).
- Feed lists ≥1 code from each stream on Growatt fixture data.
- Accept inserts material with correct source + status.
- Reject persists; un-reject removes.
- Screenshots committed showing populated feed + accept + reject + un-reject.
- BACKLOG entry deleted; STATUS.md "Next Steps" advances to item #2.

## Effort

~1-1.5 days as estimated in BACKLOG. Single mig + single route module + single
template + replaces existing wizard. No cross-cut refactor.

## Next step

Confirm 3 open questions below via AskUserQuestion → write tests first
(per `/tdd` workflow, modest TDD: schema mig + key extract logic + accept/reject
endpoints) → implement → UI smoke → commit.
