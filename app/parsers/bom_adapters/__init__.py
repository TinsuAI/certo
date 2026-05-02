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


_REGISTRY: dict[str, BomAdapter] = {}
_LEGACY_ALIASES: dict[str, str] = {
    # Old name → new neutral name. Kept indefinitely so cached profile
    # selections + dev-DB pending uploads continue resolving.
    "growatt_multi_workbook": "sheet_per_product",
    "johnson_sap_exploded":   "sap_exploded_levels",
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


def parse_with_fallback(
    blob: bytes, *,
    root_code: str | None = None,
) -> tuple[dict[str, list[dict]], str] | None:
    """Try every adapter in registration order. Return (products, name)
    of the first one that yields a non-empty parse, or None.

    `root_code` is an optional hint (typically the filename stem) used by
    adapters whose source format doesn't carry the root product code in
    the workbook itself (e.g. SAP indented walks). Adapters that don't
    care about it ignore the kwarg.
    """
    last_err: Exception | None = None
    for adapter in _REGISTRY.values():
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
