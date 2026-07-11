"""VN-origin ticket #13: dncx preset gains E13; the client-config form shows
per-declaration-type BCCT counts and warns (non-blocking) when the configured
eligible list excludes a type present in the client's data — the mistake that
silently drops on-spot lots and produces false shortages.
"""
from __future__ import annotations

from app.bcct_aggregates import declaration_type_counts, excluded_types_with_rows, supplier_type_summary
from app.client_config_store import DECLARATION_TYPE_PRESETS


def test_dncx_preset_includes_e13():
    assert DECLARATION_TYPE_PRESETS["dncx"]["eligible_import_declaration_types"] == ["E11", "E13", "E15"]


def test_manual_preset_still_means_no_filter():
    assert DECLARATION_TYPE_PRESETS["manual"]["eligible_import_declaration_types"] == []


def test_declaration_type_counts_weigh_aggregated_lots_by_source_lines():
    rows = [
        {"declaration_type": "E11"},
        {"declaration_type": "E13", "source_line_ids": ["a", "b", "c"]},
        {"declaration_type": "E13"},
        {"declaration_type": ""},
    ]
    assert declaration_type_counts(rows) == {"?": 1, "E11": 1, "E13": 4}


def test_excluded_types_only_when_filter_active():
    counts = {"E11": 5, "E13": 10, "E15": 2}
    assert excluded_types_with_rows(counts, []) == []  # empty list = no filter
    assert excluded_types_with_rows(counts, None) == []
    assert excluded_types_with_rows(counts, ["E11", "E15"]) == [("E13", 10)]
    assert excluded_types_with_rows(counts, ["E11", "E13", "E15"]) == []


def test_excluded_types_ignore_unknown_bucket():
    assert excluded_types_with_rows({"?": 3, "E11": 1}, ["E11"]) == []


def test_supplier_type_summary_groups_by_normalized_key():
    rows = [
        {"consignee_name": "MYS GROUP(VIET NAM)", "declaration_type": "E15", "origin_country": "VIETNAM"},
        {"consignee_name": "MYS GROUP (VIET NAM)", "declaration_type": "E13", "origin_country": "VIETNAM"},
        {"consignee_name": "MINGJIE INDUSTRIAL (HK) LIMITED", "declaration_type": "E13", "origin_country": "CHINA"},
        {"consignee_name": ""},
    ]
    summary = supplier_type_summary(rows)
    assert [entry["supplier_key"] for entry in summary] == [
        "MYS GROUP (VIET NAM)",
        "MINGJIE INDUSTRIAL (HK) LIMITED",
    ]
    mys = summary[0]
    assert mys["row_count"] == 2
    assert mys["type_counts"] == {"E15": 1, "E13": 1}
    assert mys["origin_counts"] == {"VIETNAM": 2}
    assert mys["names"] == ["MYS GROUP(VIET NAM)", "MYS GROUP (VIET NAM)"]


def test_config_page_shows_counts_and_exclusion_warning(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app import co_stock_materializer
    from app.client_config_store import get_client_config, save_client_config
    from app.demo_data import get_client

    client_record = get_client("do-thanh")
    config = get_client_config(client_record)
    config["bcct"]["eligible_import_declaration_types"] = ["E11", "E15"]
    save_client_config(client_record, config)

    rows = [
        {"declaration_type": "E11"},
        {"declaration_type": "E13"},
        {"declaration_type": "E13"},
    ]
    monkeypatch.setattr(co_stock_materializer, "read_co_stock_rows_cached", lambda client_id: list(rows))
    client = TestClient(main_module.app)
    page = client.get("/clients/do-thanh/config")
    assert page.status_code == 200
    assert "data-bcct-type-counts" in page.text
    assert "E13: 2 dòng" in page.text
    assert "data-bcct-excluded-warning" in page.text
    assert "E13 (2 dòng)" in page.text


def test_save_message_carries_exclusion_warning(monkeypatch):
    from app.routers.pages import declaration_type_exclusion_warning
    from app import co_stock_materializer

    monkeypatch.setattr(
        co_stock_materializer,
        "read_co_stock_rows_cached",
        lambda client_id: [{"declaration_type": "E13"}, {"declaration_type": "E13"}],
    )
    warning = declaration_type_exclusion_warning(
        {"id": "do-thanh"},
        {"bcct": {"eligible_import_declaration_types": ["E11", "E15"]}},
    )
    assert "E13" in warning
    assert "2 dòng" in warning
    clean = declaration_type_exclusion_warning(
        {"id": "do-thanh"},
        {"bcct": {"eligible_import_declaration_types": []}},
    )
    assert clean == ""
