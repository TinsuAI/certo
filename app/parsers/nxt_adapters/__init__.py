"""NXT (Nhập-Xuất-Tồn) parser adapter registry.

Same plugin shape as `app/parsers/bom_adapters` — drop a module in this
directory, call `register(YourAdapter)` at import time, and a new NXT source
format becomes available with no route/template changes. Every adapter maps
INTO the canonical line shape documented in `_common.ALIASES`.

Adapter contract (Protocol):
    name: str                         — stable machine code (DB + URLs).
    label_key / description_key: str  — i18n keys for the UI.
    supports_mapping_override: bool   — honours an LLM-confirmed column mapping.
    detect(blob) -> float | None      — confidence in [0,1] or None to abstain.
    parse(blob, *, mapping_override=None) -> list[dict]
                                      — canonical lines; raises NxtParseError.
"""
from __future__ import annotations

from typing import Iterator, Protocol


class NxtParseError(RuntimeError):
    pass


class NxtAdapter(Protocol):
    name: str
    label_key: str
    description_key: str
    supports_mapping_override: bool

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]: ...

    def detect(self, blob: bytes) -> float | None: ...


_REGISTRY: dict[str, NxtAdapter] = {}


def register(adapter: NxtAdapter) -> None:
    if not adapter.name:
        raise ValueError("adapter.name required")
    _REGISTRY[adapter.name] = adapter


def resolve(name: str) -> NxtAdapter | None:
    return _REGISTRY.get(name)


def adapter_names() -> list[str]:
    return list(_REGISTRY.keys())


def adapters() -> Iterator[NxtAdapter]:
    return iter(_REGISTRY.values())


def registry_info() -> list[dict]:
    """Metadata for the read-only admin registry view. Order = registration
    order = fallback order when no detect() score discriminates."""
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


def _safe_detect(adapter: NxtAdapter, blob: bytes) -> float | None:
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


def _ranked_adapters(blob: bytes) -> list[NxtAdapter]:
    scored: list[tuple[float, int, NxtAdapter]] = []
    rest: list[tuple[int, NxtAdapter]] = []
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
        raise NxtParseError(f"Unknown NXT adapter: {name}")
    return adapter.parse(blob, mapping_override=mapping_override)


def parse_with_fallback(blob: bytes) -> tuple[list[dict], str] | None:
    """Try adapters in detect-ranked order; return (lines, adapter_name) of the
    first that yields a non-empty parse, or None."""
    for adapter in _ranked_adapters(blob):
        try:
            lines = adapter.parse(blob)
            if lines:
                return lines, adapter.name
        except Exception:  # noqa: BLE001
            continue
    return None


# Eager import + register builtin adapters. Order = fallback order when no
# detect() score discriminates; high-precision (distinctive sheet/header) first.
from app.parsers.nxt_adapters.ezsoft_3tsoft import Ezsoft3TSoftAdapter  # noqa: E402
from app.parsers.nxt_adapters.sap_mb5b import SapMb5bAdapter  # noqa: E402
from app.parsers.nxt_adapters.misa_can_doi_ton import MisaCanDoiTonAdapter  # noqa: E402
from app.parsers.nxt_adapters.system_template import SystemTemplateNxtAdapter  # noqa: E402
from app.parsers.nxt_adapters.manual_generic import ManualGenericNxtAdapter  # noqa: E402

register(Ezsoft3TSoftAdapter())       # distinctive "EZSOFT - 3TSoft" sheet
register(SapMb5bAdapter())            # SAP MB5B snake_case header signature
register(MisaCanDoiTonAdapter())      # MISA "CÂN ĐỐI TỒN KHO" merged header
register(SystemTemplateNxtAdapter())  # canonical NVL/TP/BTP template
register(ManualGenericNxtAdapter())   # last-resort alias/override fallback
