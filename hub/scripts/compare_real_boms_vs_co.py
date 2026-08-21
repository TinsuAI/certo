"""Process every real Growatt + Johnson BOM workbook through the Data
Hub flatten engine and compare leaf-by-leaf with CO's reference output.

Inputs:
  Growatt source: ~/workspace/client/barry-CO-data/extracted/CO/
                  bom-supplier-zips/by-company/GROWATT/from-bom-15-01/
                  supplemental/PV*.XLSX, DV*.XLSX     (39 files)
  Johnson source: ~/workspace/client/barry-CO-data/extracted/CO/
                  bom-supplier-zips/by-company/JOHNSON/from-bom-20260423/
                  technical/MFW*.XLSX                  (82 files)

CO reference output:
  Growatt:        ~/workspace/client/barry-CO-main/data/derived/CO/
                  bom-flatten/growatt-priority/per-code/<code>.json
  Johnson:        ~/workspace/client/barry-CO-main/data/derived/CO/
                  bom-aggregate/johnson/from-bom-20260423/
                  leaf-component-rollup.csv

Output:
  data/screenshots/_compare_report.json    machine-readable per-product
                                            stats + diffs
  data/screenshots/_compare_report.md      human-readable summary
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import openpyxl

from hub.app.flatten import flatten as flatten_engine
from hub.app.flatten.types import CatalogEntry, FlattenContext, ParsedBom
from hub.app.parsers import bom_adapters


GROWATT_SRC = Path(
    os.path.expanduser(
        "~/workspace/client/barry-CO-data/extracted/CO/"
        "bom-supplier-zips/by-company/GROWATT/from-bom-15-01/supplemental/"
    )
)
JOHNSON_SRC = Path(
    os.path.expanduser(
        "~/workspace/client/barry-CO-data/extracted/CO/"
        "bom-supplier-zips/by-company/JOHNSON/from-bom-20260423/technical/"
    )
)
GROWATT_REF_PER_CODE = Path(
    os.path.expanduser(
        "~/workspace/client/barry-CO-main/data/derived/CO/"
        "bom-flatten/growatt-priority/per-code/"
    )
)
JOHNSON_REF_ROLLUP = Path(
    os.path.expanduser(
        "~/workspace/client/barry-CO-main/data/derived/CO/"
        "bom-aggregate/johnson/from-bom-20260423/leaf-component-rollup.csv"
    )
)
OUT_JSON = Path(__file__).resolve().parent.parent / "data" / "screenshots" / "_compare_report.json"
OUT_MD = Path(__file__).resolve().parent.parent / "data" / "screenshots" / "_compare_report.md"


def _graph_pure_ctx(parsed: ParsedBom, client_id: str = "compare") -> FlattenContext:
    """Graph-pure context — mimics CO's behavior: ANY code that doesn't
    have its own BOM in the upload is treated as a leaf material.
    Data Hub's spec-strict default would require explicit catalog evidence
    (category=nvl + status=active) before classifying as leaf and would
    otherwise produce 'unresolved'. For raw graph-vs-CO comparison we
    want the same topological behavior — leaf iff no children.

    The mock catalog returns an active NVL CatalogEntry for every code
    NOT present as a key in parsed (i.e. has no child BOM in the upload).
    """
    parsed_keys = set(parsed.keys())

    def catalog_pure(material_code: str):
        if material_code in parsed_keys:
            return None    # has its own BOM → not a leaf
        return CatalogEntry(
            material_code=material_code,
            category="nvl", status="active", uom=None,
        )

    return FlattenContext(
        client_id=client_id,
        catalog=catalog_pure,
        bcct_import=lambda m: False,
        same_upload_btp=lambda m, b, v: None,
        current_db_btp=lambda m, b, v: None,
        uom=lambda m, f, t: None,
        explicit_context=lambda r: None,
    )


def parse_johnson_indented(blob: bytes, *, root_code: str) -> ParsedBom:
    """Parse a Johnson SAP indented-explosion workbook into the
    {parent_code: [{material_code, qty_per_unit, uom, ...}, ...]} shape.

    Johnson workbooks have:
      - One sheet (`Sheet1`).
      - Filename stem = root product code (e.g. MFW0502-39).
      - Columns include: Phantom item, Bulk Material, Explosion level
        ('.1'/'.2'/...), Level (numeric depth), Component number,
        Comp. Qty (CUn), Object description, Item Number.
      - Each row's Level indicates depth; the parent of a row at level N
        is the most recent row at level N-1 (or root_code at level 1).
      - Phantom items (col Phantom item == 'X') ARE structural BTP
        groupings; we keep them as parents because their children roll up
        through them.

    Output shape matches the manual_flat parser.
    """
    wb = openpyxl.load_workbook(blob if isinstance(blob, str) else
                                io_buf(blob), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}
    header = [str(c or "").strip().lower() for c in rows[0]]

    def col(*needles) -> int | None:
        for needle in needles:
            for i, h in enumerate(header):
                if h == needle.lower():
                    return i
        return None

    c_level = col("level")
    c_comp  = col("component number", "componentnumber")
    c_qty   = col("comp. qty (cun)", "comp qty (cun)", "comp. qty (cun)",
                  "comp. qty(cun)", "comp qty cun", "component quantity")
    c_unit  = col("component unit", "uom", "unit", "comp. unit")
    c_phantom = col("phantom item")
    if c_level is None or c_comp is None or c_qty is None:
        return {}

    products: dict[str, list[dict]] = {root_code: []}
    parent_stack: list[str] = [root_code]   # index = level - 1
    last_level = 0

    for r in rows[1:]:
        if not r or all(c is None or c == "" for c in r):
            continue
        level_raw = r[c_level]
        try:
            level = int(level_raw) if level_raw is not None else None
        except (TypeError, ValueError):
            try:
                level = int(float(level_raw))
            except (TypeError, ValueError):
                level = None
        if level is None or level < 1:
            continue
        comp = r[c_comp]
        if comp is None or str(comp).strip() == "":
            continue
        comp = str(comp).strip()
        try:
            qty = float(r[c_qty]) if r[c_qty] is not None else 0.0
        except (TypeError, ValueError):
            qty = 0.0
        unit = str(r[c_unit]).strip() if c_unit is not None and r[c_unit] else None

        # Adjust parent stack to current depth.
        while len(parent_stack) > level:
            parent_stack.pop()
        parent = parent_stack[-1] if parent_stack else root_code

        # Append this row as a child of `parent`.
        products.setdefault(parent, []).append({
            "material_code": comp,
            "qty_per_unit": qty,
            "uom": unit,
            "bom_code": None,
            "bom_variant_id": None,
        })

        # Push self for potential children at level+1.
        if len(parent_stack) == level:
            parent_stack.append(comp)
        else:
            # Equal depth: replace last entry.
            parent_stack[level:] = [comp]
        last_level = level

    # Drop empty buckets.
    return {k: v for k, v in products.items() if v}


def io_buf(blob: bytes):
    import io
    return io.BytesIO(blob)


def parse_one(path: Path, *, johnson: bool = False) -> ParsedBom | None:
    """Parse via the registry, passing filename stem as root_code hint
    so sap_indented_walk can use it. (johnson kwarg kept for backward-
    compat with old callers; the adapter registry now handles routing.)"""
    blob = path.read_bytes()
    result = bom_adapters.parse_with_fallback(blob, root_code=path.stem)
    if result is None:
        return None
    products, _name = result
    return products


def flatten_one(parsed: ParsedBom) -> dict:
    """Return: {root_product_code: {leaf_code: total_qty}}.

    Root products are the workbook's top-level keys whose code is NOT
    referenced as a child in any other product's rows. (Same heuristic
    CO uses: the top of the tree.)
    """
    if not parsed:
        return {}
    referenced: set[str] = set()
    for pc, rows in parsed.items():
        for r in rows:
            mat = (r.get("material_code") or "").strip()
            if mat:
                referenced.add(mat)
    roots = [pc for pc in parsed.keys() if pc not in referenced]
    # Edge case: every code is referenced (cycle) or workbook is one
    # tall sheet — fall back to first parsed code.
    if not roots:
        roots = list(parsed.keys())[:1]

    result = flatten_engine(parsed, _graph_pure_ctx(parsed))
    out: dict[str, dict[str, Decimal]] = {}
    for v in result.versions:
        if v.key.product_code not in roots:
            continue
        if v.flatten_status == "non_flattened":
            # Still record so we can flag in the report.
            out.setdefault(v.key.product_code, {"_status": "non_flattened",
                                                 "_unresolved": len(v.unresolved)})
        leaf_qty: dict[str, Decimal] = {}
        for r in v.rows:
            cur = leaf_qty.get(r.material_code, Decimal(0))
            leaf_qty[r.material_code] = cur + (r.qty if isinstance(r.qty, Decimal) else Decimal(str(r.qty)))
        existing = out.get(v.key.product_code, {})
        existing.update({k: v_ for k, v_ in leaf_qty.items()})
        out[v.key.product_code] = existing
    return out


# ─── CO reference loaders ───────────────────────────────────────────────

def load_growatt_ref(code: str) -> dict[str, Decimal] | None:
    """Load CO's per-code flatten JSON. Returns {leaf_code: total_qty}
    or None if missing."""
    path = GROWATT_REF_PER_CODE / f"{code}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    leaf_qty: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for row in data.get("rows", []):
        leaf = row["leafComponentCode"]
        leaf_qty[leaf] += Decimal(str(row.get("quantity") or 0))
    return dict(leaf_qty)


_johnson_cache: dict[str, dict[str, Decimal]] | None = None


def load_johnson_ref() -> dict[str, dict[str, Decimal]]:
    """One-shot load: {export_product_code: {component_number: qty}}."""
    global _johnson_cache
    if _johnson_cache is not None:
        return _johnson_cache
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal(0)))
    with JOHNSON_REF_ROLLUP.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            export = row["exportProductCode"]
            comp = row["componentNumber"]
            qty = Decimal(str(row.get("calculatedQuantity") or 0))
            out[export][comp] += qty
    _johnson_cache = {k: dict(v) for k, v in out.items()}
    return _johnson_cache


# ─── Comparison ─────────────────────────────────────────────────────────

def compare_one(*, dh_leaves: dict[str, Decimal],
                co_leaves: dict[str, Decimal],
                qty_tolerance: Decimal = Decimal("0.005")) -> dict:
    """Compare two {leaf: qty} dicts. Returns counts + sample mismatches."""
    dh_set = set(dh_leaves.keys()) - {"_status", "_unresolved"}
    co_set = set(co_leaves.keys())
    only_dh = sorted(dh_set - co_set)
    only_co = sorted(co_set - dh_set)
    common = dh_set & co_set

    qty_match = 0
    qty_mismatch: list[dict] = []
    for leaf in sorted(common):
        dh_q = dh_leaves[leaf]
        co_q = co_leaves[leaf]
        # Relative tolerance — CO's rounding/aggregation behavior may
        # differ slightly. Treat 0.5% delta as "match".
        if co_q == 0:
            ok = abs(dh_q) <= qty_tolerance
        else:
            ok = abs(dh_q - co_q) / abs(co_q) <= qty_tolerance
        if ok:
            qty_match += 1
        elif len(qty_mismatch) < 5:
            qty_mismatch.append({
                "leaf": leaf, "dh": str(dh_q), "co": str(co_q),
            })
    return {
        "n_dh_leaves": len(dh_set),
        "n_co_leaves": len(co_set),
        "n_common_leaves": len(common),
        "n_only_in_dh": len(only_dh),
        "n_only_in_co": len(only_co),
        "n_qty_match_within_tol": qty_match,
        "qty_mismatch_samples": qty_mismatch,
        "only_in_dh_sample": only_dh[:5],
        "only_in_co_sample": only_co[:5],
        "leaf_set_overlap_pct": (
            round(100 * len(common) / max(len(dh_set | co_set), 1), 1)
        ),
    }


def main():
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    overall = {
        "growatt": {"workbooks": [], "summary": {}},
        "johnson": {"workbooks": [], "summary": {}},
    }

    # ── Growatt ──
    growatt_files = sorted(GROWATT_SRC.glob("*.XLSX")) + sorted(GROWATT_SRC.glob("*.xlsx"))
    print(f"Growatt: {len(growatt_files)} workbooks")
    for path in growatt_files:
        code_from_filename = path.stem
        try:
            parsed = parse_one(path)
        except Exception as e:
            overall["growatt"]["workbooks"].append({
                "file": path.name,
                "error": f"parse: {type(e).__name__}: {e}",
            })
            continue
        if not parsed:
            overall["growatt"]["workbooks"].append({
                "file": path.name, "error": "no parse result"})
            continue
        try:
            dh_out = flatten_one(parsed)
        except Exception as e:
            overall["growatt"]["workbooks"].append({
                "file": path.name,
                "error": f"flatten: {type(e).__name__}: {e}",
            })
            continue

        # Pick the root product whose code matches the filename if present.
        root = None
        for pc in dh_out.keys():
            if pc == code_from_filename:
                root = pc
                break
        if root is None and dh_out:
            root = next(iter(dh_out.keys()))

        co_leaves = load_growatt_ref(root) if root else None
        record = {
            "file": path.name,
            "root_product": root,
            "n_parsed_products": len(parsed),
            "n_dh_root_leaves": len([k for k in dh_out.get(root, {}) if not k.startswith("_")]),
            "ref_present": co_leaves is not None,
        }
        if co_leaves and root:
            cmp = compare_one(
                dh_leaves=dh_out[root], co_leaves=co_leaves,
            )
            record["compare"] = cmp
        overall["growatt"]["workbooks"].append(record)
        print(f"  {path.name}: {record['n_dh_root_leaves']} dh leaves"
              f"{' vs CO ref' if co_leaves else ' [no CO ref]'}")

    # ── Johnson ──
    johnson_files = sorted(JOHNSON_SRC.glob("*.XLSX")) + sorted(JOHNSON_SRC.glob("*.xlsx"))
    print(f"\nJohnson: {len(johnson_files)} workbooks")
    johnson_ref_all = load_johnson_ref()
    for path in johnson_files:
        code_from_filename = path.stem
        try:
            parsed = parse_one(path, johnson=True)
        except Exception as e:
            overall["johnson"]["workbooks"].append({
                "file": path.name,
                "error": f"parse: {type(e).__name__}: {e}",
            })
            continue
        if not parsed:
            overall["johnson"]["workbooks"].append({
                "file": path.name, "error": "no parse result"})
            continue
        try:
            dh_out = flatten_one(parsed)
        except Exception as e:
            overall["johnson"]["workbooks"].append({
                "file": path.name,
                "error": f"flatten: {type(e).__name__}: {e}",
            })
            continue

        root = code_from_filename if code_from_filename in dh_out else (
            next(iter(dh_out.keys())) if dh_out else None
        )
        co_leaves = johnson_ref_all.get(root) if root else None
        record = {
            "file": path.name,
            "root_product": root,
            "n_parsed_products": len(parsed),
            "n_dh_root_leaves": len([k for k in dh_out.get(root, {}) if not k.startswith("_")]),
            "ref_present": co_leaves is not None,
        }
        if co_leaves and root:
            cmp = compare_one(
                dh_leaves=dh_out[root], co_leaves=co_leaves,
            )
            record["compare"] = cmp
        overall["johnson"]["workbooks"].append(record)
        print(f"  {path.name}: {record['n_dh_root_leaves']} dh leaves"
              f"{' vs CO ref' if co_leaves else ' [no CO ref]'}")

    # ── Summary ──
    for tag in ("growatt", "johnson"):
        wbs = overall[tag]["workbooks"]
        n_total = len(wbs)
        n_parse_err = sum(1 for w in wbs if w.get("error"))
        n_with_ref = sum(1 for w in wbs if w.get("ref_present"))
        cmps = [w["compare"] for w in wbs if "compare" in w]
        n_full_overlap = sum(1 for c in cmps if c["leaf_set_overlap_pct"] == 100.0)
        avg_overlap = (
            round(sum(c["leaf_set_overlap_pct"] for c in cmps) / max(len(cmps), 1), 1)
            if cmps else 0.0
        )
        n_qty_perfect = sum(
            1 for c in cmps
            if c["n_common_leaves"] > 0
            and c["n_qty_match_within_tol"] == c["n_common_leaves"]
        )
        overall[tag]["summary"] = {
            "n_workbooks": n_total,
            "n_parse_error": n_parse_err,
            "n_with_co_reference": n_with_ref,
            "n_compared": len(cmps),
            "n_full_leaf_set_overlap": n_full_overlap,
            "avg_leaf_set_overlap_pct": avg_overlap,
            "n_qty_match_perfect_among_common": n_qty_perfect,
        }

    OUT_JSON.write_text(json.dumps(overall, indent=2, default=str))

    # Markdown summary.
    lines: list[str] = ["# DH flatten vs CO reference — comparison report\n"]
    for tag in ("growatt", "johnson"):
        s = overall[tag]["summary"]
        lines += [
            f"## {tag.capitalize()}",
            "",
            f"- Workbooks scanned: **{s['n_workbooks']}**",
            f"- Parse errors: {s['n_parse_error']}",
            f"- With CO reference output: {s['n_with_co_reference']}",
            f"- Compared head-to-head: **{s['n_compared']}**",
            f"- Workbooks with 100% leaf-set overlap with CO: **{s['n_full_leaf_set_overlap']} / {s['n_compared']}**",
            f"- Average leaf-set overlap: **{s['avg_leaf_set_overlap_pct']}%**",
            f"- Workbooks where every common leaf matches qty within 0.5%: **{s['n_qty_match_perfect_among_common']} / {s['n_compared']}**",
            "",
            "### Per-workbook detail",
            "",
            "| File | Root | DH leaves | CO leaves | Overlap % | Qty-match (common) |",
            "|------|------|-----------|-----------|-----------|--------------------|",
        ]
        for w in overall[tag]["workbooks"]:
            if w.get("error"):
                lines.append(f"| {w['file']} | — | — | — | ERROR: {w['error']} | — |")
                continue
            cmp_ = w.get("compare")
            if not cmp_:
                lines.append(
                    f"| {w['file']} | {w.get('root_product') or '?'} | "
                    f"{w.get('n_dh_root_leaves', 0)} | (no ref) | — | — |"
                )
                continue
            lines.append(
                f"| {w['file']} | {w['root_product']} | "
                f"{cmp_['n_dh_leaves']} | {cmp_['n_co_leaves']} | "
                f"{cmp_['leaf_set_overlap_pct']}% | "
                f"{cmp_['n_qty_match_within_tol']}/{cmp_['n_common_leaves']} |"
            )
        lines.append("")

    OUT_MD.write_text("\n".join(lines))
    print(f"\nReports written:\n  {OUT_JSON}\n  {OUT_MD}")


if __name__ == "__main__":
    main()
