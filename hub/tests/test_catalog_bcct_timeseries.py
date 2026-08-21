"""Tests for `app/stores/catalog_bcct_timeseries.py`.

Brief: `.ai/features/2026-05-20-catalog-detail-time-series/brief.md`.

Synthetic throwaway client with BCCT rows spread across dates; covers:
- RLE collapses consecutive same-value rows into one Run.
- RLE splits on field value change.
- Null vs non-null treated as distinct (`∅` run).
- Multi-line declaration aggregates to one timeline node (modal).
- Quarter buckets span year boundary.
- Price-jump flag fires when median ratio ≥ 2× between consecutive
  quarters, NOT within [0.5, 2.0].
- declaration_type drift is surfaced (4th field added in this feature).
"""
from __future__ import annotations

import secrets

import pytest

from hub.app.database import connect
from hub.app.stores.catalog_bcct_timeseries import analyze_material_timeline


@pytest.fixture
def cid():
    client_id = "tline-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (client_id, "timeline test"),
        )
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (client_id,))
        cur.execute(
            "delete from hub.bcct_row_history where client_id=%s", (client_id,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (client_id,))


def _bcct(cur, *, client_id, code, decl_no, line_no, date_str,
          direction="import", declaration_type="E11",
          unit="PIECES", hs_code="73251090", origin="CHINA",
          currency_nt="USD", unit_price=10.0, quantity=100.0):
    cur.execute(
        """insert into hub.bcct_rows
           (client_id, transaction_key, line_no, declaration_no,
            declaration_type, direction, registration_date,
            customs_code, goods_name, unit, hs_code, origin,
            currency_nt, unit_price, quantity, payload)
           values (%s, %s, %s, %s,
                   %s, %s, %s,
                   %s, %s, %s, %s, %s,
                   %s, %s, %s, '{}'::jsonb)""",
        (client_id, f"TX-{decl_no}-{line_no}-{direction}",
         line_no, decl_no, declaration_type, direction, date_str,
         code, f"{code} desc", unit, hs_code, origin,
         currency_nt, unit_price, quantity),
    )


# ─── RLE behavior ─────────────────────────────────────────────────────


def test_rle_collapses_consecutive_same_value(cid):
    """3 consecutive SETS declarations → 1 run, not 3."""
    with connect() as conn, conn.cursor() as cur:
        for i, day in enumerate(("2025-06-01", "2025-06-02", "2025-06-05"), start=1):
            _bcct(cur, client_id=cid, code="X1",
                  decl_no=f"D{i:03d}", line_no="1",
                  date_str=day, unit="SETS")
    t = analyze_material_timeline(client_id=cid, material_code="X1")
    ft = next(f for f in t.timelines if f.field == "unit")
    assert len(ft.runs) == 1
    assert ft.runs[0].value == "SETS"
    assert ft.runs[0].n_declarations == 3
    assert ft.runs[0].direction_breakdown == {"import": 3}


def test_rle_splits_on_value_change(cid):
    """SETS, SETS, PIECES, SETS → 3 runs."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X2", decl_no="D1",
              line_no="1", date_str="2025-06-01", unit="SETS")
        _bcct(cur, client_id=cid, code="X2", decl_no="D2",
              line_no="1", date_str="2025-06-02", unit="SETS")
        _bcct(cur, client_id=cid, code="X2", decl_no="D3",
              line_no="1", date_str="2025-06-03", unit="PIECES")
        _bcct(cur, client_id=cid, code="X2", decl_no="D4",
              line_no="1", date_str="2025-06-04", unit="SETS")
    t = analyze_material_timeline(client_id=cid, material_code="X2")
    ft = next(f for f in t.timelines if f.field == "unit")
    assert [r.value for r in ft.runs] == ["SETS", "PIECES", "SETS"]
    assert [r.n_declarations for r in ft.runs] == [2, 1, 1]
    assert ft.has_drift


def test_rle_treats_null_as_distinct_value(cid):
    """NULL unit splits the run from non-null."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into hub.bcct_rows
               (client_id, transaction_key, line_no, declaration_no,
                declaration_type, direction, registration_date,
                customs_code, goods_name, unit, payload)
               values (%s, 'T1', '1', 'D1', 'E11', 'import',
                       '2025-06-01', 'X3', 'd', null, '{}'::jsonb)""",
            (cid,),
        )
        _bcct(cur, client_id=cid, code="X3", decl_no="D2",
              line_no="1", date_str="2025-06-02", unit="SETS")
    t = analyze_material_timeline(client_id=cid, material_code="X3")
    ft = next(f for f in t.timelines if f.field == "unit")
    assert len(ft.runs) == 2
    assert ft.runs[0].value is None
    assert ft.runs[1].value == "SETS"


def test_multi_line_declaration_picks_modal_value(cid):
    """One declaration with 3 lines (SETS, SETS, PIECES) collapses to
    a single timeline node with the modal value SETS."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X4", decl_no="D1",
              line_no="1", date_str="2025-06-01", unit="SETS")
        _bcct(cur, client_id=cid, code="X4", decl_no="D1",
              line_no="2", date_str="2025-06-01", unit="SETS")
        _bcct(cur, client_id=cid, code="X4", decl_no="D1",
              line_no="3", date_str="2025-06-01", unit="PIECES")
    t = analyze_material_timeline(client_id=cid, material_code="X4")
    ft = next(f for f in t.timelines if f.field == "unit")
    assert len(ft.runs) == 1
    assert ft.runs[0].value == "SETS"
    assert ft.runs[0].n_declarations == 1
    assert ft.runs[0].n_lines == 3


def test_declaration_type_drift_is_tracked(cid):
    """E11 → E15 → E11 produces 3 runs on declaration_type."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X5", decl_no="D1",
              line_no="1", date_str="2025-06-01", declaration_type="E11")
        _bcct(cur, client_id=cid, code="X5", decl_no="D2",
              line_no="1", date_str="2025-07-01", declaration_type="E15")
        _bcct(cur, client_id=cid, code="X5", decl_no="D3",
              line_no="1", date_str="2025-08-01", declaration_type="E11")
    t = analyze_material_timeline(client_id=cid, material_code="X5")
    ft = next(f for f in t.timelines if f.field == "declaration_type")
    assert [r.value for r in ft.runs] == ["E11", "E15", "E11"]


def test_direction_breakdown_in_run(cid):
    """Run aggregates direction counts so the UI chip shows NK / XK
    breakdown."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X6", decl_no="D1",
              line_no="1", date_str="2025-06-01",
              direction="import", unit="SETS")
        _bcct(cur, client_id=cid, code="X6", decl_no="D2",
              line_no="1", date_str="2025-06-02",
              direction="export", declaration_type="E42", unit="SETS")
        _bcct(cur, client_id=cid, code="X6", decl_no="D3",
              line_no="1", date_str="2025-06-03",
              direction="import", unit="SETS")
    t = analyze_material_timeline(client_id=cid, material_code="X6")
    ft = next(f for f in t.timelines if f.field == "unit")
    # All 3 are SETS → 1 run with combined direction breakdown.
    assert len(ft.runs) == 1
    assert ft.runs[0].direction_breakdown == {"import": 2, "export": 1}


# ─── Quarter bucketing ────────────────────────────────────────────────


def test_quarter_buckets_span_year_boundary(cid):
    """Declarations in Q4 2025 + Q1 2026 land in separate buckets."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X7", decl_no="D1",
              line_no="1", date_str="2025-12-15",
              unit_price=10.0, quantity=100.0)
        _bcct(cur, client_id=cid, code="X7", decl_no="D2",
              line_no="1", date_str="2026-01-10",
              unit_price=12.0, quantity=110.0)
        _bcct(cur, client_id=cid, code="X7", decl_no="D3",
              line_no="1", date_str="2026-04-05",
              unit_price=13.0, quantity=120.0)
    t = analyze_material_timeline(client_id=cid, material_code="X7")
    assert [q.quarter for q in t.quarterly] == ["2025-Q4", "2026-Q1", "2026-Q2"]
    assert all(not q.price_jump_from_prev for q in t.quarterly)


def test_price_jump_flag_fires_on_2x_increase(cid):
    """Median price 10 → 25 (2.5×) flags the next quarter; 25 → 30
    (1.2×) does NOT."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X8", decl_no="D1",
              line_no="1", date_str="2025-04-15", unit_price=10.0)
        _bcct(cur, client_id=cid, code="X8", decl_no="D2",
              line_no="1", date_str="2025-07-15", unit_price=25.0)
        _bcct(cur, client_id=cid, code="X8", decl_no="D3",
              line_no="1", date_str="2025-10-15", unit_price=30.0)
    t = analyze_material_timeline(client_id=cid, material_code="X8")
    flags = {q.quarter: q.price_jump_from_prev for q in t.quarterly}
    assert flags["2025-Q2"] is False  # first quarter — no prev to compare
    assert flags["2025-Q3"] is True   # 10 → 25 = 2.5× → flag
    assert flags["2025-Q4"] is False  # 25 → 30 = 1.2× → no flag


def test_price_jump_flag_fires_on_half_drop(cid):
    """Median 100 → 40 (0.4×) also fires (outside [0.5, 2.0])."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="X9", decl_no="D1",
              line_no="1", date_str="2025-04-15", unit_price=100.0)
        _bcct(cur, client_id=cid, code="X9", decl_no="D2",
              line_no="1", date_str="2025-07-15", unit_price=40.0)
    t = analyze_material_timeline(client_id=cid, material_code="X9")
    flags = {q.quarter: q.price_jump_from_prev for q in t.quarterly}
    assert flags["2025-Q3"] is True


def test_price_jump_boundaries_inclusive(cid):
    """Exactly 2.0× and exactly 0.5× both flag as jumps. Locks in the
    `>=` / `<=` semantics so future refactors don't silently flip to
    strict inequalities."""
    with connect() as conn, conn.cursor() as cur:
        # 10 → 20 (exactly 2.0×) → should flag.
        _bcct(cur, client_id=cid, code="XB1", decl_no="D1",
              line_no="1", date_str="2025-04-15", unit_price=10.0)
        _bcct(cur, client_id=cid, code="XB1", decl_no="D2",
              line_no="1", date_str="2025-07-15", unit_price=20.0)
        # 100 → 50 (exactly 0.5×) → should flag.
        _bcct(cur, client_id=cid, code="XB2", decl_no="D3",
              line_no="1", date_str="2025-04-15", unit_price=100.0)
        _bcct(cur, client_id=cid, code="XB2", decl_no="D4",
              line_no="1", date_str="2025-07-15", unit_price=50.0)
    t1 = analyze_material_timeline(client_id=cid, material_code="XB1")
    t2 = analyze_material_timeline(client_id=cid, material_code="XB2")
    f1 = {q.quarter: q.price_jump_from_prev for q in t1.quarterly}
    f2 = {q.quarter: q.price_jump_from_prev for q in t2.quarterly}
    assert f1["2025-Q3"] is True, "ratio==2.0 should flag"
    assert f2["2025-Q3"] is True, "ratio==0.5 should flag"


def test_rle_same_day_different_values_produces_separate_runs(cid):
    """Two declarations registered the same date with different units
    each produce their own run (start_date == end_date). The
    chronological order between same-day declarations is ambiguous,
    but the RLE should not merge them silently."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="XSD", decl_no="D1",
              line_no="1", date_str="2025-06-01", unit="SETS")
        _bcct(cur, client_id=cid, code="XSD", decl_no="D2",
              line_no="1", date_str="2025-06-01", unit="PIECES")
    t = analyze_material_timeline(client_id=cid, material_code="XSD")
    ft = next(f for f in t.timelines if f.field == "unit")
    assert len(ft.runs) == 2
    assert {r.value for r in ft.runs} == {"SETS", "PIECES"}
    # Both runs are single-day.
    for r in ft.runs:
        assert r.start_date == r.end_date


def test_rle_direction_changes_split_when_value_also_differs(cid):
    """import=SETS, export=PIECES, import=SETS → 3 runs split by value
    change. Each run carries only its own direction(s)."""
    with connect() as conn, conn.cursor() as cur:
        _bcct(cur, client_id=cid, code="XDS", decl_no="D1",
              line_no="1", date_str="2025-06-01",
              direction="import", unit="SETS")
        _bcct(cur, client_id=cid, code="XDS", decl_no="D2",
              line_no="1", date_str="2025-06-02",
              direction="export", declaration_type="E42", unit="PIECES")
        _bcct(cur, client_id=cid, code="XDS", decl_no="D3",
              line_no="1", date_str="2025-06-03",
              direction="import", unit="SETS")
    t = analyze_material_timeline(client_id=cid, material_code="XDS")
    ft = next(f for f in t.timelines if f.field == "unit")
    assert [r.value for r in ft.runs] == ["SETS", "PIECES", "SETS"]
    assert ft.runs[0].direction_breakdown == {"import": 1}
    assert ft.runs[1].direction_breakdown == {"export": 1}
    assert ft.runs[2].direction_breakdown == {"import": 1}


def test_no_rows_returns_empty_timeline(cid):
    """Material code with no BCCT rows returns a well-formed empty
    timeline (callers can render the empty state safely)."""
    t = analyze_material_timeline(client_id=cid, material_code="UNKNOWN")
    assert t.n_declarations == 0
    assert all(ft.runs == [] for ft in t.timelines)
    assert t.quarterly == []
    assert not t.has_any_drift


# NOTE: bcct_rows enforces NOT NULL on `year` (generated from
# registration_date), so a null-date row cannot exist in this table.
# The `where registration_date is not null` clause in the store stays
# as defensive coding but isn't exercised by a test — the schema
# already rules it out.
