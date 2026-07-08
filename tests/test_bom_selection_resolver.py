"""BOM version selection: one precedence resolver, honoured by BOTH the snapshot
writer and the per-sheet row selector.

Precedence (ADR 2026-07-08): explicit pin (case override) > client default >
DH aggregate composition > DH latest usable. A pinned/client-default version is
honoured even after DH publishes a newer one.

Regression target: `attach_case_bom_snapshot` used to run first with NO
client-default step and *write* `product.bom_product_artifact_id`, shadowing the
client-default layer of `selected_bom_rows_by_product`.
"""
from __future__ import annotations

import pytest


def _v(code, vid, no, material):
    return {
        "product_code": code,
        "product_version_id": vid,
        "product_artifact_id": vid,
        "product_version_no": no,
        "product_artifact_no": no,
        "version_hash": f"hash-{vid}",
        "row_count": 1,
        "status": "current",
        "rows": [{"product_code": code, "material_code": material, "qty_per": "1"}],
    }


def _workspace():
    """P1 has usable v1 (composition default) and v2 (newer, unpinned)."""
    v1 = _v("P1", "v1", 1, "NVL-OLD")
    v2 = _v("P1", "v2", 2, "NVL-NEW")
    return {
        "latest_version": {
            "version_id": "agg-1",
            "artifact_id": "agg-1",
            "product_versions": [{"product_code": "P1", "product_version_id": "v1"}],
        },
        "versions": [
            {
                "version_id": "agg-1",
                "artifact_id": "agg-1",
                "rows": [],
                # composition default for P1 => v1
                "product_versions": [{"product_code": "P1", "product_version_id": "v1"}],
            }
        ],
        "latest_rows": [],
        "product_versions": [v1, v2],
        "product_version_options_by_code": {"P1": [v1, v2]},
    }


@pytest.fixture
def default_store(monkeypatch, tmp_path):
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    from app.bom_default_store import set_default
    return set_default


def test_snapshot_pins_client_default_over_composition(default_store):
    """The snapshot writer must honour the client default, not silently pin the
    DH composition/latest version (the shadowing bug)."""
    from app.bom_store import attach_case_bom_snapshot

    default_store("cli", "P1", "v2")  # staff pinned v2 as the client default
    case = {"client_id": "cli", "products": [{"code": "P1", "bom_product_code": "P1"}]}

    attached = attach_case_bom_snapshot(case, _workspace())

    assert attached["products"][0]["bom_product_artifact_id"] == "v2"


def _versions(case, client_defaults=None):
    from app.web.co_case_context import selected_bom_versions_by_product
    return selected_bom_versions_by_product(case, _workspace(), client_defaults=client_defaults)["P1"]


def test_versions_reports_client_default_source(default_store):
    default_store("cli", "P1", "v2")
    case = {"client_id": "cli", "products": [{"code": "P1", "bom_product_code": "P1"}]}
    picked = _versions(case)
    assert picked["version_id"] == "v2"
    assert picked["version_no"] == 2
    assert picked["source"] == "client_default"


def test_versions_reports_case_override_source():
    case = {
        "client_id": "cli",
        "products": [{"code": "P1", "bom_product_code": "P1"}],
        "bom_product_artifact_overrides": {"P1": "v1"},
    }
    picked = _versions(case, client_defaults={"P1": "v2"})
    assert picked["version_id"] == "v1"
    assert picked["source"] == "case_override"


def test_versions_reports_composition_source_when_no_default():
    case = {"client_id": "cli", "products": [{"code": "P1", "bom_product_code": "P1"}]}
    picked = _versions(case, client_defaults={})
    assert picked["version_id"] == "v1"  # composition default
    assert picked["source"] == "dh_composition"


def test_versions_ignores_snapshot_echo(default_store):
    """The 'why' label must not read the snapshot echo as a user pick: a product
    carrying a stamped bom_product_artifact_id (but no case override) still reports
    the real precedence winner (client default), not 'you picked it'."""
    default_store("cli", "P1", "v2")
    case = {
        "client_id": "cli",
        # echo of a prior snapshot write, NOT an explicit pick (not in overrides):
        "products": [{"code": "P1", "bom_product_code": "P1", "bom_product_artifact_id": "v1"}],
    }
    picked = _versions(case)
    assert picked["version_id"] == "v2"
    assert picked["source"] == "client_default"


# --------------------------------------------------------------------------- #
# Precedence WITH usability: a higher-precedence pick that is unusable must not #
# shadow a lower-precedence usable one (code-review finding, 2026-07-08).       #
# --------------------------------------------------------------------------- #
def _uv(vid, no, *, usable):
    """A P1 product version. usable=False => empty rows, so the resolver skips it."""
    return {
        "product_code": "P1",
        "product_version_id": vid,
        "product_artifact_id": vid,
        "product_version_no": no,
        "rows": [{"product_code": "P1", "material_code": "M", "qty_per": "1"}] if usable else [],
    }


def _resolver_inputs(**over):
    stale = _uv("v_stale", 1, usable=False)
    good = _uv("v_good", 3, usable=True)
    latest = _uv("v_latest", 9, usable=True)
    inputs = dict(
        overrides={},
        client_defaults={},
        composition_ids={},
        version_index={"v_stale": stale, "v_good": good, "v_latest": latest},
        bom_workspace={"product_versions": [stale, good, latest]},
        bom_product_code="P1",
    )
    inputs.update(over)
    return inputs


def test_unusable_pin_falls_through_to_client_default_not_latest():
    """(c) regression: a stale-but-set pin echo pointing at an unusable version must
    NOT shadow a valid client_default and drop straight to dh_latest."""
    from app.bom_store import resolve_selected_product_version
    product = {"code": "P1", "bom_product_code": "P1", "bom_product_artifact_id": "v_stale"}
    version, source = resolve_selected_product_version(
        product, honor_product_pin=True, **_resolver_inputs(client_defaults={"P1": "v_good"}),
    )
    assert source == "client_default"
    assert version["product_version_id"] == "v_good"


def test_unusable_case_override_does_not_shadow_client_default():
    """Same rule one level down: an unusable case_override must fall through to a
    usable client_default, not to dh_latest."""
    from app.bom_store import resolve_selected_product_version
    product = {"code": "P1", "bom_product_code": "P1"}
    version, source = resolve_selected_product_version(
        product, honor_product_pin=False,
        **_resolver_inputs(overrides={"P1": "v_stale"}, client_defaults={"P1": "v_good"}),
    )
    assert source == "client_default"
    assert version["product_version_id"] == "v_good"


def test_usable_pin_still_wins():
    """Positive control: a usable pin echo is still honoured first (backward compat),
    even when a client_default points elsewhere."""
    from app.bom_store import resolve_selected_product_version
    product = {"code": "P1", "bom_product_code": "P1", "bom_product_artifact_id": "v_good"}
    version, source = resolve_selected_product_version(
        product, honor_product_pin=True, **_resolver_inputs(client_defaults={"P1": "v_latest"}),
    )
    assert source == "pin"
    assert version["product_version_id"] == "v_good"
