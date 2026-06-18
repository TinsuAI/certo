"""selected_bom_rows_by_product honors the per-client default BOM pick (#14).

Precedence: explicit product field > case-level override > client default >
aggregate composition default > latest.
"""
from __future__ import annotations

import pytest


def _workspace():
    v1_rows = [{"product_code": "P1", "material_code": "NVL-OLD", "qty_per": "1"}]
    v2_rows = [{"product_code": "P1", "material_code": "NVL-NEW", "qty_per": "1"}]
    return {
        "latest_version": {
            "version_id": "agg-1",
            "product_versions": [{"product_code": "P1", "product_version_id": "v1"}],
        },
        "versions": [
            {
                "version_id": "agg-1",
                "rows": [{"product_code": "P1", "product_version_id": "v1", "material_code": "NVL-OLD", "qty_per": "1"}],
                # composition default for P1 => v1
                "product_versions": [{"product_code": "P1", "product_version_id": "v1"}],
            }
        ],
        "latest_rows": [],
        "product_versions": [
            {"product_code": "P1", "product_version_id": "v1", "rows": v1_rows},
            {"product_code": "P1", "product_version_id": "v2", "rows": v2_rows},
        ],
        "product_version_options_by_code": {
            "P1": [
                {"product_code": "P1", "product_version_id": "v1", "rows": v1_rows},
                {"product_code": "P1", "product_version_id": "v2", "rows": v2_rows},
            ]
        },
    }


def _material(case, workspace, **kwargs):
    from app.main import selected_bom_rows_by_product
    return selected_bom_rows_by_product(case, workspace, **kwargs)["P1"][0]["material_code"]


def test_client_default_used_when_no_case_override():
    case = {"client_id": "cli", "products": [{"code": "P1", "bom_product_code": "P1"}]}
    assert _material(case, _workspace(), client_defaults={"P1": "v2"}) == "NVL-NEW"


def test_no_default_falls_back_to_composition():
    case = {"client_id": "cli", "products": [{"code": "P1", "bom_product_code": "P1"}]}
    assert _material(case, _workspace(), client_defaults={}) == "NVL-OLD"


def test_case_override_beats_client_default():
    case = {
        "client_id": "cli",
        "products": [{"code": "P1", "bom_product_code": "P1"}],
        "bom_product_artifact_overrides": {"P1": "v1"},
    }
    assert _material(case, _workspace(), client_defaults={"P1": "v2"}) == "NVL-OLD"


def test_explicit_product_field_beats_client_default():
    case = {
        "client_id": "cli",
        "products": [{"code": "P1", "bom_product_code": "P1", "bom_product_artifact_id": "v1"}],
    }
    assert _material(case, _workspace(), client_defaults={"P1": "v2"}) == "NVL-OLD"


def test_auto_reads_client_default_from_store(monkeypatch, tmp_path):
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    from app.bom_default_store import set_default
    set_default("cli", "P1", "v2")
    case = {"client_id": "cli", "products": [{"code": "P1", "bom_product_code": "P1"}]}
    # client_defaults not passed -> resolved from case["client_id"]
    assert _material(case, _workspace()) == "NVL-NEW"
