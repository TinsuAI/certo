"""BOM parser adapter registry.

Each adapter encapsulates one workbook-shape strategy. Drop a new module
in this directory and call `register(YourAdapter)` at import time to
make a new BOM format available — no changes to routes/templates needed.

Adapter contract (Python `Protocol` compatible):

    name:                  str   — stable machine code, used in DB + URLs.
    label_key:             str   — i18n key for short UI label.
    description_key:       str   — i18n key for longer description.
    supports_mapping_override: bool   — whether this adapter honours
                                        an LLM-confirmed column mapping.
    parse(blob, *, mapping_override=None) -> dict[str, list[dict]]
                                  — raises BomParseError on failure;
                                    returns dict keyed by product_code.

Why the format-name change:
- Old keys (`growatt_multi_workbook`, `johnson_sap_exploded`) hardcoded
  customer names. New keys describe the workbook STRUCTURE
  (`sheet_per_product`, `sap_exploded_levels`, `manual_flat`) so the
  same adapter can be reused for any agency that uploads that shape.
- Backward-compat aliases keep old DB rows + URLs working.
"""
from __future__ import annotations

from typing import Iterator, Protocol


class BomParseError(RuntimeError):
    pass


class BomAdapter(Protocol):
    name: str
    label_key: str
    description_key: str
    supports_mapping_override: bool

    # Phase 3c. Identifier strings naming post-ingest hooks the
    # runner should invoke after a raw artifact commits. Resolved
    # via the module-level `HOOKS` map. Default: empty list (no
    # hooks). Adapters that expose deep raw graphs whose
    # intermediate parent_code values are real BTPs (sap_indented_walk,
    # multi_sheet_per_root) declare ['derive_btp_shallows'] so that
    # per-BTP own raw_graph artifacts get minted automatically.
    post_ingest_hooks: list[str]

    # When False, the adapter treats the workbook as a single rooted
    # explosion tree — intermediate parent codes are computational
    # artifacts, not standalone BTP products. The parser pre-multiplies
    # qty through ancestor chains and emits ONE entry per (root → leaf)
    # occurrence under a single root key. Engine then materializes ONE
    # FlattenedVersion per root with no intermediate BTP versions.
    #
    # When True (default), the adapter emits a multi-product parsed dict
    # where each parent code becomes a candidate BTP version (current
    # behavior — appropriate for manual_flat / sheet_per_product where
    # each product is a stable, reusable BOM in its own right).
    #
    # Sources where it should be False:
    #   - SAP-indented exports (Johnson) — sub-assemblies are explosion
    #     intermediates, not separate products
    #   - Per-product workbooks split across sheets (Growatt PV*.XLSX)
    #     — sheet boundaries are organizational, not BTP boundaries
    emits_intermediate_btp_versions: bool

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None
              ) -> dict[str, list[dict]]: ...

    # A confidence in [0, 1] that THIS adapter is the right one for `blob`,
    # or None to abstain. Used by parse_with_fallback to rank candidates ahead
    # of plain registration order: adapters that return a positive score are
    # tried before abstaining ones. High-precision only — return a positive
    # score solely on unambiguous structural markers (e.g. an explicit Level
    # column). A new adapter SHOULD implement detect() as its extension point;
    # an explicit `return None` abstains (keeps registration order). The runner
    # (_safe_detect) also tolerates a missing method for backward-compat.
    def detect(self, blob: bytes, *, root_code: str | None = None
               ) -> float | None: ...


_REGISTRY: dict[str, BomAdapter] = {}
_LEGACY_ALIASES: dict[str, str] = {
    # Old name → new neutral name. Kept indefinitely so cached profile
    # selections + dev-DB pending uploads continue resolving.
    "growatt_multi_workbook": "sheet_per_product",
    "johnson_sap_exploded":   "sap_exploded_levels",
    # Raw-edge parsers in `app/parsers/bom_edges.py` use their own
    # adapter names (parse_raw_edges_with_fallback). For
    # `run_post_ingest_hooks` to find the right hooks, alias them
    # to the closest registered adapter so the same SAP / Growatt
    # post-ingest behaviour applies whether the upload route went
    # through the flat-rows path or the raw-edges path.
    "sap_indented_raw":          "sap_indented_walk",
    "growatt_factory_technical": "multi_sheet_per_root",
}


def register(adapter: BomAdapter) -> None:
    if not adapter.name:
        raise ValueError("adapter.name required")
    _REGISTRY[adapter.name] = adapter


def resolve(name: str) -> BomAdapter | None:
    return _REGISTRY.get(_LEGACY_ALIASES.get(name, name))


def adapter_names() -> list[str]:
    """Names in stable iteration order — first one is the default."""
    return list(_REGISTRY.keys())


def adapters() -> Iterator[BomAdapter]:
    return iter(_REGISTRY.values())


def registry_info() -> list[dict]:
    """Describe registered adapters for the read-only admin registry view (B.0).
    Pure metadata read — no parsing. Order = registration order = the fallback
    order used by parse_with_fallback when no detect() score discriminates."""
    legacy: dict[str, list[str]] = {}
    for old, new in _LEGACY_ALIASES.items():
        legacy.setdefault(new, []).append(old)
    out: list[dict] = []
    for idx, a in enumerate(_REGISTRY.values()):
        out.append({
            "name": a.name,
            "order": idx,
            "label_key": getattr(a, "label_key", ""),
            "description_key": getattr(a, "description_key", ""),
            "supports_mapping_override":
                bool(getattr(a, "supports_mapping_override", False)),
            "emits_intermediate_btp_versions":
                bool(getattr(a, "emits_intermediate_btp_versions", False)),
            "post_ingest_hooks": list(getattr(a, "post_ingest_hooks", []) or []),
            "has_detect": callable(getattr(a, "detect", None)),
            "legacy_aliases": sorted(legacy.get(a.name, [])),
        })
    return out


def parse_with(
    blob: bytes, *,
    name: str,
    mapping_override: dict[str, str] | None = None,
    root_code: str | None = None,
) -> dict[str, list[dict]]:
    adapter = resolve(name)
    if adapter is None:
        raise BomParseError(f"Unknown BOM adapter: {name}")
    return _call_adapter(adapter, blob,
                         mapping_override=mapping_override, root_code=root_code)


def _safe_detect(adapter: BomAdapter, blob: bytes,
                 root_code: str | None) -> float | None:
    """Call adapter.detect() defensively. Missing method or any error →
    None (abstain). Pass root_code only if the signature accepts it."""
    import inspect
    fn = getattr(adapter, "detect", None)
    if not callable(fn):
        return None
    try:
        kwargs: dict = {}
        if "root_code" in inspect.signature(fn).parameters:
            kwargs["root_code"] = root_code
        score = fn(blob, **kwargs)
    except Exception:  # noqa: BLE001
        return None
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _ranked_adapters(blob: bytes, root_code: str | None) -> list[BomAdapter]:
    """Order adapters for fallback: those returning a positive detect()
    score first (highest score wins; registration order breaks ties),
    then every abstaining adapter in registration order. When no adapter
    scores, the result equals registration order — i.e. a no-op vs. the
    prior behaviour."""
    scored: list[tuple[float, int, BomAdapter]] = []
    rest: list[tuple[int, BomAdapter]] = []
    for idx, adapter in enumerate(_REGISTRY.values()):
        score = _safe_detect(adapter, blob, root_code)
        if score is not None and score > 0:
            scored.append((score, idx, adapter))
        else:
            rest.append((idx, adapter))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [a for _, _, a in scored] + [a for _, a in rest]


def parse_with_fallback(
    blob: bytes, *,
    root_code: str | None = None,
) -> tuple[dict[str, list[dict]], str] | None:
    """Try adapters in detect-ranked order (see _ranked_adapters). Return
    (products, name) of the first one that yields a non-empty parse, or
    None.

    `root_code` is an optional hint (typically the filename stem) used by
    adapters whose source format doesn't carry the root product code in
    the workbook itself (e.g. SAP indented walks). Adapters that don't
    care about it ignore the kwarg.
    """
    last_err: Exception | None = None
    for adapter in _ranked_adapters(blob, root_code):
        try:
            products = _call_adapter(adapter, blob, root_code=root_code)
            if products:
                return products, adapter.name
        except BomParseError as e:
            last_err = e
            continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    return None


def _call_adapter(adapter: BomAdapter, blob: bytes, *,
                  mapping_override: dict[str, str] | None = None,
                  root_code: str | None = None,
                  ) -> dict[str, list[dict]]:
    """Invoke adapter.parse(); pass root_code only if the signature
    accepts it (avoids forcing every adapter to declare the kwarg)."""
    import inspect
    sig = inspect.signature(adapter.parse)
    kwargs: dict = {}
    if "mapping_override" in sig.parameters:
        kwargs["mapping_override"] = mapping_override
    if "root_code" in sig.parameters:
        kwargs["root_code"] = root_code
    return adapter.parse(blob, **kwargs)


# Eager import + register builtin adapters. New adapters added in this
# directory must also be imported here (or via __init__.py side-effect).
from app.parsers.bom_adapters.manual_flat import ManualFlatAdapter             # noqa: E402
from app.parsers.bom_adapters.sheet_per_product import SheetPerProductAdapter  # noqa: E402
from app.parsers.bom_adapters.sap_exploded_levels import SapExplodedLevelsAdapter  # noqa: E402
from app.parsers.bom_adapters.sap_indented_walk import SapIndentedWalkAdapter  # noqa: E402
from app.parsers.bom_adapters.multi_sheet_per_root import MultiSheetPerRootAdapter  # noqa: E402

# Registration order matters for parse_with_fallback. Single-root
# adapters first (more discriminating); generic adapters last.
register(SapIndentedWalkAdapter())     # filename = root, Level + indented
register(MultiSheetPerRootAdapter())   # one rooted tree across sheets
register(ManualFlatAdapter())          # generic per-product
register(SheetPerProductAdapter())     # sheet title = product
register(SapExplodedLevelsAdapter())   # explicit Level + product code


# ─────────────────────────────────────────────────────────────────────
# Phase 3c — Post-ingest hooks
# ─────────────────────────────────────────────────────────────────────
# `HOOKS` maps hook identifier → callable. Each callable's signature
# is (*, artifact_id: str, client_id: str, **kwargs) → list[dict].
# Adapters declare which hooks run after their ingest via
# `post_ingest_hooks`. The runner is `run_post_ingest_hooks()`.
#
# Wired into the upload-confirm flow at app/routes/bom.py: after each
# artifact is created, run_post_ingest_hooks() fires for the active
# adapter. Hook failures get logged + mark the artifact stale with
# dim='derive_hook_failed'; never bubble to the user.

def _derive_btp_shallows_hook(*, artifact_id: str, client_id: str, **kwargs):
    """Bridge to scripts/derive_btp_shallows.py (lazy import to avoid
    circular dependency with app.stores.bom)."""
    from scripts.derive_btp_shallows import (
        _client_policy, derive_btp_shallows_for_artifact,
    )
    from app.database import connect
    with connect() as conn, conn.cursor() as cur:
        policy = _client_policy(cur, client_id)
    status = {"disabled": "disabled", "draft_only": "draft",
              "publish": "publish"}.get(policy, "draft")
    return derive_btp_shallows_for_artifact(
        artifact_id=artifact_id, client_id=client_id, status=status,
    )


def _materialize_shapes_hook(*, artifact_id: str, client_id: str, **kwargs):
    """Materialize shallow + full_flat for any published raw_graph in
    this client that doesn't yet have shapes attached. Catches up the
    just-uploaded TP and any BTP raw_graphs minted by the prior
    derive_btp_shallows hook in the same chain. Idempotent."""
    from scripts.materialize_shallow_and_full_flat import (
        list_raw_artifacts_missing_shapes, materialize_one,
        fetch_client_policy,
    )
    policy = fetch_client_policy(client_id)
    if policy == "disabled":
        return []
    publish = policy == "publish"
    out = []
    for raw_id, product_code, variant, ctx, _hash in (
        list_raw_artifacts_missing_shapes(client_id)
    ):
        counters = materialize_one(
            raw_id, product_code, variant, ctx,
            client_id=client_id, publish=publish,
        )
        out.append({"raw_artifact_id": raw_id, "product_code": product_code,
                    **counters})
    return out


HOOKS: dict[str, callable] = {
    "derive_btp_shallows": _derive_btp_shallows_hook,
    "materialize_shapes":  _materialize_shapes_hook,
}


def run_post_ingest_hooks(
    *, adapter_name: str, artifact_id: str, client_id: str, **kwargs,
) -> list:
    """Invoke each declared post-ingest hook for the named adapter.
    Unknown adapters are a no-op (defensive). Each hook's return value
    is appended to the aggregated result."""
    adapter = resolve(adapter_name)
    if adapter is None:
        return []
    out: list = []
    for hook_name in (getattr(adapter, "post_ingest_hooks", None) or []):
        fn = HOOKS.get(hook_name)
        if fn is None:
            continue
        result = fn(artifact_id=artifact_id, client_id=client_id, **kwargs)
        if result is not None:
            out.extend(result)
    return out


# Patch existing adapters to declare empty hooks by default; deep-tree
# adapters get derive_btp_shallows. We do this via attribute set so
# adapter classes don't all need a duplicate definition.
def _set_hooks(name: str, hooks: list[str]):
    a = resolve(name)
    if a is None:
        return
    setattr(a, "post_ingest_hooks", hooks)


_set_hooks("manual_flat",          ["materialize_shapes"])
_set_hooks("sheet_per_product",    ["materialize_shapes"])
_set_hooks("sap_exploded_levels",  ["derive_btp_shallows", "materialize_shapes"])
_set_hooks("sap_indented_walk",    ["derive_btp_shallows", "materialize_shapes"])
_set_hooks("multi_sheet_per_root", ["derive_btp_shallows", "materialize_shapes"])
