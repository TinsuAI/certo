"""Pure extraction logic for catalog candidates (Mã chờ duyệt).

Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md (D2, D3, D3b).

Per-row classification handles 4 BCCT cases:
  1. dual (NB != HQ) — emit (hq,'hq') + (nb,'nb') for each NB
  2. unified (NB == HQ overlap) — emit (hq,'unified') only
  3. HQ only (no paren match) — emit (hq, 'hq' if dual_system else 'unified')
  4. NB only (customs_code empty or a client placeholder) — emit (nb,'nb')
     for each NB. Placeholder strings come from
     `hub.clients.customs_code_placeholders` (mig 090), loaded by callers.

The BOM and code_mappings discovery streams live in SQL
(hub.catalog_discovery, mig 092) — only the BCCT regex extraction
needs Python.

These helpers are deliberately stateless; DB lookups happen in the store
layer (app/stores/bcct_nb_codes.py) and route layer.
"""
from __future__ import annotations

from typing import Collection

from hub.app.parsers.client_parser_rules import (
    CompiledRule, extract_all_matches_from_compiled,
)


CodeKind = str  # 'nb' | 'hq' | 'unified'
Candidate = tuple[str, CodeKind]


def _is_missing_hq(value: str | None, placeholders: Collection[str]) -> bool:
    """Treat None, empty, whitespace, and the client's configured placeholder
    strings (hub.clients.customs_code_placeholders, e.g. Growatt's '.') as
    missing."""
    if value is None:
        return True
    s = value.strip()
    return s == "" or s in placeholders


def candidates_from_bcct_row(
    row: dict,
    *,
    rules: list[CompiledRule],
    has_dual_system: bool,
    placeholders: Collection[str],
) -> list[Candidate]:
    """Classify a single BCCT row into 0..N candidate (code, kind) tuples.

    Args:
      row: dict with keys 'customs_code' and 'goods_name' at minimum.
      rules: precompiled internal_code parser rules. Empty list when client
             doesn't have rules (Johnson-shape).
      has_dual_system: client-level flag — true when client has rules OR
                       code_mappings rows. Affects HQ-only case.
      placeholders: the client's customs_code placeholder strings; a
                    customs_code equal to one of them counts as missing.

    Returns:
      List of (code, kind) tuples. Order: HQ before NB. Empty if row is noise.
    """
    hq_raw = row.get("customs_code")
    hq = None if _is_missing_hq(hq_raw, placeholders) else (hq_raw or "").strip()

    nbs: list[str] = []
    if rules:
        matches = extract_all_matches_from_compiled(rules, row=row)
        for m in matches:
            code = (m.get("product_code") or "").strip()
            if code and code not in nbs:
                nbs.append(code)

    if hq is None and not nbs:
        return []

    # Case 2: NB == HQ overlap → single 'unified' candidate
    if hq is not None and hq in nbs:
        return [(hq, "unified")]

    # Case 1: dual (HQ + 1+ NBs, all distinct from HQ)
    if hq is not None and nbs:
        return [(hq, "hq")] + [(nb, "nb") for nb in nbs if nb != hq]

    # Case 3: HQ only, no paren match
    if hq is not None and not nbs:
        kind = "hq" if has_dual_system else "unified"
        return [(hq, kind)]

    # Case 4: NB only (no HQ)
    return [(nb, "nb") for nb in nbs]
