from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.co_form_psr_index import normalize_hs_scope, seed_psr_rules


DEFAULT_CO_FORM_CONFIG_PATH = "data/local/runtime/co-form-index.json"
_CONFIG_CACHE: dict[str, tuple[tuple[str, int, int], dict]] = {}


def default_co_form_config() -> dict:
    return {
        "schema_version": 1,
        "updated_at": "",
        "source_note": "Seeded from temp/CO-TABLE-FORM.jpg, eCoSys legal-document list, VNTR/MOIT FTA pages, official AIFTA references, and local legal-corpus PSR tables.",
        "form_priority": ["B", "CPTPP", "EUR.1", "AI"],
        "forms": [
            {
                "form_code": "B",
                "display_name": "Form B",
                "agreement": "Không ưu đãi / xuất xứ chung",
                "instrument": "05/2018/TT-BCT; 44/2023/TT-BCT; 23/2025/TT-BCT",
                "instrument_note": "C/O mẫu B của Việt Nam; dùng fallback khi không có form ưu đãi phù hợp hoặc khách yêu cầu chứng nhận xuất xứ chung.",
                "source_label": "eCoSys + 05/2018/TT-BCT amendments",
                "source_url": "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
                "verification_status": "pending_trong_tin_confirmation",
                "enabled": True,
            },
            {
                "form_code": "CPTPP",
                "display_name": "Form CPTPP",
                "agreement": "CPTPP",
                "instrument": "03/2019/TT-BCT",
                "instrument_note": "Quy tắc xuất xứ CPTPP; Phụ lục PSR và mẫu C/O CPTPP.",
                "source_label": "VNTR CPTPP + eCoSys",
                "source_url": "https://vntr.moit.gov.vn/roo/rfta",
                "verification_status": "pending_trong_tin_confirmation",
                "enabled": True,
            },
            {
                "form_code": "EUR.1",
                "display_name": "Form EUR.1",
                "agreement": "EVFTA",
                "instrument": "14/2026/TT-BCT; previously 11/2020/TT-BCT and 41/2022/TT-BCT",
                "instrument_note": "EVFTA/EUR.1; PSR lives in the legal appendix for the selected effective instrument.",
                "source_label": "MOIT EVFTA TT14/2026 + eCoSys",
                "source_url": "https://moit.gov.vn/upload/2005517/20260428/Thong_tu_14_2026_TT_BCT_final_88aa1.pdf",
                "verification_status": "pending_trong_tin_confirmation",
                "enabled": True,
            },
            {
                "form_code": "AI",
                "display_name": "Form AI",
                "agreement": "ASEAN-India Free Trade Area",
                "instrument": "15/2010/TT-BCT",
                "instrument_note": "Quy tắc xuất xứ ASEAN-Ấn Độ; C/O Mẫu AI. Nguồn tìm được hiện xác nhận rule chung AIFTA 35% FOB + CTSH, chưa có bảng PSR all-HS công khai để seed tự động.",
                "source_label": "MOIT AIFTA + 15/2010/TT-BCT",
                "source_url": "https://fta.gov.vn/index.php?id=904&r=site%2Fcontent",
                "verification_status": "pending_trong_tin_confirmation",
                "enabled": True,
            },
        ],
        "market_presets": [
            {
                "market": "EU",
                "label": "EU / EVFTA",
                "form_code": "EUR.1",
                "aliases": [
                    "EU",
                    "European Union",
                    "Pháp",
                    "France",
                    "Đức",
                    "Germany",
                    "Hà Lan",
                    "Netherlands",
                    "Italy",
                    "Spain",
                    "Bỉ",
                    "Belgium",
                    "Ireland",
                    "Áo",
                    "Austria",
                    "Thụy Điển",
                    "Sweden",
                    "Phần Lan",
                    "Finland",
                    "Đan Mạch",
                    "Denmark",
                    "Ba Lan",
                    "Poland",
                    "Séc",
                    "Czech",
                    "Hungary",
                    "Slovakia",
                    "Slovenia",
                    "Lithuania",
                    "Latvia",
                    "Estonia",
                    "Portugal",
                    "Greece",
                    "Malta",
                    "Cyprus",
                    "Bulgaria",
                    "Romania",
                    "Luxembourg",
                    "Croatia",
                ],
                "selection_reason": "Destination is an EVFTA/EU market in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR EVFTA",
                "enabled": True,
                "show_in_picker": True,
            },
            {
                "market": "India",
                "label": "Ấn Độ / Form AI",
                "form_code": "AI",
                "aliases": ["India", "Ấn Độ", "An Do"],
                "selection_reason": "Destination is an AIFTA party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR AIFTA",
                "enabled": True,
                "show_in_picker": True,
            },
            {
                "market": "Canada",
                "label": "Canada / CPTPP",
                "form_code": "CPTPP",
                "aliases": ["Canada", "Ca-na-đa", "Ca na da"],
                "selection_reason": "Destination is a CPTPP party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR CPTPP",
                "enabled": True,
                "show_in_picker": True,
            },
            {
                "market": "Japan",
                "label": "Nhật Bản / CPTPP",
                "form_code": "CPTPP",
                "aliases": ["Japan", "Nhật Bản", "Nhat Ban"],
                "selection_reason": "Destination is a CPTPP party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR CPTPP",
                "enabled": True,
                "show_in_picker": True,
            },
            {
                "market": "Australia",
                "label": "Úc / CPTPP",
                "form_code": "CPTPP",
                "aliases": ["Australia", "Úc", "Uc"],
                "selection_reason": "Destination is a CPTPP party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR CPTPP",
                "enabled": True,
                "show_in_picker": True,
            },
            {
                "market": "Mexico",
                "label": "Mexico / CPTPP",
                "form_code": "CPTPP",
                "aliases": ["Mexico", "Mê-hi-cô", "Me hi co"],
                "selection_reason": "Destination is a CPTPP party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR CPTPP",
                "enabled": True,
                "show_in_picker": False,
            },
            {
                "market": "Peru",
                "label": "Peru / CPTPP",
                "form_code": "CPTPP",
                "aliases": ["Peru", "Pê-ru", "Pe ru"],
                "selection_reason": "Destination is a CPTPP party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR CPTPP",
                "enabled": True,
                "show_in_picker": False,
            },
            {
                "market": "Singapore",
                "label": "Singapore / CPTPP",
                "form_code": "CPTPP",
                "aliases": ["Singapore"],
                "selection_reason": "Destination is a CPTPP party in the CO form index.",
                "source_label": "temp/CO-TABLE-FORM.jpg + VNTR CPTPP",
                "enabled": True,
                "show_in_picker": False,
            },
        ],
        "psr_rules": list(seed_psr_rules()),
    }


def co_form_config_path() -> Path:
    return Path(os.environ.get("CO_FORM_CONFIG_PATH", DEFAULT_CO_FORM_CONFIG_PATH))


def load_co_form_config() -> dict:
    path = co_form_config_path()
    signature = config_file_signature(path)
    cache_key = str(path)
    cached = _CONFIG_CACHE.get(cache_key)
    if cached and cached[0] == signature:
        return cached[1]
    if not path.exists():
        config = sanitize_co_form_config(default_co_form_config())
    else:
        config = sanitize_co_form_config(json.loads(path.read_text(encoding="utf-8")))
    _CONFIG_CACHE[cache_key] = (signature, config)
    return config


def save_co_form_config(config: dict) -> dict:
    sanitized = sanitize_co_form_config(config)
    sanitized["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = co_form_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(sanitized, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp_name, path)
    clear_co_form_config_cache()
    return sanitized


def reset_co_form_config() -> dict:
    return save_co_form_config(default_co_form_config())


def clear_co_form_config_cache() -> None:
    _CONFIG_CACHE.clear()


def config_file_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def sanitize_co_form_config(config: dict) -> dict:
    default = default_co_form_config()
    payload = {**default, **(config or {})}
    forms = [sanitize_form(row) for row in payload.get("forms", []) if sanitize_form(row).get("form_code")]
    if not forms:
        forms = [sanitize_form(row) for row in default["forms"]]
    form_codes = [row["form_code"] for row in forms]
    priority = unique_text_list(payload.get("form_priority", []))
    priority = [code for code in priority if code in form_codes]
    priority.extend(code for code in form_codes if code not in priority)
    market_presets = [
        sanitize_market_preset(row)
        for row in payload.get("market_presets", [])
        if sanitize_market_preset(row).get("market") and sanitize_market_preset(row).get("form_code") in form_codes
    ]
    psr_rules = [
        sanitize_psr_rule(row)
        for row in payload.get("psr_rules", [])
        if sanitize_psr_rule(row).get("form_code") in form_codes and sanitize_psr_rule(row).get("hs_scope")
    ]
    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "updated_at": str(payload.get("updated_at") or ""),
        "source_note": str(payload.get("source_note") or default["source_note"]).strip(),
        "form_priority": priority,
        "forms": forms,
        "market_presets": market_presets,
        "psr_rules": psr_rules,
    }


def sanitize_form(row: dict) -> dict:
    return {
        "form_code": clean_text(row.get("form_code")).upper() if clean_text(row.get("form_code")) != "EUR.1" else "EUR.1",
        "display_name": clean_text(row.get("display_name")),
        "agreement": clean_text(row.get("agreement")),
        "instrument": clean_text(row.get("instrument")),
        "instrument_note": clean_text(row.get("instrument_note")),
        "source_label": clean_text(row.get("source_label")),
        "source_url": clean_text(row.get("source_url")),
        "verification_status": clean_text(row.get("verification_status")) or "pending_trong_tin_confirmation",
        "enabled": bool(row.get("enabled", True)),
    }


def sanitize_market_preset(row: dict) -> dict:
    return {
        "market": clean_text(row.get("market")),
        "label": clean_text(row.get("label")) or clean_text(row.get("market")),
        "form_code": clean_text(row.get("form_code")).upper() if clean_text(row.get("form_code")) != "EUR.1" else "EUR.1",
        "aliases": unique_text_list(row.get("aliases", [])),
        "selection_reason": clean_text(row.get("selection_reason")) or "Destination matches the configured CO form index.",
        "source_label": clean_text(row.get("source_label")),
        "enabled": bool(row.get("enabled", True)),
        "show_in_picker": bool(row.get("show_in_picker", False)),
    }


def sanitize_psr_rule(row: dict) -> dict:
    return {
        "form_code": clean_text(row.get("form_code")).upper() if clean_text(row.get("form_code")) != "EUR.1" else "EUR.1",
        "hs_scope": normalize_hs_scope(row.get("hs_scope")),
        "criteria": clean_text(row.get("criteria")),
        "source_reference": clean_text(row.get("source_reference")),
        "note": clean_text(row.get("note")),
        "status": clean_text(row.get("status")) or "pending_trong_tin_confirmation",
        "enabled": bool(row.get("enabled", True)),
    }


def unique_text_list(values) -> list[str]:
    if isinstance(values, str):
        values = values.replace("\n", ",").split(",")
    output = []
    seen = set()
    for value in values or []:
        text = clean_text(value)
        if not text or text in seen:
            continue
        output.append(text)
        seen.add(text)
    return output


def clean_text(value) -> str:
    return str(value or "").strip()
