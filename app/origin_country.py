from __future__ import annotations

import re

COLUMN9_MODE_COUNTRY = "country"
COLUMN9_MODE_QUALIFICATION = "qualification_label"
COLUMN9_MODES = {COLUMN9_MODE_COUNTRY, COLUMN9_MODE_QUALIFICATION}
DEFAULT_COLUMN9_MODE = COLUMN9_MODE_COUNTRY
DEFAULT_UNKNOWN_ORIGIN_LABEL = "Không xác định"

QUALIFICATION_LABEL_ORIGIN = "Việt Nam"
QUALIFICATION_LABEL_NON_ORIGIN = "Không xuất xứ"

# Raw BCCT origin vocabulary → ISO 3166-1 alpha-2. Seeded from the observed
# values across Johnson + Growatt BCCT data (2026-07-10 audit) plus the
# common customs-style abbreviations of the region. Git-versioned and
# code-owned by design (ADR 2026-07-11): an unmapped-but-present string
# renders raw with a non-blocking warning, never a block, so a vocabulary
# gap cannot stop a dossier whose numbers are correct.
RAW_TO_ISO = {
    "VIETNAM": "VN",
    "VIET NAM": "VN",
    "CHINA": "CN",
    "TAIWAN": "TW",
    "TAIWAN (ROC)": "TW",
    "JAPAN": "JP",
    "GERMANY": "DE",
    "U.S.A.": "US",
    "USA": "US",
    "U.S.A": "US",
    "AMERICA": "US",
    "SWITZLD": "CH",
    "SWITZERLAND": "CH",
    "HG.KONG": "HK",
    "HONG KONG": "HK",
    "HONGKONG": "HK",
    "THAILND": "TH",
    "THAILAND": "TH",
    "U KING": "GB",
    "UNITED KINGDOM": "GB",
    "ENGLAND": "GB",
    "INDNSIA": "ID",
    "INDONESIA": "ID",
    "KOREA": "KR",
    "S.KOREA": "KR",
    "SOUTH KOREA": "KR",
    "KOREA (REP.)": "KR",
    "MALAYSIA": "MY",
    "MALAYSA": "MY",
    "SINGAPORE": "SG",
    "SINGAPORE REP.": "SG",
    "INDIA": "IN",
    "ITALY": "IT",
    "FRANCE": "FR",
    "SPAIN": "ES",
    "NETHERLANDS": "NL",
    "PHILIPPINES": "PH",
    "PHILIPPINE": "PH",
    "AUSTRALIA": "AU",
    "CANADA": "CA",
    "MEXICO": "MX",
    "BRAZIL": "BR",
    "RUSSIA": "RU",
    "TURKEY": "TR",
    "POLAND": "PL",
    "CZECH": "CZ",
    "SWEDEN": "SE",
    "AUSTRIA": "AT",
    "BELGIUM": "BE",
    "DENMARK": "DK",
    "FINLAND": "FI",
    "NORWAY": "NO",
    "LAOS": "LA",
    "CAMBODIA": "KH",
    "MYANMAR": "MM",
    "MACAU": "MO",
    "MACAO": "MO",
    "NEW ZEALAND": "NZ",
    "ISRAEL": "IL",
    "SAUDI ARABIA": "SA",
    "UAE": "AE",
    "U.A.E": "AE",
}

ISO_TO_VI = {
    "VN": "Việt Nam",
    "CN": "Trung Quốc",
    "TW": "Đài Loan",
    "JP": "Nhật Bản",
    "DE": "Đức",
    "US": "Hoa Kỳ",
    "CH": "Thụy Sĩ",
    "HK": "Hồng Kông",
    "TH": "Thái Lan",
    "GB": "Anh",
    "ID": "Indonesia",
    "KR": "Hàn Quốc",
    "MY": "Malaysia",
    "SG": "Singapore",
    "IN": "Ấn Độ",
    "IT": "Ý",
    "FR": "Pháp",
    "ES": "Tây Ban Nha",
    "NL": "Hà Lan",
    "PH": "Philippines",
    "AU": "Úc",
    "CA": "Canada",
    "MX": "Mexico",
    "BR": "Brazil",
    "RU": "Nga",
    "TR": "Thổ Nhĩ Kỳ",
    "PL": "Ba Lan",
    "CZ": "Séc",
    "SE": "Thụy Điển",
    "AT": "Áo",
    "BE": "Bỉ",
    "DK": "Đan Mạch",
    "FI": "Phần Lan",
    "NO": "Na Uy",
    "LA": "Lào",
    "KH": "Campuchia",
    "MM": "Myanmar",
    "MO": "Macau",
    "NZ": "New Zealand",
    "IL": "Israel",
    "SA": "Ả Rập Xê Út",
    "AE": "UAE",
}

# The unknown bucket: lots whose origin is genuinely not stated. Only THESE
# render the configurable unknown label — a present-but-unmapped country
# string must never be swallowed by it.
_UNKNOWN_RAW = {"", "UNKNOWN", "KHONG XAC DINH", "KHÔNG XÁC ĐỊNH", "N/A", "NA"}

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_raw(raw: str | None) -> str:
    return _WHITESPACE_RUN.sub(" ", str(raw or "")).strip().upper()


def is_unknown_origin(raw: str | None) -> bool:
    return normalize_raw(raw) in _UNKNOWN_RAW


def iso_for_raw(raw: str | None) -> str:
    return RAW_TO_ISO.get(normalize_raw(raw), "")


def is_vietnam_origin(raw: str | None) -> bool:
    return iso_for_raw(raw) == "VN"


def country_label_vi(raw: str | None, unknown_label: str = DEFAULT_UNKNOWN_ORIGIN_LABEL) -> tuple[str, bool]:
    """Resolve a raw BCCT origin string to the Vietnamese display label.

    Returns (label, mapped): unknown bucket → the configured label (mapped);
    known vocabulary → Vietnamese name (mapped); anything else → the raw
    string as-is with mapped=False so the caller can attach the non-blocking
    warning."""
    if is_unknown_origin(raw):
        return (str(unknown_label or DEFAULT_UNKNOWN_ORIGIN_LABEL), True)
    iso = iso_for_raw(raw)
    if iso and iso in ISO_TO_VI:
        return (ISO_TO_VI[iso], True)
    return (str(raw or "").strip(), False)


def column9_text(mode: str, origin_status: str, country_label: str) -> str:
    """The bảng kê column (9) cell text. PURE and independent of money: the
    mode never touches origin_status/value columns — the two modes must yield
    identical (7)/(8) totals and LVC."""
    if mode == COLUMN9_MODE_QUALIFICATION:
        return QUALIFICATION_LABEL_ORIGIN if str(origin_status or "") == "origin" else QUALIFICATION_LABEL_NON_ORIGIN
    return str(country_label or "")


def normalize_column9_mode(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in COLUMN9_MODES else ""
