from __future__ import annotations

from app.supplier_identity import supplier_key


def declaration_type_counts(stock_rows: list[dict]) -> dict[str, int]:
    """BCCT import-row count per declaration_type, from the materialized
    co_stock snapshot. Aggregated lots weigh as their source line count so the
    numbers match the raw BCCT regardless of lot_policy."""
    counts: dict[str, int] = {}
    for row in stock_rows or []:
        declaration_type = str(row.get("declaration_type") or "").strip() or "?"
        counts[declaration_type] = counts.get(declaration_type, 0) + _row_weight(row)
    return dict(sorted(counts.items()))


def excluded_types_with_rows(counts: dict[str, int], eligible_types: list[str] | None) -> list[tuple[str, int]]:
    """Declaration types present in the client's BCCT data but absent from a
    non-empty eligible list — the config mistake that produces false shortages.
    An empty list means no filter, so nothing is excluded."""
    eligible = [str(item).strip().upper() for item in (eligible_types or []) if str(item).strip()]
    if not eligible:
        return []
    return [
        (declaration_type, count)
        for declaration_type, count in (counts or {}).items()
        if declaration_type != "?" and declaration_type.upper() not in eligible
    ]


def supplier_type_summary(stock_rows: list[dict]) -> list[dict]:
    """Per-supplier BCCT aggregation for the curation screen (ticket #11) and
    shared with the config-form counts: one entry per supplier_key with the raw
    name(s) seen, row count, per-declaration-type counts, and origin mix."""
    by_key: dict[str, dict] = {}
    for row in stock_rows or []:
        name = str(row.get("consignee_name") or "").strip()
        key = supplier_key(name)
        if not key:
            continue
        entry = by_key.setdefault(key, {
            "supplier_key": key,
            "names": [],
            "row_count": 0,
            "type_counts": {},
            "origin_counts": {},
        })
        if name and name not in entry["names"]:
            entry["names"].append(name)
        weight = _row_weight(row)
        entry["row_count"] += weight
        declaration_type = str(row.get("declaration_type") or "").strip() or "?"
        entry["type_counts"][declaration_type] = entry["type_counts"].get(declaration_type, 0) + weight
        origin = str(row.get("origin_country") or "").strip() or "?"
        entry["origin_counts"][origin] = entry["origin_counts"].get(origin, 0) + weight
    return sorted(by_key.values(), key=lambda entry: (-entry["row_count"], entry["supplier_key"]))


def _row_weight(row: dict) -> int:
    source_line_ids = row.get("source_line_ids")
    if isinstance(source_line_ids, list) and source_line_ids:
        return len(source_line_ids)
    return 1
