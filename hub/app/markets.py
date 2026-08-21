"""Market-hint helpers for export-side BCCT analysis.

Used by `/v1/hub/bcct/invoice-matches` to translate a customs
`Địa điểm dỡ hàng` (unloading location) value into an ISO 3166-1
alpha-2 country code + display name. The hint is a *recommendation* for
the C/O case-creation flow in the CO app; the operator confirms before
acting on it.

Rules (mirrored from the request brief at
`.ai/features/2026-05-03-bcct-invoice-market-fields/brief.md`):

- Prefer `unloading_location`. UN/LOCODE format is `^[A-Z]{2}[A-Z0-9]{3}` —
  the leading two characters are the ISO 3166-1 alpha-2 country.
- VN as the unloading country = bonded domestic transfer (e.g. `VNZZZ`),
  not a real export market. Confidence is downgraded to `medium`
  there and the consumer is expected to fall back to operator input.
- `destination_location_code` / `destination_location_name` describe
  Vietnam-side bonded logistics. They are surfaced as raw evidence
  but never converted into a market hint here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Top ~40 destination markets seen in real Growatt/Johnson BCCT data
# plus the typical OECD + ASEAN exporters. Keep the list small and
# additive; unknown codes still return high-confidence `country_code`
# with a null `country_name` so the consumer renders the raw code.
_ISO_3166_ALPHA2: dict[str, str] = {
    "US": "United States", "CA": "Canada", "MX": "Mexico",
    "BR": "Brazil", "AR": "Argentina", "CL": "Chile",
    "GB": "United Kingdom", "IE": "Ireland",
    "DE": "Germany", "FR": "France", "NL": "Netherlands", "BE": "Belgium",
    "IT": "Italy", "ES": "Spain", "PT": "Portugal",
    "CH": "Switzerland", "AT": "Austria",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "PL": "Poland", "CZ": "Czechia", "HU": "Hungary", "RO": "Romania",
    "RU": "Russia", "TR": "Turkey", "UA": "Ukraine",
    "AE": "United Arab Emirates", "SA": "Saudi Arabia", "IL": "Israel",
    "EG": "Egypt", "ZA": "South Africa", "KE": "Kenya", "NG": "Nigeria",
    "JP": "Japan", "KR": "South Korea", "CN": "China",
    "TW": "Taiwan", "HK": "Hong Kong", "MO": "Macao",
    "SG": "Singapore", "MY": "Malaysia", "TH": "Thailand",
    "ID": "Indonesia", "PH": "Philippines", "VN": "Vietnam",
    "IN": "India", "PK": "Pakistan", "BD": "Bangladesh",
    "LK": "Sri Lanka", "NP": "Nepal",
    "AU": "Australia", "NZ": "New Zealand",
}

_UNLOCODE_RE = re.compile(r"^([A-Z]{2})[A-Z0-9]{3}\b")


@dataclass(frozen=True)
class MarketHint:
    country_code: str | None
    country_name: str | None
    source_field: str
    source_value: str
    confidence: str  # 'high' | 'medium' | 'low'

    def to_dict(self) -> dict:
        return {
            "country_code": self.country_code,
            "country_name": self.country_name,
            "source_field": self.source_field,
            "source_value": self.source_value,
            "confidence": self.confidence,
        }


def unloading_location_to_market_hint(value: str | None) -> MarketHint | None:
    """Parse an unloading-location string into a MarketHint.

    Returns None when `value` is empty/whitespace-only. Returns a `low`
    confidence hint (with `country_code=None`) when the value is present
    but does not begin with a valid UN/LOCODE country prefix — keeps the
    raw evidence visible to the consumer without committing to a code.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    upper = raw.upper()
    match = _UNLOCODE_RE.match(upper)
    if not match:
        return MarketHint(
            country_code=None, country_name=None,
            source_field="unloading_location", source_value=raw,
            confidence="low",
        )
    code = match.group(1)
    # VN prefix on the *unloading* leg means a domestic bonded transfer
    # (e.g. VNZZZ for "Vietnam, no specific port"). Don't claim it as a
    # high-confidence export market; CO operator confirms.
    confidence = "medium" if code == "VN" else "high"
    return MarketHint(
        country_code=code,
        country_name=_ISO_3166_ALPHA2.get(code),
        source_field="unloading_location",
        source_value=raw,
        confidence=confidence,
    )
