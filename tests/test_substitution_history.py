from app.substitution_history import build_substitution_history


def _case(case_code, updated_at, product_code, materials, status, overrides):
    return {
        "case_code": case_code,
        "updated_at": updated_at,
        "products": [{"code": product_code, "materials": materials}],
        "origin_sheet_states": {
            product_code: {"status": status, "material_overrides": overrides},
        },
    }


def test_locked_swap_recorded():
    cases = [_case(
        "C1", "2026-06-01", "SP1",
        [{"material_code": "B"}, {"material_code": "X"}],
        "locked",
        {"0": {"material_code": "A", "name": "Mã A"}},
    )]
    history = build_substitution_history(cases)
    assert "B" in history
    assert history["B"][0]["substitute_code"] == "A"
    assert history["B"][0]["count"] == 1
    assert history["B"][0]["name"] == "Mã A"
    assert history["B"][0]["case_codes"] == ["C1"]


def test_draft_sheet_ignored():
    cases = [_case(
        "C1", "2026-06-01", "SP1",
        [{"material_code": "B"}],
        "stale",
        {"0": {"material_code": "A"}},
    )]
    assert build_substitution_history(cases) == {}


def test_delete_and_added_rows_ignored():
    cases = [_case(
        "C1", "2026-06-01", "SP1",
        [{"material_code": "B"}],
        "locked",
        {"0": {"deleted": True}, "added_1": {"added": True, "material_code": "Z"}},
    )]
    assert build_substitution_history(cases) == {}


def test_noop_override_ignored():
    cases = [_case(
        "C1", "2026-06-01", "SP1",
        [{"material_code": "B"}],
        "locked",
        {"0": {"material_code": "B", "norm_per_unit": "2"}},
    )]
    assert build_substitution_history(cases) == {}


def test_count_and_ranking_across_cases():
    cases = [
        _case("C1", "2026-06-01", "SP1", [{"material_code": "B"}], "locked",
              {"0": {"material_code": "A"}}),
        _case("C2", "2026-06-05", "SP1", [{"material_code": "B"}], "locked",
              {"0": {"material_code": "A"}}),
        _case("C3", "2026-06-09", "SP1", [{"material_code": "B"}], "locked",
              {"0": {"material_code": "C"}}),
    ]
    history = build_substitution_history(cases)
    subs = history["B"]
    # A used twice → ranked above C used once.
    assert [s["substitute_code"] for s in subs] == ["A", "C"]
    assert subs[0]["count"] == 2
    assert subs[0]["last_used"] == "2026-06-05"
    assert sorted(subs[0]["case_codes"]) == ["C1", "C2"]


def test_out_of_range_row_index_skipped():
    cases = [_case(
        "C1", "2026-06-01", "SP1",
        [{"material_code": "B"}],
        "locked",
        {"5": {"material_code": "A"}},
    )]
    assert build_substitution_history(cases) == {}
