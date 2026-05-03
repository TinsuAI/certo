"""Inventory historical client data sources for Data Hub intake.

This script deliberately indexes metadata only. It does not copy, move, or
mutate source files from sibling projects.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.parsers.bcct import BcctParseError, parse_bcct_workbook
from app.parsers.bom import BomParseError, parse_bom_workbook
from app.parsers.bom_adapters import adapter_names
from app.parsers.code_mappings import CodeMappingsParseError, parse_code_mappings_workbook
from app.parsers.materials import MaterialsParseError, parse_materials_workbook


DATA_EXTS = {".xls", ".xlsx", ".xlsm", ".csv", ".json"}
EXCEL_EXTS = {".xls", ".xlsx", ".xlsm"}


@dataclass(frozen=True)
class SourceRoot:
    key: str
    path: Path
    notes: str


def client_root() -> Path:
    env = os.environ.get("CLIENT_WORKSPACE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def source_roots(root: Path) -> list[SourceRoot]:
    candidates = [
        SourceRoot("BCQT-System/data", root / "BCQT-System" / "data", "BCQT app project uploads and local project DB data"),
        SourceRoot("BCQT-System/sample-data", root / "BCQT-System" / "sample data", "BCQT sample Growatt files"),
        SourceRoot("BCQT-System/test-uploads", root / "BCQT-System" / "test-uploads", "BCQT test upload corpus"),
        SourceRoot("BCQT-System/tests-fixtures", root / "BCQT-System" / "tests" / "fixtures", "BCQT parser fixture corpus"),
        SourceRoot("bcqt-growatt/data", root / "bcqt-growatt" / "data", "Growatt BCQT raw archive"),
        SourceRoot("bcqt-growatt/output", root / "bcqt-growatt" / "output", "Growatt settlement outputs"),
        SourceRoot("BCQT-DKE/input", root / "BCQT-DKE" / "input", "DKE raw settlement inputs"),
        SourceRoot("BCQT-DKE/output", root / "BCQT-DKE" / "output", "DKE settlement outputs and mapping workbooks"),
        SourceRoot("bcqt-dothanh/data", root / "bcqt-dothanh" / "data", "Do Thanh extracted/raw settlement inputs"),
        SourceRoot("bcqt-dothanh/output", root / "bcqt-dothanh" / "output", "Do Thanh settlement outputs"),
        SourceRoot("Johnson/docs", root / "Johnson" / "docs", "Johnson raw input docs"),
        SourceRoot("Johnson/output", root / "Johnson" / "output", "Johnson cleaned data and settlement outputs"),
        SourceRoot("Johnson/archive", root / "Johnson" / "archive", "Johnson archived inputs/outputs"),
        SourceRoot("barry-CO-data/source", root / "barry-CO-data" / "source", "CO source files"),
        SourceRoot("barry-CO-data/extracted", root / "barry-CO-data" / "extracted", "CO extracted customer folders"),
        SourceRoot("barry-CO-data/cases", root / "barry-CO-data" / "cases", "CO case normalized/results data"),
        SourceRoot("barry-CO-data/derived", root / "barry-CO-data" / "derived", "CO derived reference outputs"),
        SourceRoot("barry-CO-data/reference", root / "barry-CO-data" / "reference", "CO reference tables"),
        SourceRoot("barry-CO-main/temp", root / "barry-CO-main" / "temp", "CO app manual test and temp HQ files"),
        SourceRoot("barry-CO-bom-data/source", root / "barry-CO-bom-data" / "source", "BOM builder source files"),
        SourceRoot("barry-CO-bom-data/extracted", root / "barry-CO-bom-data" / "extracted", "BOM builder extracted data"),
        SourceRoot("barry-CO-bom-data/local", root / "barry-CO-bom-data" / "local", "BOM builder manual/runtime fixtures"),
        SourceRoot("barry/docs/sample-data", root / "barry" / "docs" / "sample-data", "Legacy Barry sample data"),
        SourceRoot("barry-google-app/docs/sample-data", root / "barry-google-app" / "docs" / "sample-data", "Legacy Google app sample data"),
    ]
    return [c for c in candidates if c.path.exists()]


def norm_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def stable_id(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:12]


def infer_client(rel_path: str) -> str:
    s = rel_path.lower()
    if "growatt" in s or "grw" in s or "/pv0" in s or "/pv1" in s:
        return "growatt-vn"
    if "johnson" in s or "/jy" in s or "t13_danh_sach" in s:
        return "johnson-vn"
    if "dke" in s:
        return "dke-vn"
    if "do-thanh" in s or "dothanh" in s or "đô thành" in s:
        return "do-thanh-vietnam-2614"
    if "test_company" in s or "smoke" in s or "demo" in s:
        return "test/demo"
    return "unknown"


def classify_kind(rel_path: str) -> str:
    s = rel_path.lower()
    name = Path(rel_path).name.lower()
    if any(x in s for x in ["code_mapping", "mapping_ma_erp", "bang quy doi", "bảng quy đổi", "bqd"]):
        return "code_mappings"
    if any(x in name for x in ["baocaohangchitiet", "bao cao hang chi tiet", "bcct", "tokhai", "to khai", "q1_bcct"]):
        return "bcct"
    if any(x in name for x in ["ds_npl", "ds npl", "ds_nvl", "ds nvl", "danh muc npl", "danh mục npl",
                               "ma nvl", "mã nvl", "danh muc nvl", "danh mục nvl", "material_master",
                               "danh muc sp", "danh mục sp", "ds_sp", "ds sp", "ma sp", "mã sp",
                               "danh muc tp", "danh mục tp", "danh muc tp - btp"]):
        return "catalog_materials"
    if "bom" in name or "dinh muc" in name or "định mức" in name or "bang tinh ham luong" in name:
        return "bom"
    if any(x in name for x in ["mau_15", "mau 15", "mẫu 15", "mau_15a", "mau 15a", "mau_16", "mau 16",
                               "settlement_forms", "bcqt"]):
        return "settlement_output"
    if any(x in name for x in ["mb51", "mb5b", "nxt", "ton kho", "tồn kho", "stock"]):
        return "inventory_movement"
    if any(x in name for x in ["rvc", "replacement", "scenario", "certificate", "co-stock", "co_stock"]):
        return "co_case_output"
    if "llm" in s or "manual-test" in s or "manual_test" in s or "fixture" in s:
        return "test_fixture"
    if name.endswith(".json"):
        return "config_or_metadata"
    return "unknown"


def initial_feedability(kind: str, ext: str, rel_path: str) -> str:
    s = rel_path.lower()
    if kind in {"bcct", "catalog_materials", "code_mappings", "bom"} and ext in EXCEL_EXTS:
        if any(x in s for x in ["/output/", "/derived/", "/results/", "/archive/output/", "/versions/", "/backup_"]):
            return "possible_generated_excel"
        return "direct_candidate"
    if kind in {"bcct", "catalog_materials", "code_mappings", "bom"} and ext == ".csv":
        return "needs_csv_adapter_or_conversion"
    if kind in {"settlement_output", "inventory_movement", "co_case_output"}:
        return "not_current_data_hub_scope"
    if kind in {"test_fixture", "config_or_metadata"}:
        return "reference_or_test_only"
    return "manual_review"


def probe_excel(path: Path, kind: str) -> tuple[str, str, str]:
    blob = path.read_bytes()
    try:
        if kind == "bcct":
            rows = parse_bcct_workbook(blob)
            return "ok", "bcct", f"rows={len(rows)}"
        if kind == "catalog_materials":
            rows, skipped = parse_materials_workbook(blob)
            extra = f" skipped={len(skipped)}" if skipped else ""
            return "ok", "materials", f"rows={len(rows)}{extra}"
        if kind == "code_mappings":
            rows = parse_code_mappings_workbook(blob)
            return "ok", "code_mappings", f"rows={len(rows)}"
        if kind == "bom":
            errors: list[str] = []
            for profile in adapter_names():
                try:
                    products = parse_bom_workbook(blob, profile=profile)
                except BomParseError as e:
                    errors.append(f"{profile}:{str(e)[:80]}")
                    continue
                n_rows = sum(len(v) for v in products.values())
                return "ok", f"bom:{profile}", f"products={len(products)} rows={n_rows}"
            return "fail", "bom", "; ".join(errors[:3])
    except (BcctParseError, MaterialsParseError, CodeMappingsParseError) as e:
        return "fail", kind, str(e)[:240]
    except Exception as e:  # noqa: BLE001 - inventory should keep going
        return "error", kind, f"{type(e).__name__}: {str(e)[:220]}"
    return "skipped", "", ""


def iter_files(src: SourceRoot):
    skip_parts = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
    for p in src.path.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_parts for part in p.parts):
            continue
        yield p


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/source_inventory")
    parser.add_argument("--no-probe", action="store_true")
    args = parser.parse_args()

    root = client_root()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    root_rows: list[dict] = []
    ext_by_root: dict[str, Counter] = defaultdict(Counter)

    for src in source_roots(root):
        total_size = 0
        total_files = 0
        data_files = 0
        for p in iter_files(src):
            total_files += 1
            size = p.stat().st_size
            total_size += size
            ext = p.suffix.lower()
            ext_by_root[src.key][ext or "<none>"] += 1
            if ext not in DATA_EXTS:
                continue
            data_files += 1
            rel = norm_path(p, root)
            kind = classify_kind(rel)
            client = infer_client(rel)
            feedability = initial_feedability(kind, ext, rel)
            probe_status = "skipped"
            parser_profile = ""
            probe_detail = ""
            if not args.no_probe and feedability in {"direct_candidate", "possible_generated_excel"} and ext in EXCEL_EXTS:
                probe_status, parser_profile, probe_detail = probe_excel(p, kind)
                if probe_status == "ok" and feedability == "direct_candidate":
                    feedability = "direct_feed_ready"
                elif probe_status == "ok":
                    feedability = "parser_ok_but_generated_source"
                elif probe_status in {"fail", "error"} and feedability == "direct_candidate":
                    feedability = "needs_parser_or_mapping"
            manifest.append({
                "id": stable_id(rel),
                "source_root": src.key,
                "client": client,
                "kind": kind,
                "feedability": feedability,
                "ext": ext,
                "size_bytes": size,
                "probe_status": probe_status,
                "parser_profile": parser_profile,
                "probe_detail": probe_detail.replace("\n", " "),
                "path": rel,
            })
        root_rows.append({
            "source_root": src.key,
            "exists": "yes",
            "file_count": total_files,
            "data_file_count": data_files,
            "size_bytes": total_size,
            "notes": src.notes,
            "top_extensions": json.dumps(ext_by_root[src.key].most_common(10), ensure_ascii=False),
        })

    fields = [
        "id", "source_root", "client", "kind", "feedability", "ext",
        "size_bytes", "probe_status", "parser_profile", "probe_detail", "path",
    ]
    write_csv(out / "manifest.csv", manifest, fields)

    feedable = [r for r in manifest if r["feedability"] in {
        "direct_feed_ready", "direct_candidate", "parser_ok_but_generated_source",
        "needs_parser_or_mapping", "needs_csv_adapter_or_conversion",
    }]
    write_csv(out / "feedable_candidates.csv", feedable, fields)

    write_csv(out / "source_roots.csv", root_rows, [
        "source_root", "exists", "file_count", "data_file_count",
        "size_bytes", "notes", "top_extensions",
    ])

    by_client_kind = Counter((r["client"], r["kind"]) for r in manifest)
    by_feed = Counter(r["feedability"] for r in manifest)
    by_kind = Counter(r["kind"] for r in manifest)
    by_probe = Counter(r["probe_status"] for r in manifest)

    lines = [
        "# Source Data Inventory",
        "",
        "Generated by `uv run python scripts/inventory_source_data.py`.",
        "Paths are relative to the client workspace root; raw files were not copied or moved.",
        "",
        "## Totals",
        "",
        f"- Source roots scanned: {len(root_rows)}",
        f"- Data files indexed (`.xls`, `.xlsx`, `.xlsm`, `.csv`, `.json`): {len(manifest)}",
        f"- Feedable candidate rows: {len(feedable)}",
        "",
        "## Feedability",
        "",
    ]
    for k, n in by_feed.most_common():
        lines.append(f"- `{k}`: {n}")
    lines.extend(["", "## Kinds", ""])
    for k, n in by_kind.most_common():
        lines.append(f"- `{k}`: {n}")
    lines.extend(["", "## Probe Status", ""])
    for k, n in by_probe.most_common():
        lines.append(f"- `{k}`: {n}")
    lines.extend(["", "## Client x Kind", ""])
    for (client, kind), n in by_client_kind.most_common(80):
        lines.append(f"- `{client}` / `{kind}`: {n}")
    lines.extend([
        "",
        "## Files",
        "",
        "- `source_roots.csv`: root-level counts and notes.",
        "- `manifest.csv`: all indexed data files with classification.",
        "- `feedable_candidates.csv`: shortlist for Data Hub intake work.",
        "",
    ])
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {out / 'source_roots.csv'}")
    print(f"wrote {out / 'manifest.csv'} ({len(manifest)} rows)")
    print(f"wrote {out / 'feedable_candidates.csv'} ({len(feedable)} rows)")
    print(f"wrote {out / 'README.md'}")


if __name__ == "__main__":
    main()
