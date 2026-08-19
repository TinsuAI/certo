"""Tiêu chí: chosen once per lô hàng, inherited by every bảng kê, overridable per sheet.

Prod johnson-vn: 34 cases / 157 sheets, **no case has more than one HS**, so the
recommended criterion is identical across a case's sheets — and only 1 of 157 sheets
ever carried its own criterion. Asking the operator per sheet is 5–13 clicks for one
answer and lets two sheets of the same C/O drift apart. The file still prints the
criterion per sheet (`workbook_io` reads it per product), so the sheet remains where
it is stored; the case-level choice is what fills it.

Precedence: sheet override → case choice → engine recommendation. Only the first two
count as chosen by a person, which is what Chốt requires.

Also pinned here: with a pure tariff-shift criterion (CTH) an LVC percentage is not a
pass/fail the operator should chase, and the threshold must be re-derived from the
criterion actually in force instead of the one the recommendation left behind.
"""
from __future__ import annotations


def _case(sheet_override: str = "", case_choice: dict | None = None) -> dict:
    case = {
        "destination_market": "Canada",
        "products": [{"code": "P1", "finished_hs": "950691", "lvc_threshold": "30"}],
        "origin_sheet_states": {"P1": {"status": "calculated", "criteria_override": sheet_override}},
    }
    if case_choice is not None:
        case["criteria_choice"] = case_choice
    return case


def _product(case: dict) -> dict:
    from app.web.co_case_context import attach_origin_sheet_states
    return attach_origin_sheet_states(case)["products"][0]


def test_sheet_inherits_the_case_choice():
    product = _product(_case(case_choice={"criteria_text": "CTH", "chosen_by": "tam"}))
    assert product["origin_sheet_effective_criteria_text"] == "CTH"
    assert product["origin_sheet_criteria_source"] == "case"


def test_sheet_override_beats_the_case_choice():
    product = _product(_case(sheet_override="RVC 40%", case_choice={"criteria_text": "CTH"}))
    assert product["origin_sheet_effective_criteria_text"] == "RVC 40%"
    assert product["origin_sheet_criteria_source"] == "sheet"


def test_without_any_choice_the_source_is_the_recommendation():
    product = _product(_case())
    assert product["origin_sheet_criteria_source"] == "recommendation"


def test_case_choice_threshold_is_inherited():
    product = _product(_case(case_choice={"criteria_text": "RVC 40%", "lvc_threshold": "40"}))
    assert product["origin_sheet_effective_lvc_threshold"] == "40"


def test_threshold_is_re_derived_from_the_criterion_in_force():
    """The 30% left on the product came from the recommended CPTPP text. Choosing a
    criterion with its own percentage must not keep showing the old threshold."""
    product = _product(_case(case_choice={"criteria_text": "RVC không thấp hơn 45%"}))
    assert product["origin_sheet_effective_lvc_threshold"] == "45"


def test_a_tariff_shift_criterion_has_no_threshold_to_chase():
    product = _product(_case(case_choice={"criteria_text": "CTH"}))
    assert product["origin_sheet_effective_lvc_threshold"] == ""
    assert product["origin_sheet_criteria_family"] == "tariff_shift"
    assert product["origin_sheet_lvc_applies"] is False
    assert product["origin_sheet_ctc_applies"] is True


def test_a_value_content_criterion_applies_lvc():
    product = _product(_case(case_choice={"criteria_text": "RVC không thấp hơn 40%"}))
    assert product["origin_sheet_criteria_family"] == "value_content"
    assert product["origin_sheet_lvc_applies"] is True
    assert product["origin_sheet_ctc_applies"] is False


def test_the_cptpp_alternatives_apply_both():
    text = "CTH; hoặc RVC không thấp hơn a) 30% theo công thức tính trực tiếp"
    product = _product(_case(case_choice={"criteria_text": text}))
    assert product["origin_sheet_criteria_family"] == "mixed"
    assert product["origin_sheet_lvc_applies"] is True
    assert product["origin_sheet_ctc_applies"] is True
    assert product["origin_sheet_effective_lvc_threshold"] == "30"


def test_wholly_obtained_applies_neither():
    product = _product(_case(case_choice={"criteria_text": "WO"}))
    assert product["origin_sheet_criteria_family"] == "wholly_obtained"
    assert product["origin_sheet_lvc_applies"] is False
    assert product["origin_sheet_ctc_applies"] is False


def test_method_label_follows_the_family():
    from app.web.co_case_context import origin_method_label_for_criterion
    assert origin_method_label_for_criterion("CTH") == "Chuyển đổi mã số (CTC)"
    assert origin_method_label_for_criterion("RVC 40%") == "Build-down LVC/RVC"
    assert origin_method_label_for_criterion("WO") == "Xuất xứ thuần tuý"
    assert origin_method_label_for_criterion("") == "Build-down LVC/RVC"


# --- Chốt requires a human choice -----------------------------------------

def test_lock_gate_blocks_while_the_criterion_is_only_a_recommendation():
    from app.web.co_case_context import origin_sheet_action_error
    error = origin_sheet_action_error(_case(), "P1", "lock")
    assert "tiêu chí" in error.lower()


def test_lock_gate_passes_the_criterion_check_once_the_case_chose():
    from app.web.co_case_context import origin_sheet_action_error
    error = origin_sheet_action_error(_case(case_choice={"criteria_text": "CTH"}), "P1", "lock")
    assert "tiêu chí" not in error.lower()


def test_calculate_is_never_blocked_by_a_missing_criterion():
    """Tính is exploratory — the criterion only decides the threshold and the preview."""
    from app.web.co_case_context import origin_sheet_action_error
    assert origin_sheet_action_error(_case(), "P1", "calculate") == ""


def test_clearing_the_case_choice_persists(monkeypatch, tmp_path):
    """"Bỏ chọn" used to do nothing: the route popped `criteria_choice` off the case
    dict, and `update_case_record` only copies keys that are PRESENT in the incoming
    case, so the stored choice survived every clear (reported 2026-08-19)."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)

    from app import co_case_store
    from app.demo_data import get_client

    case_id = "case-criteria-clear"
    now = co_case_store.now_iso()
    co_case_store.save_state("growatt", {"schema_version": 1, "client_id": "growatt", "cases": [{
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-CRIT", "title": "Crit", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "products": [{"code": "PV.A", "name": "SP A", "materials": []}],
    }]})

    client = TestClient(main_module.app)
    url = f"/clients/growatt/co-case/{case_id}/origin/case-criteria"

    assert client.post(url, json={"criteria_text": "CTH"}).status_code == 200
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["criteria_choice"]["criteria_text"] == "CTH"

    assert client.post(url, json={"criteria_text": ""}).status_code == 200
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert not (record.get("criteria_choice") or {}).get("criteria_text")

    from app.web.co_case_context import case_criteria_choice
    assert case_criteria_choice(record) == {}
