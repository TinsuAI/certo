"""BCCT product-identity parser adapter registry.

Each adapter encapsulates one client's strategy for extracting candidate
BOM product codes from a BCCT row (typically by parsing `goods_name`).

Contract:

    name:           str                      — stable machine code (e.g. 'growatt_bcct')
    parser_version: str                      — bumped on rule change
    parse_candidates(row: dict) -> list[CandidateExtraction]
                                             — pure; returns ranked candidate
                                               codes with provenance metadata.

A `CandidateExtraction` is a dict shape:

    {
      "product_code":  str,                  — extracted token
      "source_field":  str,                  — e.g. 'goods_name'
      "matched_text":  str,                  — verbatim slice from source_field
      "match_rule":    str,                  — short identifier of the rule that fired
    }

Resolver validates each candidate against same-client `bom_artifacts.product_code`.
"""
from __future__ import annotations

from typing import Iterable, Protocol


class BcctIdentityAdapter(Protocol):
    name: str
    parser_version: str

    def parse_candidates(self, row: dict) -> list[dict]: ...


_REGISTRY: dict[str, BcctIdentityAdapter] = {}


def register(adapter: BcctIdentityAdapter) -> None:
    if not adapter.name:
        raise ValueError("adapter.name required")
    _REGISTRY[adapter.name] = adapter


def resolve(name: str | None) -> BcctIdentityAdapter | None:
    if not name:
        return None
    return _REGISTRY.get(name)


def adapter_names() -> list[str]:
    return list(_REGISTRY.keys())


def adapter_for_client(client_id: str, code_resolution_mode: str | None) -> BcctIdentityAdapter:
    """Pick an adapter for a client. Mirrors the dispatch convention of
    `internal_code_parser_for` (app/parsers/goods_name.py): mode
    'identity' → identity adapter; everything else → Growatt adapter.

    Today the Growatt adapter is the only goods-name extractor we have.
    Real Growatt clients carry mode='batch_aggregate_resolution', not
    literal 'growatt' — so a literal-equality check would silently miss
    them (and silently miss the spec golden case). Flipping the default
    matches the existing convention and is safe because the regex
    excludes non-Growatt-shape codes (`MFW0513-02` etc don't match).

    Future agencies with new goods-name shapes register a new adapter
    here and add a dispatch case BEFORE the Growatt fallback."""
    mode = (code_resolution_mode or "").lower()
    if mode == "identity":
        return _REGISTRY["identity"]
    return _REGISTRY["growatt_bcct"]


# Eager import + register builtin adapters.
from app.parsers.bcct_adapters.identity import IdentityBcctAdapter  # noqa: E402
from app.parsers.bcct_adapters.growatt import GrowattBcctAdapter    # noqa: E402

register(IdentityBcctAdapter())
register(GrowattBcctAdapter())
