from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

LEGAL_PSR_SOURCES = [
    {
        "form_code": "B",
        "path": "docs/legal/canonical/corpus/44-2023-tt-bct-thong-tu-so-44-2023-tt-bct-ngay-29-thang-12-nam-2023-cua-bo-truong-bo-cong-thuong-sua-doi-bo-sung-mot-so-.md",
        "source_reference": "44/2023/TT-BCT, Phụ lục I sửa đổi 05/2018/TT-BCT",
        "status": "extracted_from_local_corpus_pending_trong_tin_confirmation",
        "start_line": 1,
        "end_line": None,
    },
    {
        "form_code": "CPTPP",
        "path": "docs/legal/wiki/03-2019-tt-bct-thong-tu-quy-inh-quy-tac-xuat-xu-hang-hoa-trong-hiep-inh-oi-tac-toan-dien-va-tien-bo-xuyen-thai-binh-duon.md",
        "source_reference": "03/2019/TT-BCT, Phụ lục I",
        "status": "extracted_from_local_corpus_pending_trong_tin_confirmation",
        "start_line": 845,
        "end_line": 4922,
    },
    {
        "form_code": "EUR.1",
        "path": "docs/legal/wiki/11-2020-tt-bct-thong-tu-quy-inh-quy-tac-xuat-xu-hang-hoa-trong-hiep-inh-thuong-mai-tu-do-giua-viet-nam-va-lien-minh-chau.md",
        "source_reference": "11/2020/TT-BCT, Phụ lục II; refresh against 14/2026/TT-BCT before treating as final",
        "status": "needs_2026_evfta_refresh",
        "start_line": 363,
        "end_line": 2174,
    },
]

HS_SCOPE_START_RE = re.compile(
    r"^\s*((?:ex\s+)?(?:Chương\s+\d{1,2}|\d{2}\.\d{2}|\d{4}(?:\.\d{2})?|\d{4,6})"
    r"(?:\s*-\s*(?:\d{2}\.\d{2}|\d{4}(?:\.\d{2})?|\d{4,6}))?"
    r"(?:\s*,\s*\d{4})*)\b\s*(.*)$",
    re.IGNORECASE,
)
RULE_TOKEN_RE = re.compile(
    r"(?<!\w)(?:"
    r"LVC\s*\d+%|"
    r"RVC\s*(?:không thấp hơn|\(?\d+\)?|\d+%)|"
    r"CTSH|CTH|CC|WO|"
    r"Xuất xứ thuần túy|"
    r"Sử dụng nguyên liệu|"
    r"Nguyên liệu .*xuất xứ|"
    r"Trị giá nguyên liệu|"
    r"MaxNOM"
    r")",
    re.IGNORECASE,
)
NOISE_LINE_RE = re.compile(
    r"^(?:Nhóm HS|Mã số|\(?HS|\(1\)|Phụ lục|QUY TẮC|_+|#+|\d+$|\f|"
    r"BỘ CÔNG|CỘNG HÒA|Độc lập|\(ban hành|PHẦN|Mô tả hàng hóa|Công đoạn|\(?[123]\)\s*$)",
    re.IGNORECASE,
)
CHAPTER_SCOPE_RE = re.compile(r"^(ex\s+)?Chương\s+(\d{1,2})$", re.IGNORECASE)


@lru_cache(maxsize=1)
def seed_psr_rules() -> tuple[dict, ...]:
    rules: list[dict] = []
    for source in LEGAL_PSR_SOURCES:
        source_path = REPO_ROOT / source["path"]
        if not source_path.exists():
            continue
        rules.extend(extract_psr_rules(source_path, source))
    rules.extend(manual_anchor_rules())
    return tuple(dedupe_rules(rules))


def extract_psr_rules(source_path: Path, source: dict) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    start_line = int(source.get("start_line") or 1)
    end_line = source.get("end_line")
    for line_no, line in enumerate(source_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if line_no < start_line:
            continue
        if end_line and line_no >= int(end_line):
            break
        text = line.strip()
        if not text or NOISE_LINE_RE.match(text):
            continue
        match = HS_SCOPE_START_RE.match(text)
        if match:
            append_entry(entries, current, source)
            current = {
                "line_no": line_no,
                "hs_scope": normalize_hs_scope(match.group(1)),
                "criteria": clean_text(match.group(2)),
            }
            continue
        if current:
            current["criteria"] = clean_text(f"{current['criteria']} {text}")
    append_entry(entries, current, source)
    return entries


def append_entry(entries: list[dict], current: dict | None, source: dict) -> None:
    if not current or not RULE_TOKEN_RE.search(current["criteria"]):
        return
    criteria = criteria_text(current["criteria"])
    if not criteria:
        return
    entries.append({
        "form_code": source["form_code"],
        "hs_scope": current["hs_scope"],
        "criteria": criteria,
        "source_reference": source["source_reference"],
        "note": f"Extracted from local legal corpus line {current['line_no']}; verify table extraction before final use.",
        "status": source["status"],
        "enabled": True,
    })


def criteria_text(value: str) -> str:
    match = RULE_TOKEN_RE.search(value)
    if not match:
        return ""
    text = clean_text(value[match.start():])
    if len(text) > 700:
        text = text[:700].rstrip() + "..."
    return text


def manual_anchor_rules() -> list[dict]:
    return [
        {
            "form_code": "B",
            "hs_scope": "Any HS",
            "criteria": "Tra PSR Form B theo Phụ lục I",
            "source_reference": "05/2018/TT-BCT, sửa đổi 44/2023/TT-BCT và 23/2025/TT-BCT",
            "note": "Fallback when no extracted HS scope matches the shipment HS code.",
            "status": "requires_manual_lookup",
            "enabled": True,
        },
        {
            "form_code": "CPTPP",
            "hs_scope": "8541",
            "criteria": "CTSH hoặc RVC 30/40/50 tùy công thức",
            "source_reference": "03/2019/TT-BCT, Phụ lục I; HS2022 bridge for photovoltaic subheadings",
            "note": "Local CPTPP corpus is HS2012 and contains 8541.40; use this HS2022 bridge for 8541.4x until legal mapping is confirmed.",
            "status": "pending_trong_tin_confirmation",
            "enabled": True,
        },
        {
            "form_code": "CPTPP",
            "hs_scope": "Any HS",
            "criteria": "Tra PSR CPTPP theo Phụ lục I",
            "source_reference": "03/2019/TT-BCT, Phụ lục I",
            "note": "Fallback when no extracted HS scope matches the shipment HS code.",
            "status": "requires_manual_lookup",
            "enabled": True,
        },
        {
            "form_code": "EUR.1",
            "hs_scope": "85",
            "criteria": "Sử dụng nguyên liệu từ bất kỳ Nhóm nào để sản xuất, ngoại trừ Nhóm của sản phẩm; hoặc trị giá nguyên liệu không vượt quá 70% giá xuất xưởng",
            "source_reference": "11/2020/TT-BCT, Phụ lục II; refresh against 14/2026/TT-BCT before treating as final",
            "note": "Chapter-level EVFTA local-corpus anchor for Chapter 85; detailed exception rows remain in extracted rules where available.",
            "status": "needs_2026_evfta_refresh",
            "enabled": True,
        },
        {
            "form_code": "EUR.1",
            "hs_scope": "Any HS",
            "criteria": "Tra PSR EVFTA/EUR.1 theo Phụ lục II",
            "source_reference": "11/2020/TT-BCT, Phụ lục II; refresh against 14/2026/TT-BCT before treating as final",
            "note": "Fallback when no extracted HS scope matches the shipment HS code.",
            "status": "requires_manual_lookup",
            "enabled": True,
        },
        {
            "form_code": "AI",
            "hs_scope": "Any HS",
            "criteria": "AIFTA 35% FOB + CTSH",
            "source_reference": "15/2010/TT-BCT, Điều 4 Phụ lục 1; AIFTA legal text Annex 2",
            "note": "Located official guidance exposes the general non-wholly-obtained rule (35% AIFTA content and CTSH). Appendix B Product Specific Rules is listed as under negotiation in the legal-text index; add overrides only when an official PSR table or Trọng Tín confirmation is available.",
            "status": "pending_trong_tin_confirmation",
            "enabled": True,
        }
    ]


def dedupe_rules(rules: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for rule in rules:
        key = (rule["form_code"], rule["hs_scope"], rule["criteria"])
        if key in seen:
            continue
        output.append(rule)
        seen.add(key)
    return output


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" :-;")


def normalize_hs_scope(value: str) -> str:
    scope = clean_text(value)
    match = CHAPTER_SCOPE_RE.match(scope)
    if not match:
        return scope
    prefix = "ex " if match.group(1) else ""
    return f"{prefix}{match.group(2).zfill(2)}"
