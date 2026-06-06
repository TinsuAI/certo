"""sap_indented_walk — SAP indented-explosion workbook (Johnson-style).

Each workbook contains the COMPLETE explosion of one finished product:
  - Filename stem = root product code (e.g. MFW0502-39)
  - One sheet, with columns: Phantom item, Bulk Material, Explosion level
    ('.1', '.2', ...), Level (numeric depth), Item Number, Component number,
    Comp. Qty (CUn), Object description, ...
  - Each row's Level encodes parent-child indent. The parent of a row at
    level N is the most recent row at level N-1; the parent of a level-1
    row is the root.

Same component code may appear at multiple positions in the tree (under
different ancestor chains). The graph-flatten engine merges these by
material code and double-counts. To avoid that, this adapter is
`emits_intermediate_btp_versions=False`: we walk the workbook linearly,
multiply qty through the ancestor chain, and emit ONE row per leaf
occurrence under a single root key. Each emitted row carries
`explicit_context='do_not_explode'` so the engine treats it as a
terminal leaf without re-recursing.

The detection heuristic: the workbook has a `Level` column AND a
`Component number` column AND no `成品物料`/`product code`/`mã sp`
column at the parent header level. (If a `product_code` column exists,
the file is sap_exploded_levels — that adapter handles it.)
"""
from __future__ import annotations

import io
from collections import defaultdict
from decimal import Decimal

from app.parsers.bom_adapters._common import COMMON_ALIASES


_LEVEL_ALIASES = ["level", "lvl", "cấp", "explosion level"]
_COMPONENT_ALIASES = ["component number", "componentnumber", "component code", "mã nvl"]
_QTY_ALIASES = [
    # MENGE/XMENG = per-immediate-parent. MUST win over MNGKO
    # ("Comp. Qty (CUn)") which is cumulative through ancestors.
    "component quantity", "required quantity", "qty",
    "comp. qty (cun)", "comp qty (cun)", "comp.qty(cun)", "comp qty cun",
]
_UNIT_ALIASES = ["component unit", "uom", "unit", "comp. unit", "base unit of measure"]
_DESCRIPTION_ALIASES = [
    "object description", "description", "material description",
    "component description", "tên hàng", "ten hang", "mô tả", "mo ta",
    "物料描述", "物料名称",
]
# If any of these alias-as-product-code matches, this is NOT a Johnson-style
# indented file — defer to a different adapter.
_PRODUCT_CODE_ALIASES = ["成品物料", "product code", "mã sp", "ma sp",
                         "thành phẩm", "parent code"]


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _col_index(header: list[str], aliases: list[str]) -> int | None:
    """First column whose normalized value matches any alias."""
    norm = [_norm(h) for h in header]
    for alias in aliases:
        a = alias.lower()
        for i, h in enumerate(norm):
            if h == a:
                return i
    return None


class SapIndentedWalkAdapter:
    name = "sap_indented_walk"
    label_key = "bom.adapter.sap_indented_walk.label"
    description_key = "bom.adapter.sap_indented_walk.desc"
    supports_mapping_override = False
    emits_intermediate_btp_versions = False

    def detect(self, blob: bytes, *,
               root_code: str | None = None) -> float | None:
        """High-precision: positive only when the first row has a Level +
        Component column AND no product_code column (the same markers
        parse() keys on). Scored slightly above sap_exploded_levels so an
        indented Johnson-style workbook prefers this walker. Abstain on
        anything else (e.g. a file with a product_code column → that's
        sap_exploded_levels' job)."""
        try:
            import openpyxl
            wb = openpyxl.load_workbook(
                io.BytesIO(blob), data_only=True, read_only=True)
        except Exception:  # noqa: BLE001
            return None
        try:
            ws = wb.worksheets[0]
            first = next(ws.iter_rows(values_only=True), None)
        finally:
            wb.close()
        if not first:
            return None
        header = [str(c or "").strip() for c in first]
        if _col_index(header, _PRODUCT_CODE_ALIASES) is not None:
            return None
        if (_col_index(header, _LEVEL_ALIASES) is not None
                and _col_index(header, _COMPONENT_ALIASES) is not None):
            return 0.95
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None,
              root_code: str | None = None,
              ) -> dict[str, list[dict]]:
        """Walk the indented BOM. `root_code` is normally injected by the
        upload route from the filename stem; if absent, falls back to a
        sentinel ('__root__') so the engine still has something to key on.
        """
        from app.parsers.bom_adapters import BomParseError
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        except Exception as e:
            raise BomParseError(f"Cannot open workbook: {e}") from e

        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            raise BomParseError("Empty workbook")

        header = [str(c or "").strip() for c in rows[0]]

        # Reject if this looks like sap_exploded_levels (has product_code).
        if _col_index(header, _PRODUCT_CODE_ALIASES) is not None:
            raise BomParseError("Has product_code column — not SAP indented")

        c_level = _col_index(header, _LEVEL_ALIASES)
        c_comp = _col_index(header, _COMPONENT_ALIASES)
        c_qty = _col_index(header, _QTY_ALIASES)
        c_unit = _col_index(header, _UNIT_ALIASES)
        c_desc = _col_index(header, _DESCRIPTION_ALIASES)
        if c_level is None or c_comp is None or c_qty is None:
            raise BomParseError("Missing Level / Component / Qty columns")

        # Numeric Level required (not the dotted ExplLvl string).
        # Pre-scan: find a row whose Level column parses as int >= 1.
        sample_ok = any(
            self._to_int(r[c_level]) is not None and self._to_int(r[c_level]) >= 1
            for r in rows[1:20] if r and len(r) > c_level
        )
        if not sample_ok:
            raise BomParseError("Level column not numeric integers")

        root = root_code or "__root__"

        # Walk: parent_stack[k-1] = parent code at depth k.
        parent_stack: list[tuple[str, Decimal]] = [(root, Decimal(1))]
        # qty_stack[k] = cumulative qty multiplier from root through depth k.
        qty_stack: list[Decimal] = [Decimal(1)]

        leaves: list[dict] = []
        # We don't know yet which rows are leaves vs intermediates. A row
        # is a LEAF iff no subsequent row has a strictly deeper level
        # before the parent_stack pops past it. Easier: emit every row
        # as a candidate leaf with its multiplied qty, then in a second
        # pass drop intermediate rows whose code shows up as a parent
        # for a deeper row.
        all_rows: list[dict] = []   # parsed rows in order

        for r in rows[1:]:
            if not r or all(c is None or c == "" for c in r):
                continue
            level = self._to_int(r[c_level])
            if level is None or level < 1:
                continue
            comp = r[c_comp]
            if comp is None or str(comp).strip() == "":
                continue
            comp_str = str(comp).strip()
            qty = self._to_decimal(r[c_qty])
            unit = (str(r[c_unit]).strip() if c_unit is not None
                    and c_unit < len(r) and r[c_unit] else None)
            desc = (str(r[c_desc]).strip() if c_desc is not None
                    and c_desc < len(r) and r[c_desc] else None)

            # Pop ancestors deeper than this row's level.
            while len(parent_stack) > level:
                parent_stack.pop()
                qty_stack.pop()
            parent_code, _parent_qty = parent_stack[-1]
            cumulative_qty = qty_stack[-1] * qty

            all_rows.append({
                "level": level,
                "material_code": comp_str,
                "qty_per_unit_raw": qty,
                "qty_cumulative": cumulative_qty,
                "uom": unit,
                "description": desc,
                "parent_code": parent_code,
                "ancestor_chain": [pc for pc, _ in parent_stack],
            })

            # Push this row as a potential parent for deeper rows.
            if len(parent_stack) == level:
                parent_stack.append((comp_str, qty))
                qty_stack.append(cumulative_qty)
            else:
                # Same depth: replace last entry (keeps siblings flat).
                parent_stack[level:] = [(comp_str, qty)]
                qty_stack[level:] = [cumulative_qty]

        # Identify leaf rows: rows whose code is NOT a parent for any
        # deeper row immediately following it. The simplest reliable
        # check: a row at index i is a leaf iff the next row (if any)
        # has level <= this row's level (i.e. no row at level+1
        # immediately follows).
        leaf_rows: list[dict] = []
        for i, row in enumerate(all_rows):
            next_level = (
                all_rows[i + 1]["level"] if i + 1 < len(all_rows) else 0
            )
            if next_level > row["level"]:
                # Has children → intermediate, skip.
                continue
            leaf_rows.append({
                "material_code": row["material_code"],
                # Pre-multiplied through ancestor chain.
                "qty_per_unit": float(row["qty_cumulative"]),
                "uom": row["uom"],
                "description": row["description"],
                "bom_code": None,
                "bom_variant_id": None,
                # Tells the engine "do not recurse, this IS a leaf".
                "explicit_context": "do_not_explode",
                # Audit: the path that produced this leaf instance.
                "_node_path": " > ".join([*row["ancestor_chain"],
                                          row["material_code"]]),
                "_qty_raw": str(row["qty_per_unit_raw"]),
            })

        if not leaf_rows:
            raise BomParseError("No leaf rows detected after indented walk")

        return {root: leaf_rows}

    @staticmethod
    def _to_int(v) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None

    @staticmethod
    def _to_decimal(v) -> Decimal:
        if v is None or v == "":
            return Decimal(0)
        if isinstance(v, Decimal):
            return v
        try:
            return Decimal(str(v))
        except Exception:  # noqa: BLE001
            return Decimal(0)
