# BOM adapters — the extension point

Per-format BOM parsing lives behind the `BomAdapter` Protocol in
`app/parsers/bom_adapters/`. The engine, routes, and declarability logic never
import a specific adapter or branch on `client_id` — extensibility is in
adapters (code, git/CI-governed) and DATA tables (per-client config). This is
the anti-chaos pattern from `DECISIONS.md` (2026-06-09).

The read-only registry is visible at **`/admin/bom-adapters`** (admin/dev).

## Three ways to onboard a new file — pick the smallest

1. **New column names, same structural shape** → DATA, zero code.
   Add rows to `client_column_aliases` at
   `/clients/<id>/column-aliases` (module `bom`). The rigid auto-map resolves
   the client's header variants onto the logical fields.

2. **New SAP Material Group / item-type token** → DATA, zero code.
   Add rows to `client_material_group_map` at
   `/clients/<id>/material-group-map`. Drives `customs_relevance` in
   `hub.v_material_classification` (live). Re-tag stored row exclusions with the
   "chạy lại backfill" button (job kind `material_group_backfill`).

3. **New structural shape** → a new adapter (1 module + tests + deploy).
   This is the only case that needs code. Steps below.

> Do NOT build runtime `.py` upload / hot-add. It is RCE-by-design, bypasses
> CI, and increases chaos. New adapters ship through git/CI like any code.

## Authoring a new adapter

Create `app/parsers/bom_adapters/<shape>.py` with a class implementing the
`BomAdapter` Protocol:

```python
class MyShapeAdapter:
    name = "my_shape"                 # stable machine code (DB + URLs)
    label_key = "bom.adapter.my_shape.label"
    description_key = "bom.adapter.my_shape.desc"
    supports_mapping_override = False  # True if it honours an LLM column mapping
    emits_intermediate_btp_versions = False  # see Protocol docstring
    post_ingest_hooks = []            # e.g. ["derive_btp_shallows", "materialize_shapes"]

    def detect(self, blob: bytes, *, root_code: str | None = None) -> float | None:
        # High-precision only: return a positive score ONLY on an unambiguous
        # structural marker (e.g. an explicit Level column). Else `return None`
        # to abstain (keeps registration-order fallback).
        return None

    def parse(self, blob: bytes, *, mapping_override=None) -> dict[str, list[dict]]:
        # raise BomParseError on failure; return {product_code: [rows...]}.
        ...
```

Register it in `__init__.py` (the eager-import block + `register(...)`).
Registration order is the fallback order when no `detect()` score
discriminates — put single-root/high-precision adapters first.

Add i18n keys (`bom.adapter.my_shape.label` / `.desc`) and tests covering
`detect()` (positive marker + abstain) and `parse()` (happy path + a malformed
file → `BomParseError`). Then deploy.

## Per-client default adapter

`hub.clients.default_bom_adapter` (mig 081) pins one adapter as the upload-form
default for a client. `null` = `auto` (detect-ranked `parse_with_fallback`, the
default). An unregistered stored value degrades to `auto` at read time
(`app/stores/adapter_binding.py`), so removing an adapter never breaks upload.
Set it on the client's BOM upload page; see the matrix at `/admin/bom-adapters`.
