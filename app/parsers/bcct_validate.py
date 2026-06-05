"""Post-parse anomaly detection for BCCT rows (Phase 2 mapping overhaul).

Pure, DB-free validators surfaced as non-blocking warnings on the preview —
EXCEPT a clear column inversion, which is a hard gate (needs explicit ack).

The motivating incident (2026-06-05): a confirmed mapping swapped
`unit_price` (VND, "đơn giá tính thuế") with `unit_price_nt` (nguyên tệ,
"đơn giá"). For a foreign-currency row the VND amount must be ≈ the
foreign amount × exchange_rate (rate ≫ 1), so the VND field is the LARGER
one. If instead the *_nt field is ≈ VND × rate, the two columns are
inverted.
"""
from __future__ import annotations

# currency_nt values that mean "already local" — no FX domain, skip the pair.
_VND_CURRENCIES = {"", "VND", "VNĐ", "VN", "VND.", "DONG", "ĐỒNG"}

# (vnd_field, nt_field) pairs that must satisfy vnd ≈ nt × exchange_rate.
_PRICE_PAIRS = (
    ("unit_price", "unit_price_nt"),
    ("total_value", "total_value_nt"),
)


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def detect_price_anomalies(
    rows: list[dict], *, ratio_lo: float = 0.5, ratio_hi: float = 2.0,
    block_fraction: float = 0.5,
) -> list[dict]:
    """Return anomaly warnings for VND/nguyên-tệ price-pair inversion.

    For each (vnd_field, nt_field) pair, over rows that have a non-VND
    `currency_nt`, a usable `exchange_rate` (>1) and both amounts > 0:
      - consistent : vnd / nt ≈ exchange_rate (within [ratio_lo, ratio_hi]).
      - inverted   : nt / vnd ≈ exchange_rate (and NOT consistent).
    If inverted rows are ≥ `block_fraction` of the comparable rows → a
    `severity='block'` warning (hard gate). A smaller share → `severity=
    'warn'` (advisory). Returns [] when everything is consistent.
    """
    warnings: list[dict] = []
    for vnd_field, nt_field in _PRICE_PAIRS:
        comparable = 0
        inverted = 0
        samples: list[dict] = []
        for r in rows:
            cur = str(r.get("currency_nt") or "").strip().upper()
            if cur in _VND_CURRENCIES:
                continue
            rate = _num(r.get("exchange_rate"))
            vnd = _num(r.get(vnd_field))
            nt = _num(r.get(nt_field))
            if not rate or rate <= 1 or not vnd or not nt or vnd <= 0 or nt <= 0:
                continue
            comparable += 1
            consistent = ratio_lo <= (vnd / nt) / rate <= ratio_hi
            inverted_match = ratio_lo <= (nt / vnd) / rate <= ratio_hi
            if inverted_match and not consistent:
                inverted += 1
                if len(samples) < 5:
                    samples.append({
                        "decl_no": r.get("declaration_no"),
                        "line_no": r.get("line_no"),
                        "currency_nt": r.get("currency_nt"),
                        "exchange_rate": rate,
                        vnd_field: vnd,
                        nt_field: nt,
                    })
        if not comparable or not inverted:
            continue
        severity = "block" if inverted / comparable >= block_fraction else "warn"
        warnings.append({
            "code": "price_pair_inverted",
            "field_pair": [vnd_field, nt_field],
            "severity": severity,
            "affected_rows": inverted,
            "comparable_rows": comparable,
            "samples": samples,
            "message": (
                f"Nghi đảo 2 cột '{vnd_field}' và '{nt_field}': "
                f"{inverted}/{comparable} dòng ngoại tệ có giá trị nguyên tệ "
                f"≈ giá trị VND × tỷ giá (đáng lẽ ngược lại). "
                f"Kiểm tra lại ánh xạ cột đơn giá/trị giá."
            ),
        })
    return warnings


def has_blocking_anomaly(warnings: list[dict]) -> bool:
    return any(w.get("severity") == "block" for w in (warnings or []))
