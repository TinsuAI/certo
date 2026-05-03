from __future__ import annotations

import re
import unicodedata


FORM_REFERENCES = {
    "B": {
        "display_name": "Form B",
        "agreement": "Không ưu đãi / xuất xứ chung",
        "instrument": "05/2018/TT-BCT; 44/2023/TT-BCT; 23/2025/TT-BCT",
        "instrument_note": "C/O mẫu B của Việt Nam; PSR hiện dùng phụ lục đã sửa đổi, Form B không nằm trong ma trận ưu đãi.",
        "source_label": "docs/legal/canonical/corpus/05-2018-tt-bct...",
        "verification_status": "verified_local_corpus",
    },
    "AI": {
        "display_name": "Form AI",
        "agreement": "ASEAN-India Free Trade Area",
        "instrument": "15/2010/TT-BCT",
        "instrument_note": "Quy tắc xuất xứ ASEAN-Ấn Độ; C/O Mẫu AI.",
        "source_label": "docs/legal/canonical/corpus/15-2010-tt-bct...",
        "verification_status": "verified_local_corpus_temporary_text",
    },
    "CPTPP": {
        "display_name": "Form CPTPP",
        "agreement": "CPTPP",
        "instrument": "03/2019/TT-BCT",
        "instrument_note": "Quy tắc xuất xứ CPTPP; Phụ lục PSR và mẫu C/O CPTPP.",
        "source_label": "docs/legal/canonical/corpus/03-2019-tt-bct...",
        "verification_status": "verified_local_corpus",
    },
    "EUR.1": {
        "display_name": "Form EUR.1",
        "agreement": "EVFTA",
        "instrument": "11/2020/TT-BCT",
        "instrument_note": "EVFTA/EUR.1; lưu ý sửa đổi bởi 41/2022/TT-BCT.",
        "source_label": "docs/legal/canonical/corpus/11-2020-tt-bct...",
        "verification_status": "verified_local_corpus",
    },
}

FORM_PRIORITY = ("B", "CPTPP", "EUR.1", "AI")

COMMON_MARKET_PRESETS = [
    {"market": "EU", "form_code": "EUR.1", "label": "EU / EVFTA", "aliases": ["Pháp", "Đức", "Hà Lan", "Italy", "Spain"]},
    {"market": "Japan", "form_code": "CPTPP", "label": "Nhật Bản / CPTPP", "aliases": ["Nhật Bản"]},
    {"market": "Canada", "form_code": "CPTPP", "label": "Canada / CPTPP", "aliases": ["Ca-na-đa"]},
    {"market": "Australia", "form_code": "CPTPP", "label": "Úc / CPTPP", "aliases": ["Úc"]},
    {"market": "India", "form_code": "AI", "label": "Ấn Độ / Form AI", "aliases": ["Ấn Độ"]},
]

FORM_CRITERIA_PRESETS = {
    "B": [
        {
            "hs_scope": "8504",
            "criteria": "LVC 30% hoặc CTH",
            "source_reference": "44/2023/TT-BCT, Phụ lục I sửa đổi 05/2018/TT-BCT",
            "note": "Preview theo PSR Form B đã lưu; operator vẫn cần đối chiếu hồ sơ và thông tư.",
        },
        {
            "hs_scope": "8541",
            "criteria": "LVC 30% hoặc CTSH",
            "source_reference": "44/2023/TT-BCT, Phụ lục I sửa đổi 05/2018/TT-BCT",
            "note": "Một số phân nhóm 8541.42/8541.43 có ngoại lệ cùng phân nhóm.",
        },
        {
            "hs_scope": "Any HS",
            "criteria": "Tra PSR Form B theo Phụ lục I",
            "source_reference": "05/2018/TT-BCT, sửa đổi 44/2023/TT-BCT và 23/2025/TT-BCT",
            "note": "Chưa map tự động hết HS; legal PSR engine đang coming soon.",
        },
    ],
    "CPTPP": [
        {
            "hs_scope": "8504",
            "criteria": "CTH hoặc RVC 30/40/50 tùy công thức",
            "source_reference": "03/2019/TT-BCT, Phụ lục II",
            "note": "RVC: 30% trực tiếp, 40% gián tiếp, hoặc 50% giá trị tập trung.",
        },
        {
            "hs_scope": "8541",
            "criteria": "CTSH hoặc RVC 30/40/50 tùy công thức",
            "source_reference": "03/2019/TT-BCT, Phụ lục II",
            "note": "Áp dụng theo phân nhóm HS; chỉ nguyên liệu không có xuất xứ phải đạt chuyển đổi.",
        },
    ],
    "EUR.1": [
        {
            "hs_scope": "8504",
            "criteria": "CTH hoặc MaxNOM 70% EXW",
            "source_reference": "11/2020/TT-BCT, Phụ lục II",
            "note": "EVFTA/EUR.1; cần tính theo giá xuất xưởng khi dùng MaxNOM.",
        },
        {
            "hs_scope": "8541",
            "criteria": "Tra PSR EVFTA theo 6 số HS",
            "source_reference": "11/2020/TT-BCT, Phụ lục II; 41/2022/TT-BCT sửa đổi",
            "note": "Đã lưu thông tư/form; dòng PSR chi tiết sẽ do legal engine map tiếp.",
        },
    ],
    "AI": [
        {
            "hs_scope": "8504",
            "criteria": "AIFTA 35% FOB + CTSH",
            "source_reference": "15/2010/TT-BCT, Điều 4 Phụ lục 1",
            "note": "Áp dụng rule chung hàng hóa không thuần túy khi chưa có PSR riêng.",
        },
        {
            "hs_scope": "8541",
            "criteria": "AIFTA 35% FOB + CTSH",
            "source_reference": "15/2010/TT-BCT, Điều 4 Phụ lục 1",
            "note": "C/O Mẫu AI ghi tiêu chí và tỷ lệ hàm lượng ở ô số 8.",
        },
    ],
}

AI_MARKETS = {
    "brunei",
    "brunei darussalam",
    "campuchia",
    "cambodia",
    "indonesia",
    "lao",
    "laos",
    "malaysia",
    "myanmar",
    "philippines",
    "singapore",
    "thai lan",
    "thailand",
    "viet nam",
    "vietnam",
    "an do",
    "india",
}

CPTPP_MARKETS = {
    "australia",
    "uc",
    "brunei",
    "canada",
    "ca na da",
    "chile",
    "chi le",
    "japan",
    "nhat ban",
    "malaysia",
    "mexico",
    "me hi co",
    "new zealand",
    "niu di lan",
    "peru",
    "pe ru",
    "singapore",
    "viet nam",
    "vietnam",
}

EUR1_MARKETS = {
    "eu",
    "european union",
    "lien minh chau au",
    "ao",
    "austria",
    "ba lan",
    "bi",
    "belgium",
    "bo dao nha",
    "portugal",
    "bulgaria",
    "bun ga ri",
    "croatia",
    "croatia",
    "cong hoa sip",
    "cyprus",
    "czech",
    "sec",
    "dan mach",
    "denmark",
    "duc",
    "germany",
    "estonia",
    "ex to nia",
    "phan lan",
    "finland",
    "phap",
    "france",
    "ha lan",
    "netherlands",
    "hungary",
    "hung ga ri",
    "hy lap",
    "greece",
    "ireland",
    "ai len",
    "italia",
    "italy",
    "lat vi a",
    "latvia",
    "lit va",
    "lithuania",
    "luc xam bua",
    "luxembourg",
    "malta",
    "man ta",
    "romania",
    "ru ma ni",
    "slovakia",
    "slo va kia",
    "slovenia",
    "slo ve nia",
    "spain",
    "tay ban nha",
    "thuy dien",
    "sweden",
}


def form_candidates_for_market(market: str) -> list[dict]:
    key = market_key(market)
    candidates = []
    if key in AI_MARKETS:
        candidates.append(candidate("AI", "Destination is an AIFTA party in the local AI source."))
    if key in CPTPP_MARKETS:
        candidates.append(candidate("CPTPP", "Destination is in the local CPTPP member-code guidance."))
    if key in EUR1_MARKETS:
        candidates.append(candidate("EUR.1", "Destination is treated as EVFTA/EU market for EUR.1 guidance."))
    candidates.append(candidate("B", "Non-preferential fallback; operator must confirm when preferential form is not used."))
    return candidates


def prioritized_form_lanes(market: str, hs_codes: list[str] | None = None) -> list[dict]:
    candidates = {row["form_code"]: row for row in form_candidates_for_market(market)}
    normalized_hs_codes = normalize_hs_codes(hs_codes or [])
    market_is_set = bool(market_key(market) and market_key(market) != "chua nhap")
    preferential_matches = {form_code for form_code in candidates if form_code != "B"}
    preferred_form = next((form_code for form_code in FORM_PRIORITY if form_code in preferential_matches), "")
    if not preferred_form and "B" in candidates:
        preferred_form = "B"
    lanes = []
    for index, form_code in enumerate(FORM_PRIORITY, start=1):
        reference = FORM_REFERENCES[form_code]
        matched_candidate = candidates.get(form_code)
        recommended = bool(matched_candidate and market_is_set and form_code == preferred_form)
        lanes.append({
            "priority": index,
            "form_code": form_code,
            "display_name": reference["display_name"],
            "agreement": reference["agreement"],
            "instrument": reference["instrument"],
            "verification_status": reference["verification_status"],
            "recommended": recommended,
            "selection_reason": matched_candidate["selection_reason"] if matched_candidate else "Không tự khuyến nghị cho thị trường hiện tại; operator có thể chọn thủ công.",
            "rule_lookup_label": "PSR engine coming soon",
            "criteria_preview": criteria_preview_rows(form_code, normalized_hs_codes),
        })
    return lanes


def recommended_form_lane(lanes: list[dict]) -> dict:
    return next((lane for lane in lanes if lane.get("recommended")), lanes[0] if lanes else {})


def common_market_guidance() -> list[dict]:
    rows = []
    for preset in COMMON_MARKET_PRESETS:
        reference = FORM_REFERENCES[preset["form_code"]]
        rows.append({
            **preset,
            "display_name": reference["display_name"],
            "agreement": reference["agreement"],
            "instrument": reference["instrument"],
        })
    return rows


def criteria_preview_rows(form_code: str, hs_codes: list[str]) -> list[dict]:
    if hs_codes:
        return [criteria_preview_for_hs(form_code, hs_code) for hs_code in hs_codes]
    return [
        {
            "hs_code": preset["hs_scope"],
            "criteria": preset["criteria"],
            "note": preset["note"],
            "source_reference": preset.get("source_reference", FORM_REFERENCES[form_code]["instrument"]),
            "status": "coming soon",
        }
        for preset in FORM_CRITERIA_PRESETS[form_code]
    ]


def criteria_preview_for_hs(form_code: str, hs_code: str) -> dict:
    hs_key = normalize_hs(hs_code)
    preset = first_matching_preset(form_code, hs_key)
    return {
        "hs_code": hs_code,
        "criteria": preset["criteria"],
        "note": preset["note"],
        "source_reference": preset.get("source_reference", FORM_REFERENCES[form_code]["instrument"]),
        "status": "coming soon",
    }


def first_matching_preset(form_code: str, hs_key: str) -> dict:
    presets = FORM_CRITERIA_PRESETS[form_code]
    for preset in presets:
        scope = normalize_hs(preset["hs_scope"])
        if scope and hs_key.startswith(scope):
            return preset
    return presets[0]


def normalize_hs_codes(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        normalized = normalize_hs(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value)
    return output[:8]


def normalize_hs(value: str) -> str:
    return re.sub(r"\D+", "", value or "")[:6]


def candidate(form_code: str, reason: str) -> dict:
    reference = FORM_REFERENCES[form_code]
    return {
        "form_code": form_code,
        "rule_lookup_status": "needs_rule_lookup",
        "rule_lookup_label": "Cần tra cứu PSR theo HS",
        "selection_reason": reason,
        **reference,
    }


def market_key(value: str) -> str:
    text = strip_accents(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def strip_accents(value: str) -> str:
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(char) != "Mn"
    )
    return normalized.replace("đ", "d").replace("Đ", "D")
