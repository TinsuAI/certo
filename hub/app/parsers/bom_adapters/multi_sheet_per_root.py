"""multi_sheet_per_root — one finished product, exploded across multiple sheets.

Each sheet has manual_flat layout (product/material/qty columns), but the
sheets together describe one product's BOM tree:
  Sheet "整机" (whole machine): rows where parent = root TP code (PV01.0117300),
                                children include sub-assembly codes (B700.*).
  Sheet "B700": rows where parent = sub-assembly code (B700.0241800),
                children include deeper sub-assemblies (B710.*).
  Sheet "B710": rows where parent = deeper sub-assembly, children = NVL leaves.

The intermediate parent codes are NOT standalone BTP products — they're
just organizational containers within one product's exploded BOM. So
this adapter:
  1. Parses every sheet as manual_flat shape, building edge map
     {parent_code: [(child_code, qty, uom), ...]}.
  2. Identifies the single root: a parent_code that NEVER appears as a
     child_code anywhere. If multiple roots exist, REJECTS — this isn't
     a single-rooted file, manual_flat handles those cases.
  3. Walks the tree from the root with explicit per-instance recursion.
     Each parent visit pushes a fresh frame; same-code children inherit
     their position-specific multiplied qty without merging.
  4. Emits ONE row per (root → leaf) occurrence under a single root key
     with `explicit_context='do_not_explode'`.

Result: engine materializes ONE FlattenedVersion per root, no
intermediate BTP versions, no double-counting from code-merging.
"""
from __future__ import annotations

import io
from collections import defaultdict
from decimal import Decimal

from hub.app.parsers.bom_adapters._common import (
    COMMON_ALIASES, cell_num, cell_str, cols_from_override,
)


def _parse_edge_map(blob: bytes) -> tuple[dict[str, list[dict]], set[str]]:
    """Walk every sheet, collect edges (parent → children) into a flat map.
    Returns (edge_map, all_parent_codes)."""
    from hub.app.parsers.bom_adapters import BomParseError
    from hub.app.parsers._excel import header_row, index_headers, iter_data_rows, load_xlsx
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BomParseError(f"Cannot open workbook: {e}") from e

    edges: dict[str, list[dict]] = defaultdict(list)
    parents: set[str] = set()
    for ws in wb.worksheets:
        hdr = header_row(ws, aliases=COMMON_ALIASES)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = index_headers(headers, COMMON_ALIASES)
        if "product_code" not in cols or "material_code" not in cols:
            continue
        for raw in iter_data_rows(ws, header_idx):
            product = cell_str(raw, cols.get("product_code"))
            material = cell_str(raw, cols.get("material_code"))
            if not product or not material:
                continue
            edges[product].append({
                "material_code": material,
                "qty_per_unit": cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                "uom": cell_str(raw, cols.get("uom")),
            })
            parents.add(product)
    return dict(edges), parents


class MultiSheetPerRootAdapter:
    name = "multi_sheet_per_root"
    label_key = "bom.adapter.multi_sheet_per_root.label"
    description_key = "bom.adapter.multi_sheet_per_root.desc"
    supports_mapping_override = False
    emits_intermediate_btp_versions = False

    def detect(self, blob: bytes, *, root_code: str | None = None
               ) -> float | None:
        # No unambiguous structural marker; abstain (registration-order
        # fallback). See parse_with_fallback / _ranked_adapters.
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None,
              root_code: str | None = None,
              ) -> dict[str, list[dict]]:
        from hub.app.parsers.bom_adapters import BomParseError

        edges, parents = _parse_edge_map(blob)
        if not edges:
            raise BomParseError("No BOM edges parsed from workbook")

        # Find roots: parents that never appear as a child anywhere.
        children_set: set[str] = set()
        for parent_rows in edges.values():
            for row in parent_rows:
                children_set.add(row["material_code"])
        roots = [p for p in parents if p not in children_set]

        # Strict: this adapter handles SINGLE-ROOT files only. If there
        # are 0 roots (cycle) or >1 root (multi-product), defer to
        # manual_flat / sheet_per_product / etc.
        if len(roots) != 1:
            raise BomParseError(
                f"Not a single-rooted workbook (found {len(roots)} roots); "
                f"defer to manual_flat"
            )

        # Per /rev finding I1: a single-rooted file with NO intermediate
        # parents (root + only leaves) is a flat manual_flat upload, not
        # a multi-sheet exploded tree. Reject so manual_flat handles it
        # — otherwise we'd mark every row with do_not_explode and lose
        # the engine's ability to classify them as catalog/BCCT leaves.
        intermediates = parents & children_set
        if not intermediates:
            raise BomParseError(
                "Single root with no intermediate parents — flat upload, "
                "defer to manual_flat"
            )

        actual_root = roots[0]
        # Optionally honour the caller's root_code hint as a sanity check;
        # if it disagrees with the detected root, prefer the workbook's
        # internal evidence over the filename.
        if root_code and root_code != actual_root:
            # Filename hint differs — still use workbook root, but record.
            pass

        leaf_rows = _walk_tree(actual_root, edges)
        if not leaf_rows:
            raise BomParseError("Tree walk produced no leaves")

        return {actual_root: leaf_rows}


def _walk_tree(root: str, edges: dict[str, list[dict]]) -> list[dict]:
    """Iterative DFS from root, multiplying qty through each edge.
    Emits one entry per (root → leaf) occurrence. Same-code leaves
    appearing under different ancestor paths produce separate entries
    (preserves multi-instance qty correctness)."""
    leaves: list[dict] = []
    # Stack frames: (current_code, cumulative_qty, ancestor_path)
    # `visiting` set guards against cycles.
    def dfs(code: str, qty_so_far: Decimal, path: list[str], visiting: set[str]):
        if code in visiting:
            # Cycle — bail this branch silently. (Cycle detection at
            # adapter level; engine won't see it because this is
            # pre-flattened.)
            return
        children = edges.get(code)
        if not children:
            # Leaf: emit at the qty multiplied along the path.
            leaves.append({
                "material_code": code,
                "qty_per_unit": float(qty_so_far),
                "uom": None,
                "bom_code": None,
                "bom_variant_id": None,
                "explicit_context": "do_not_explode",
                "_node_path": " > ".join([*path, code]),
            })
            return
        new_visiting = visiting | {code}
        for child_row in children:
            child_qty = Decimal(str(child_row.get("qty_per_unit") or 0))
            child_code = child_row["material_code"]
            sub_qty = qty_so_far * child_qty
            sub_path = [*path, code]
            sub_children = edges.get(child_code)
            if not sub_children:
                # Direct leaf — emit with this child's UOM, not None.
                leaves.append({
                    "material_code": child_code,
                    "qty_per_unit": float(sub_qty),
                    "uom": child_row.get("uom"),
                    "bom_code": None,
                    "bom_variant_id": None,
                    "explicit_context": "do_not_explode",
                    "_node_path": " > ".join([*sub_path, child_code]),
                })
            else:
                dfs(child_code, sub_qty, sub_path, new_visiting)

    dfs(root, Decimal(1), [], set())
    return leaves
