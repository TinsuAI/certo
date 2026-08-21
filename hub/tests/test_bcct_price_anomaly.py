"""Phase 2: BCCT price-pair inversion detector (anomaly net).

Regression anchor: the 2026-06-05 johnson-vn incident where a confirmed
mapping swapped unit_price ↔ unit_price_nt, so every foreign-currency row
had the big VND amount in the nguyên-tệ column.
"""
from __future__ import annotations

from hub.app.parsers.bcct_validate import (
    detect_price_anomalies, has_blocking_anomaly,
)


def _row(**kw) -> dict:
    base = {
        "declaration_no": "308490190540", "line_no": "1",
        "currency_nt": "EUR", "exchange_rate": 30377.72,
        "unit_price": 10136289.92, "unit_price_nt": 380.7,
        "total_value": 5111658.94, "total_value_nt": 168.27,
    }
    base.update(kw)
    return base


def test_consistent_rows_no_warning():
    rows = [_row() for _ in range(10)]
    assert detect_price_anomalies(rows) == []
    assert not has_blocking_anomaly(detect_price_anomalies(rows))


def test_incident_inversion_is_blocking():
    # unit_price <-> unit_price_nt swapped (the incident), total_value fine.
    rows = [
        _row(unit_price=380.7, unit_price_nt=10136289.92)
        for _ in range(10)
    ]
    ws = detect_price_anomalies(rows)
    codes = {tuple(w["field_pair"]): w for w in ws}
    assert ("unit_price", "unit_price_nt") in codes
    up = codes[("unit_price", "unit_price_nt")]
    assert up["severity"] == "block"
    assert up["affected_rows"] == 10
    assert has_blocking_anomaly(ws)
    # total_value pair stayed consistent → not flagged.
    assert ("total_value", "total_value_nt") not in codes


def test_minority_inversion_is_warn_not_block():
    rows = [_row() for _ in range(9)]
    rows.append(_row(unit_price=380.7, unit_price_nt=10136289.92))
    ws = detect_price_anomalies(rows)
    up = next(w for w in ws if w["field_pair"] == ["unit_price", "unit_price_nt"])
    assert up["severity"] == "warn"
    assert up["affected_rows"] == 1
    assert not has_blocking_anomaly(ws)


def test_vnd_rows_skipped():
    # currency_nt = VND → no FX domain, pair not comparable, no warning even
    # if magnitudes look odd.
    rows = [_row(currency_nt="VND", unit_price=1.0, unit_price_nt=999999.0)
            for _ in range(10)]
    assert detect_price_anomalies(rows) == []


def test_missing_or_unit_rate_skipped():
    rows = [
        _row(exchange_rate=None),       # no rate
        _row(exchange_rate=1.0),        # rate==1 (already local)
        _row(unit_price=0, unit_price_nt=0),  # zero amounts
    ]
    assert detect_price_anomalies(rows) == []
