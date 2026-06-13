# CO consumer spec — adopt DH `customs_relevance` for bảng kê (rich path)

**Audience:** CO (`barry-CO-main` / TinsuAI/co). **Producer:** Data Hub (mig 078).
**Carry this into a CO session** — DH is audit-only from DH sessions, so the CO
edits below happen in the CO repo, not here.
**DH contract refs:** `docs/API_CHANGELOG.md` (2026-06-09 Additive),
`.ai/sister-app-notes/2026-06-09-bom-row-exclusion-and-material-group.md`,
investigation `.ai/features/2026-06-08-leaf-nvl-declarability/brief.md`.

## Why

CO already drops "only-in-technical-BOM" rows from the bảng kê via
`app/origin_material_filters.py::is_bom_technical_noise()` — a **heuristic**:
`bom_source=='technical_flattened' AND no hs_code AND no allocation`. That guess
**conflates two very different things** and under-declares: it drops genuine
imported materials (steel cut-pieces, welding-rod variants) as "noise" — its own
docstring even lists `"Tube;Round;45#"` as droppable, but that is a real
non-originating material that belongs on the C/O sheet.

DH now ships the authoritative split so CO can stop guessing. **Keep the
classification in DH; CO consumes it. Do NOT re-implement RD-code logic in CO.**

## Decision: rich path (read fields), default `exclude_non_declarable=false`

CO does **not** use the server-side row filter. It keeps the batch default
(`exclude_non_declarable` unset/false → DH returns every row) and branches on the
per-material `customs_relevance`. This keeps CO transparent (it can show *why* a
row was dropped) and lets it treat `declarable_unmatched` correctly instead of
silently dropping it.

## The contract CO reads

From `GET /v1/hub/materials` (CO already calls this — `data_hub_client.list_materials`/`get_material`),
each material now carries (additive):
- `customs_relevance` ∈ `excluded_non_material` | `declarable` | `declarable_unmatched` | `review` | `null`
- `item_category` (nature: drawing/label/metal/…), `material_group` (raw SAP).

Per BOM row (batch/single), additive: `excluded_at`, `exclusion_reason`, and
payload `material_group`/`phantom`/`bulk`. CO's decision is **material-level**
(`customs_relevance`), so the row fields are optional/diagnostic.

**Import wins (mig 079):** any material with a BCCT import line is `declarable`
regardless of Material Group — DH never classifies a genuinely-imported material
as rác. So `excluded_non_material` = **non-imported documents + labels** (+ phantom
rows). Drawings live in the overloaded SAP group RD07 (mixed with real "Set/Semi-
Assy"); they are **not** auto-excluded — a non-imported drawing surfaces as
`declarable_unmatched` for review (precise drawing auto-hide is a DH follow-up).

Meaning → required CO behavior:

| `customs_relevance` | what it is | bảng kê EXPORT | web sheet |
|---|---|---|---|
| `excluded_non_material` | non-imported document / label (+ phantom rows via `excluded_at`) | **exclude** (LVC-neutral) | collapse/flag "phi vật tư" |
| `declarable` | material **with** a BCCT import match (import wins over MG) | **emit** normally | normal |
| `declarable_unmatched` | physical material / drawing / set, **no** import match (steel cut-piece, welding variant, RD07 drawings & sets) | **exclude from export BUT flag** — cannot emit a no-HS/no-CIF line | **⚠ "cần đối soát"** review bucket — distinct from noise |
| `review` / `null` | unmapped MG / not classified | treat as needs-attention | flag; never silently drop |

The behavior change vs today: `declarable_unmatched` must be shown as a
**reconciliation queue**, not lumped into "noise". The C/O still can't declare it
until it gets HS+import evidence (Phase 2), but operators must SEE it.

## Exact CO edits

### 1. `app/origin_material_filters.py` — replace the heuristic
```python
_EXPORT_EXCLUDE = {"excluded_non_material", "declarable_unmatched"}

def is_bom_technical_noise(material: dict) -> bool:
    """Exclude from C/O exports. With DH mig 078+ this is authoritative;
    falls back to the legacy heuristic for older Data Hub."""
    cr = str(material.get("customs_relevance") or "").strip()
    if cr:
        # excluded_non_material = true rác (drawings/labels/docs).
        # declarable_unmatched = real material we can't yet declare (no HS/CIF)
        #   -> still excluded from EXPORT, but surfaced via is_declarable_unmatched.
        return cr in _EXPORT_EXCLUDE
    # Back-compat: Data Hub without customs_relevance.
    return (
        str(material.get("bom_source") or "") == "technical_flattened"
        and not str(material.get("hs_code") or "").strip()
        and not (material.get("allocation_lines") or [])
    )

def is_declarable_unmatched(material: dict) -> bool:
    """Real, declarable-class material with no BCCT import match — belongs on
    the bảng kê but can't be emitted until reconciled. Show as a review queue,
    NOT as noise. (Legacy DH: best-effort false.)"""
    return str(material.get("customs_relevance") or "").strip() == "declarable_unmatched"
```

### 2. Web sheet — split the flag (`app/web/co_case_context.py:~2467`)
Today: `enriched["bom_technical_noise"] = is_bom_technical_noise(enriched)`.
Add a second flag so the UI can render two buckets:
```python
enriched["bom_technical_noise"] = is_bom_technical_noise(enriched)
enriched["declarable_unmatched"] = is_declarable_unmatched(enriched)
```
Render `excluded_non_material` rows as "phi vật tư (loại)" and
`declarable_unmatched` rows as "⚠ vật tư chưa khớp — cần đối soát".

### 3. Ensure `customs_relevance` reaches the enriched material dict
`is_bom_technical_noise` reads `material[...]`. Verify the enrichment that builds
that dict carries `customs_relevance`/`item_category` through from
`list_materials`/`get_material` (it should if CO spreads material fields; if it
allow-lists keys, add `customs_relevance`, `item_category`, `material_group`).

### 4. Export call sites (no logic change — they already gate on the function)
`workbook_io.py:611`, `bang_ke_xml_generator.py:391`, `bang_ke_renderer.py:259`
all do `if override.get("deleted") or is_bom_technical_noise(material): continue`
— they inherit the new behavior for free.

### 5. Recommended export guard (correctness)
Before emitting a C/O, if any kept material `is_declarable_unmatched`, **warn or
block** (don't issue a C/O that silently under-declares). Surface a count:
"N vật tư chưa khớp tờ khai — đối soát trước khi phát hành."

## Tests (CO side)
- Update `tests/test_technical_noise_filter.py`: a row with
  `customs_relevance='excluded_non_material'` → noise=True; `declarable_unmatched`
  → noise=True (export-excluded) **and** `is_declarable_unmatched`=True;
  `declarable` → noise=False; legacy row (no `customs_relevance`) → old heuristic.
- Add a case proving a steel/welding row (`declarable_unmatched`) is **no longer
  silently classified as plain noise** (gets the review flag).

## Rollout / rollback
1. DH deploys (default-off → **zero CO impact** until CO ships this).
2. CO ships the field-reading change; verify against johnson-vn real data in
   staging (compare bảng kê before/after — drawings still gone, steel/welding now
   in the review bucket).
3. Backward compatible: older DH (no `customs_relevance`) → legacy heuristic path,
   unchanged.
4. Rollback: revert the CO function (heuristic). No DH change needed.

## Ownership
Misclassification (a code in the wrong bucket) is fixed in **DH** by editing one
row of `hub.client_material_group_map` — no CO deploy, no CO code. CO must never
hardcode `material_group == 'RDxx'`.

## Phase 2 (separate, shared)
Resolving `declarable_unmatched` (cut-piece→bulk-customs-code, welding-rod
variant) needs a DH reconciliation surface (cross-language name/HS match) + a CO
"declare aggregated under bulk parent" path + domain input. Do not block the rác
win on it.
