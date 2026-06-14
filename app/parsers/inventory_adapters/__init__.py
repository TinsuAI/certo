"""Year-end inventory snapshot parser adapter registry.

Same plugin shape as `app/parsers/nxt_adapters`. Every adapter maps INTO the
canonical snapshot line shape documented in `_common.ALIASES`.
"""
from __future__ import annotations

from typing import Iterator, Protocol


class InventoryParseError(RuntimeError):
    pass


class InventoryAdapter(Protocol):
    name: str
    label_key: str
    description_key: str
    supports_mapping_override: bool

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]: ...

    def detect(self, blob: bytes) -> float | None: ...


_REGISTRY: dict[str, InventoryAdapter] = {}


def register(adapter: InventoryAdapter) -> None:
    if not adapter.name:
        raise ValueError("adapter.name required")
    _REGISTRY[adapter.name] = adapter


def resolve(name: str) -> InventoryAdapter | None:
    return _REGISTRY.get(name)


def adapter_names() -> list[str]:
    return list(_REGISTRY.keys())


def adapters() -> Iterator[InventoryAdapter]:
    return iter(_REGISTRY.values())


def registry_info() -> list[dict]:
    out: list[dict] = []
    for idx, a in enumerate(_REGISTRY.values()):
        out.append({
            "name": a.name,
            "order": idx,
            "label_key": getattr(a, "label_key", ""),
            "description_key": getattr(a, "description_key", ""),
            "supports_mapping_override":
                bool(getattr(a, "supports_mapping_override", False)),
            "has_detect": callable(getattr(a, "detect", None)),
        })
    return out


def _safe_detect(adapter: InventoryAdapter, blob: bytes) -> float | None:
    fn = getattr(adapter, "detect", None)
    if not callable(fn):
        return None
    try:
        score = fn(blob)
    except Exception:  # noqa: BLE001
        return None
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _ranked_adapters(blob: bytes) -> list[InventoryAdapter]:
    scored: list[tuple[float, int, InventoryAdapter]] = []
    rest: list[tuple[int, InventoryAdapter]] = []
    for idx, adapter in enumerate(_REGISTRY.values()):
        score = _safe_detect(adapter, blob)
        if score is not None and score > 0:
            scored.append((score, idx, adapter))
        else:
            rest.append((idx, adapter))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [a for _, _, a in scored] + [a for _, a in rest]


def parse_with(blob: bytes, *, name: str,
               mapping_override: dict[str, str] | None = None) -> list[dict]:
    adapter = resolve(name)
    if adapter is None:
        raise InventoryParseError(f"Unknown inventory adapter: {name}")
    return adapter.parse(blob, mapping_override=mapping_override)


def parse_with_fallback(blob: bytes) -> tuple[list[dict], str] | None:
    for adapter in _ranked_adapters(blob):
        try:
            lines = adapter.parse(blob)
            if lines:
                return lines, adapter.name
        except Exception:  # noqa: BLE001
            continue
    return None


from app.parsers.inventory_adapters.system_template import (  # noqa: E402
    SystemTemplateInventoryAdapter,
)

register(SystemTemplateInventoryAdapter())
