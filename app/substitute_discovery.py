"""Stock-first substitute discovery (#2, ADR 2026-07-08).

Build substitute candidates FROM the CO-stock snapshot rather than only from the
Data Hub catalog, so an NVL that is in stock but absent from the catalog is
findable and substitutable. Candidates are grouped at the logical-material grain
(`allocation_code` when resolved, else the declared `customs_item_code`) and
LEFT-JOINed to the catalog for enrichment only.

A stock-sourced candidate is fully declarable: it has a BCCT import match by
construction, so name/HS/value come from the stock lot and `stock_only` (absent
from the catalog) is a DISPLAY flag, never a blocker. See
`.ai/GLOSSARY.md` (declarable_unmatched) and DECISIONS.md (2026-07-08).

Pure and side-effect-free — the route feeds it snapshot rows + a catalog index.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.material_search import fold_text


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def stock_row_keys(row: dict) -> list[str]:
    """The codes under which a lot may be found (mirrors the allocation pool's
    aliasing): material_code, allocation_code, customs_item_code."""
    keys: list[str] = []
    for value in (row.get("material_code"), row.get("allocation_code"), row.get("customs_item_code")):
        key = str(value or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def stock_row_identity(row: dict) -> str:
    """The logical-material grain a substitute is chosen at: the normalised
    `allocation_code` when resolved, else the declared `customs_item_code`."""
    status = str(row.get("allocation_code_status") or "").strip()
    allocation_code = str(row.get("allocation_code") or "").strip()
    if allocation_code and status == "resolved":
        return allocation_code
    return str(row.get("customs_item_code") or row.get("material_code") or allocation_code or "").strip()


def build_stock_first_candidates(
    stock_rows: list[dict],
    catalog_index: dict[str, dict],
    *,
    query: str = "",
    exclude_codes: set[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """Group stock lots into substitute candidates, LEFT-JOIN the catalog, order
    stock-first (most remaining first). `catalog_index` maps any material key to a
    catalog row (name/hs_code/category/customs_relevance)."""
    exclude = {str(code).strip() for code in (exclude_codes or set()) if str(code).strip()}
    # Same rule as `material_search.match_score`: every token must hit the code or
    # the name, accent-insensitively. The old whole-phrase lowercase substring made
    # this list disagree with the catalog search next to it — "bu long" found
    # nothing and "bu lông" missed "Bộ ốc vít, bu lông…" whenever a word sat
    # between the two.
    tokens = fold_text(query).split()

    groups: dict[str, dict] = {}
    for row in stock_rows or []:
        identity = stock_row_identity(row)
        if not identity or identity in exclude:
            continue
        group = groups.get(identity)
        if group is None:
            catalog = None
            for key in stock_row_keys(row):
                if key in catalog_index:
                    catalog = catalog_index[key]
                    break
            group = groups[identity] = {
                "material_code": identity,
                "name": str((catalog or {}).get("name") or row.get("material_description") or "").strip(),
                "hs_code": str((catalog or {}).get("hs_code") or row.get("hs_code") or "").strip(),
                "category": str((catalog or {}).get("category") or "").strip(),
                "customs_relevance": str((catalog or {}).get("customs_relevance") or "").strip(),
                "catalog_matched": catalog is not None,
                "stock_only": catalog is None,
                "kind": "stock",
                "lot_count": 0,
                "_remaining": Decimal("0"),
            }
        group["lot_count"] += 1
        group["_remaining"] += _dec(row.get("remaining_qty") or row.get("available_qty"))

    candidates: list[dict] = []
    for group in groups.values():
        remaining = group.pop("_remaining")
        group["total_remaining_qty"] = str(remaining)
        if tokens:
            haystack = [fold_text(group["material_code"]), fold_text(group["name"])]
            if not all(any(token in field for field in haystack) for token in tokens):
                continue
        candidates.append(group)

    candidates.sort(key=lambda item: (-_dec(item["total_remaining_qty"]), item["material_code"]))
    return candidates[: max(1, limit)]
