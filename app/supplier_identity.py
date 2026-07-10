from __future__ import annotations

import re

_WHITESPACE_RUN = re.compile(r"\s+")
_MISSING_PAREN_SPACE = re.compile(r"(?<=\S)\(")


def supplier_key(name: str | None) -> str:
    """Whitespace-only normalization of a BCCT consignee_name (ADR 2026-07-11).

    The single shared supplier identity: the evidence-curation write path and the
    Tính read path must both call this function or flags silently stop matching
    rows. Deliberately NO case folding and NO branch/parent merging — the same
    real supplier under two spellings beyond whitespace is two suppliers.
    """
    text = _WHITESPACE_RUN.sub(" ", str(name or "")).strip()
    return _MISSING_PAREN_SPACE.sub(" (", text)
