"""BOM graph build + cycle detection. Pure."""
from __future__ import annotations

from typing import Iterable

from hub.app.flatten.types import BomKey, ParsedBom


def graph_key_of(row: dict, *, product_code: str | None = None) -> BomKey:
    """Build a BomKey from a row dict, falling back to provided product_code."""
    pc = product_code or row.get("product_code") or row.get("material_code") or ""
    return BomKey(
        product_code=str(pc),
        bom_code=str(row.get("bom_code") or ""),
        bom_variant_id=str(row.get("bom_variant_id") or "default"),
    )


def detect_cycle(
    parsed: ParsedBom,
    start_key: BomKey,
    *,
    resolve_child: callable,
) -> list[str] | None:
    """Iterative DFS. Returns the offending cycle path (list of material_codes)
    if a cycle is reachable from start_key; None otherwise.

    `resolve_child(material_code) -> BomKey | None` returns the graph key of
    the child BOM iff that material has its own BOM in `parsed`. Pass a
    closure that consults same-upload first then returns None to short-circuit.
    """
    # Stack frame: (key, iterator_over_children, path_so_far)
    visiting: set[tuple] = set()
    visited: set[tuple] = set()

    def walk(k: BomKey, path: list[str]) -> list[str] | None:
        kt = k.as_tuple()
        if kt in visiting:
            # Found cycle — return the slice from first occurrence.
            try:
                start = path.index(k.product_code)
                return path[start:] + [k.product_code]
            except ValueError:
                return path + [k.product_code]
        if kt in visited:
            return None
        visiting.add(kt)
        for r in parsed.get(k.product_code, []) or []:
            child_mat = r.get("material_code")
            if not child_mat:
                continue
            child_key = resolve_child(child_mat)
            if child_key is None:
                continue
            cycle = walk(child_key, path + [k.product_code])
            if cycle:
                return cycle
        visiting.remove(kt)
        visited.add(kt)
        return None

    return walk(start_key, [])


def all_keys(parsed: ParsedBom) -> Iterable[BomKey]:
    """Iterate BomKeys for every product in `parsed`. Variant comes from
    the first row's bom_code/bom_variant_id (manual_flat may have multiples;
    the engine preserves them by graph_key)."""
    for product_code, rows in parsed.items():
        if not rows:
            yield BomKey(product_code=product_code)
            continue
        first = rows[0]
        yield BomKey(
            product_code=product_code,
            bom_code=str(first.get("bom_code") or ""),
            bom_variant_id=str(first.get("bom_variant_id") or "default"),
        )
