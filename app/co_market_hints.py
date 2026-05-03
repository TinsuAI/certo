from __future__ import annotations


COUNTRY_MARKET_LABELS = {
    "IN": "India",
    "US": "United States",
}


def infer_market_from_invoice_matches(invoice_matches: list[dict]) -> dict:
    high_confidence_hints = []
    for row in invoice_matches:
        hint = row.get("market_hint")
        if not isinstance(hint, dict):
            continue
        if str(hint.get("confidence", "")).lower() != "high":
            continue
        country_code = str(hint.get("country_code") or "").upper().strip()
        country_name = str(hint.get("country_name") or "").strip()
        if not country_code and not country_name:
            continue
        high_confidence_hints.append({
            "country_code": country_code,
            "country_name": country_name,
            "source_field": hint.get("source_field", ""),
            "source_value": hint.get("source_value", ""),
        })

    unique_hints = {}
    for hint in high_confidence_hints:
        key = hint["country_code"] or hint["country_name"].lower()
        unique_hints[key] = hint

    if not unique_hints:
        return {"status": "missing", "destination_market": "", "hints": []}
    if len(unique_hints) > 1:
        return {"status": "conflict", "destination_market": "", "hints": list(unique_hints.values())}

    hint = next(iter(unique_hints.values()))
    market = COUNTRY_MARKET_LABELS.get(hint["country_code"]) or hint["country_name"] or hint["country_code"]
    return {"status": "ready", "destination_market": market, "hints": [hint]}
