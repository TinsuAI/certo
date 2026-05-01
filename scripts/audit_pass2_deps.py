"""Audit which (parser, header, alias) triples today rely on pass-2 substring
matching. Output: a list of "promote this to explicit pass-1 alias" candidates.

Approach:
- Instrument a copy of `index_headers` that records pass-1 vs pass-2 matches.
- Run every parser against every fixture + real-data file we have.
- Collect every (parser_name, original_header, matched_field, alias_used) tuple
  where the match came from pass 2.
- Print grouped, deduplicated.

Run:
    DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run python scripts/audit_pass2_deps.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

from app.parsers._excel import load_xlsx, header_row, normalize_header

# ─── Instrumented index_headers ────────────────────────────────────────────

PASS2_HITS: list[dict] = []
CURRENT_CONTEXT: dict = {}


def index_headers_audited(headers, aliases):
    """Mirrors app.parsers._excel.index_headers but records pass-2 matches."""
    norm = [normalize_header(h) for h in headers]
    found: dict[str, int] = {}
    claimed: set[int] = set()

    # Pass 1: exact match.
    for field, alts in aliases.items():
        if field in found:
            continue
        for alt in alts:
            target = normalize_header(alt)
            for i, h in enumerate(norm):
                if i in claimed:
                    continue
                if h == target:
                    found[field] = i
                    claimed.add(i)
                    break
            if field in found:
                break

    # Pass 2: substring — record every hit.
    for field, alts in aliases.items():
        if field in found:
            continue
        for alt in alts:
            target = normalize_header(alt)
            for i, h in enumerate(norm):
                if i in claimed:
                    continue
                if target in h or h in target:
                    PASS2_HITS.append({
                        **CURRENT_CONTEXT,
                        "field": field,
                        "header_original": headers[i],
                        "header_norm": h,
                        "alias": alt,
                        "alias_norm": target,
                        "col_idx": i,
                    })
                    found[field] = i
                    claimed.add(i)
                    break
            if field in found:
                break

    return found


# ─── Monkey-patch the parsers to use audited index_headers ─────────────────

import app.parsers._excel as _excel_mod
import app.parsers.bcct as _bcct_mod
import app.parsers.bom as _bom_mod
import app.parsers.code_mappings as _cm_mod
import app.parsers.materials as _mat_mod

_excel_mod.index_headers = index_headers_audited
_bcct_mod.index_headers = index_headers_audited
_bom_mod.index_headers = index_headers_audited
_cm_mod.index_headers = index_headers_audited
_mat_mod.index_headers = index_headers_audited

from app.parsers.bcct import parse_bcct_workbook
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers.code_mappings import parse_code_mappings_workbook, CodeMappingsParseError
from app.parsers.materials import parse_materials_workbook, MaterialsParseError


# ─── Fixture corpus ────────────────────────────────────────────────────────

FIXTURE_ROOT = Path("tests/fixtures")
REAL_ROOT = Path(os.environ.get("DATA_HUB_REAL_DATA_DIR", "/tmp/dh_real_data"))

CASES: list[tuple[str, str, callable, dict]] = []

# BCCT — real data
for rel in [
    "growatt/bcct_nk_2026_t3-t4.xls",
    "growatt/bcct_xk_2026_t3-t4.xls",
    "dke/bcct_2025_official.xls",
    "dothanh/bcct_e31.xls",
    "dothanh/bcct_e62.xls",
]:
    CASES.append(("bcct", str(REAL_ROOT / rel), parse_bcct_workbook, {}))

# BCCT — fixtures
for p in (FIXTURE_ROOT / "manual_test").glob("*.xlsx"):
    CASES.append(("bcct", str(p), parse_bcct_workbook, {}))

# BOM — real data
for rel in ["growatt/bom_tp.xlsx", "growatt/bom_btp.xlsx", "johnson/bom_sap.xlsx"]:
    for prof in ["manual_flat", "growatt_multi_workbook", "johnson_sap_exploded"]:
        CASES.append(("bom", str(REAL_ROOT / rel), parse_bom_workbook, {"profile": prof}))

# BQD — real data
for rel in ["growatt/bqd_tp.xlsx", "growatt/bqd_nvl.xlsx", "dke/bqd.xls"]:
    CASES.append(("bqd", str(REAL_ROOT / rel), parse_code_mappings_workbook, {}))

# Materials (Catalog) — real BCCT-adjacent files won't help, but fixtures will.
for p in (FIXTURE_ROOT / "manual_test").glob("*ds*.xlsx"):  # ds_nvl / ds_sp filename hints
    CASES.append(("catalog", str(p), parse_materials_workbook, {}))


# ─── Run ──────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"Running {len(CASES)} parser invocations...")
    for module, path, fn, kwargs in CASES:
        p = Path(path)
        if not p.exists():
            continue
        CURRENT_CONTEXT.clear()
        CURRENT_CONTEXT.update({"module": module, "file": p.name, "kwargs": kwargs})
        try:
            blob = p.read_bytes()
            fn(blob, **kwargs)
        except (BomParseError, CodeMappingsParseError, MaterialsParseError):
            pass  # Parse error is fine — we still recorded any pass-2 hits before it.
        except Exception as e:
            print(f"  unexpected {type(e).__name__} on {p.name}: {e}", file=sys.stderr)

    if not PASS2_HITS:
        print("\n✓ No pass-2 substring matches found. Drop pass-2 freely.")
        return 0

    # Group by (module, field, alias_norm, header_norm)
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for hit in PASS2_HITS:
        key = (hit["module"], hit["field"], hit["alias_norm"], hit["header_norm"])
        grouped[key].append(hit)

    print(f"\n{len(PASS2_HITS)} pass-2 substring matches across "
          f"{len(grouped)} unique (module, field, alias, header) combos:\n")
    for (module, field, alias_norm, header_norm), hits in sorted(grouped.items()):
        files = sorted({h["file"] for h in hits})
        # Only flag actual semantic substrings, not empty-cell ghosts.
        if not header_norm:
            continue
        print(f"  [{module:8} {field:18}] alias={alias_norm!r:30} header={header_norm!r:35} files={files}")

    # Empty-cell hits separately — these are Bug C ghosts, not aliases to promote.
    empty_hits = [h for h in PASS2_HITS if not h["header_norm"]]
    if empty_hits:
        print(f"\n{len(empty_hits)} empty-cell (Bug C) ghost matches — these are bug evidence, not aliases to add:")
        empty_grouped = defaultdict(int)
        for h in empty_hits:
            empty_grouped[(h["module"], h["field"], h["file"])] += 1
        for (module, field, file), count in sorted(empty_grouped.items()):
            print(f"  [{module:8} {field:18}] file={file:40} count={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
