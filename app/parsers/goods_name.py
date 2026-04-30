"""Per-DNCX parsers extracting internal_code from BCCT 'Tên hàng' field.

Growatt regex inherited verbatim from `bcqt-growatt/settlement/load.py`.
For other DNCXs (and non-Growatt mode), default to identity (internal_code = customs_code).
"""
from __future__ import annotations

import re
from typing import Callable, Optional


# Growatt regexes (verbatim from bcqt-growatt/settlement/load.py)
_PAT_F1 = re.compile(r'\((\d{3}\.\w+|[A-Z]{2,}\d{2}\.\w+)\)\s*$')
_PAT_F3 = re.compile(r'^([A-Z0-9][A-Z0-9a-z. _\-]+?)#&')
_PAT_F4 = re.compile(r'^\.\s*#&')


def growatt_parse_internal_code(goods_name: str) -> Optional[str]:
    """Extract internal code from Tên hàng. Returns None if equipment/no code."""
    if not goods_name:
        return None
    s = str(goods_name).strip()
    m1 = _PAT_F1.search(s)
    if m1:
        return m1.group(1)
    m4 = _PAT_F4.match(s)
    if m4:
        return None
    m3 = _PAT_F3.match(s)
    if m3:
        return m3.group(1)
    return None


_GROWATT_DNCX_TOKENS = ("growatt", "grw")


def internal_code_parser_for(dncx_id: str, code_resolution_mode: str) -> Callable[[str], Optional[str]]:
    """Return a parser callable: goods_name -> internal_code | None.

    Identity mode: returns lambda that maps any goods_name to None — caller falls back to customs_code.
    batch_aggregate_resolution + dncx looks like growatt: use Growatt regex.
    Other DNCXs in simple_mapping: heuristic — try Growatt regex (it covers a few common shapes),
    fall back to None (caller uses customs_code as fallback).
    """
    if code_resolution_mode == "identity":
        return lambda _: None
    lower = (dncx_id or "").lower()
    if any(tok in lower for tok in _GROWATT_DNCX_TOKENS):
        return growatt_parse_internal_code
    return growatt_parse_internal_code  # default — extension hook for additional DNCXs
