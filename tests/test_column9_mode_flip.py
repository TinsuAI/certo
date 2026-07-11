"""Column-9 mode flip lifecycle (VN-origin ticket #10).

Flipping the mode — per-case override or client default — can never leave a
dossier silently mixing two conventions: mismatched `calculated` sheets go
stale (re-Tính applies the new convention), `draft`/`bom_loaded` are untouched,
locked sheets are NEVER modified (mismatch chip + warning instead — their
snapshot is what was filed). The lock gate and export blockers re-check the
materialized mode stamp, so the save-route status hardcode cannot bypass it.
"""
from __future__ import annotations

from app.web.co_case_context import (
    apply_column9_mode_flip,
    attach_column9_mode_mismatch,
    column9_mode_mismatches,
    origin_sheet_action_error,
    origin_sheet_export_blockers,
)


def _case(statuses: dict[str, str], materialized_mode: str = "country", override: str = "qualification_label") -> dict:
    return {
        "bang_ke_column9_mode_override": override,
        "products": [
            {"code": code, "bang_ke_column9_mode": materialized_mode, "lvc_status": "pass",
             "materials": [{"material_code": "M1", "material_sequence": "1"}]}
            for code in statuses
        ],
        "origin_sheet_states": {code: {"status": status} for code, status in statuses.items()},
    }


def test_mismatches_report_only_diverging_sheets():
    case = _case({"P1": "calculated", "P2": "locked"})
    entries = column9_mode_mismatches(case, {})
    assert {(entry["code"], entry["status"]) for entry in entries} == {("P1", "calculated"), ("P2", "locked")}
    # same mode → no mismatch
    aligned = _case({"P1": "calculated"}, materialized_mode="qualification_label")
    assert column9_mode_mismatches(aligned, {}) == []
    # sheet never materialized (pre-feature) → not a mismatch
    fresh = _case({"P1": "calculated"}, materialized_mode="")
    assert column9_mode_mismatches(fresh, {}) == []


def test_flip_marks_calculated_stale_leaves_draft_and_locked():
    case = _case({"P1": "calculated", "P2": "draft", "P3": "bom_loaded", "P4": "locked"})
    flip = apply_column9_mode_flip(case, {})
    assert flip["stale_codes"] == ["P1"]
    assert flip["locked_codes"] == ["P4"]
    states = flip["case"]["origin_sheet_states"]
    assert states["P1"]["status"] == "stale"
    assert states["P2"]["status"] == "draft"
    assert states["P3"]["status"] == "bom_loaded"
    assert states["P4"]["status"] == "locked"


def test_lock_gate_blocks_mode_mismatch_even_when_status_calculated():
    case = _case({"P1": "calculated"})
    error = origin_sheet_action_error(case, "P1", "lock", {})
    assert "quy ước" in error
    # without client context (legacy callers) the check is skipped, not crashed
    assert origin_sheet_action_error(case, "P1", "lock") == ""


def test_export_blockers_include_mismatched_unlocked_but_not_locked():
    case = _case({"P1": "calculated", "P2": "locked"})
    blockers = origin_sheet_export_blockers(case, {})
    assert "P1" in blockers
    assert "P2" not in blockers


def test_attach_chip_flags_locked_sheet_without_mutating_it():
    case = _case({"P1": "locked"})
    before = dict(case["origin_sheet_states"]["P1"])
    attached = attach_column9_mode_mismatch(case, {})
    assert attached["products"][0]["bang_ke_column9_mode_mismatch"] is True
    assert case["origin_sheet_states"]["P1"] == before


def test_flip_route_previews_then_applies(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app import co_case_store

    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    now = co_case_store.now_iso()
    case = {
        "id": "case-flip-1", "persisted_case_id": "case-flip-1", "case_id": "case-flip-1",
        "case_code": "CO-FLIP", "title": "Flip", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open", "created_at": now, "updated_at": now,
        "origin_product_order": ["P1", "P2"],
        "products": [
            {"code": "P1", "name": "SP1", "fob": "100", "quantity": "1",
             "bang_ke_column9_mode": "country", "materials": []},
            {"code": "P2", "name": "SP2", "fob": "100", "quantity": "1",
             "bang_ke_column9_mode": "country", "materials": []},
        ],
        "origin_sheet_states": {"P1": {"status": "calculated"}, "P2": {"status": "locked"}},
    }
    co_case_store.save_state("growatt", {"schema_version": 1, "client_id": "growatt", "cases": [case]})
    client = TestClient(main_module.app)
    url = "/clients/growatt/co-case/case-flip-1/origin/column9-mode"

    preview = client.post(url, json={"mode": "qualification_label", "preview": True}).json()
    assert preview["stale_codes"] == ["P1"]
    assert preview["locked_mismatch_codes"] == ["P2"]
    # preview persisted nothing
    from app.demo_data import get_client
    record = co_case_store.get_case_record(get_client("growatt"), "case-flip-1")
    assert record["origin_sheet_states"]["P1"]["status"] == "calculated"

    applied = client.post(url, json={"mode": "qualification_label"}).json()
    assert applied["stale_codes"] == ["P1"]
    record = co_case_store.get_case_record(get_client("growatt"), "case-flip-1")
    assert record["origin_sheet_states"]["P1"]["status"] == "stale"
    assert record["origin_sheet_states"]["P2"]["status"] == "locked"
    assert record["bang_ke_column9_mode_override"] == "qualification_label"

    # clearing the override flips back to the client default (country) — P1 is
    # stale (untouched by flips), P2 stays locked
    cleared = client.post(url, json={"mode": ""}).json()
    assert cleared["mode"] == ""
    record = co_case_store.get_case_record(get_client("growatt"), "case-flip-1")
    assert record["bang_ke_column9_mode_override"] == ""

    bogus = client.post(url, json={"mode": "bogus"})
    assert bogus.status_code == 400


def test_materializer_never_restamps_locked_sheets():
    # A Tính on any other sheet persists the WHOLE case — the locked sheet's
    # as-filed column-9 text and mode stamp must survive it (and keep the chip).
    from app.web.co_case_context import materialize_bang_ke_origin_fields

    locked_material = {
        "material_code": "M1", "material_sequence": "1",
        "origin_country": "CHINA", "bang_ke_origin_text": "Trung Quốc",
        "allocation_lines": [{"origin_country": "CHINA", "bang_ke_origin_text": "Trung Quốc"}],
    }
    case = {
        "bang_ke_column9_mode_override": "qualification_label",
        "products": [
            {"code": "P1", "bang_ke_column9_mode": "country", "materials": [locked_material]},
            {"code": "P2", "bang_ke_column9_mode": "country",
             "materials": [{"material_code": "M2", "origin_country": "CHINA", "allocation_lines": []}]},
        ],
        "origin_sheet_states": {"P1": {"status": "locked"}, "P2": {"status": "calculated"}},
    }
    out = materialize_bang_ke_origin_fields(case, {})
    locked, unlocked = out["products"][0], out["products"][1]
    assert locked["bang_ke_column9_mode"] == "country"  # as filed
    assert locked["materials"][0]["bang_ke_origin_text"] == "Trung Quốc"
    assert locked["materials"][0]["allocation_lines"][0]["bang_ke_origin_text"] == "Trung Quốc"
    assert unlocked["bang_ke_column9_mode"] == "qualification_label"
    assert unlocked["materials"][0]["bang_ke_origin_text"] == "Không xuất xứ"
    # and the chip material stays intact
    assert column9_mode_mismatches(out, {}) != []


def test_recalc_after_flip_clears_the_mismatch():
    # A stale mismatched sheet re-Tính'd under the new mode re-materializes and
    # stops being a mismatch — the loop closes.
    from app.web.co_case_context import materialize_bang_ke_origin_fields

    case = _case({"P1": "calculated"})
    flip = apply_column9_mode_flip(case, {})
    assert flip["stale_codes"] == ["P1"]
    rematerialized = materialize_bang_ke_origin_fields(flip["case"], {})
    assert column9_mode_mismatches(rematerialized, {}) == []
