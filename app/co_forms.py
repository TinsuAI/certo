from __future__ import annotations

import re
import unicodedata


FORM_REFERENCES = {
    "B": {
        "display_name": "Form B",
        "agreement": "Không ưu đãi / xuất xứ chung",
        "instrument": "05/2018/TT-BCT",
        "instrument_note": "C/O mẫu B của Việt Nam; Form B không nằm trong ma trận ưu đãi.",
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
