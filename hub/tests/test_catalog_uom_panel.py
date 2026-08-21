"""A.4.4 — catalog detail UoM panel: 4-state chip classification.

`build_uom_panel` annotates each observed UoM chip (BCCT + BOM) with a
`state` driven by `classify_uom_relation`, replacing the old binary
`are_equivalent` divergence cue.

  equivalent   — same canonical (muted, no action)
  convertible  — converts cleanly, confirmed factor ("quy đổi ×N")
  unconfirmed  — tier-A 1:1 guess (amber "cần xác nhận")
  incompatible — no factor (warn → /uom-factors or /admin/uom)
"""
from __future__ import annotations

import pytest

from hub.app.stores.catalog_uom_panel import build_uom_panel

CLIENT = "_uom_panel_test"


def test_alias_chip_is_equivalent():
    panel = build_uom_panel(
        client_id=CLIENT, material_code="M1", official="pcs",
        uom_bcct=[{"unit": "pieces", "n_rows": 3, "n_decls": 2}],
        uom_bom=[{"uom": "pcs", "n_edges": 5}],
    )
    assert panel["bcct"][0]["state"] == "equivalent"
    assert panel["bom"][0]["state"] == "equivalent"
    assert panel["needs_attention"] is False


def test_same_family_chip_is_convertible_with_factor():
    panel = build_uom_panel(
        client_id=CLIENT, material_code="M1", official="kg",
        uom_bcct=[{"unit": "g", "n_rows": 1, "n_decls": 1}], uom_bom=[],
    )
    chip = panel["bcct"][0]
    assert chip["state"] == "convertible"
    assert chip["factor"] == "0.001"
    assert panel["needs_attention"] is False  # converts cleanly, no action


def test_tier_a_chip_is_unconfirmed():
    panel = build_uom_panel(
        client_id=CLIENT, material_code="M1", official="SETS",
        uom_bcct=[{"unit": "EA", "n_rows": 1, "n_decls": 1}], uom_bom=[],
    )
    assert panel["bcct"][0]["state"] == "unconfirmed"
    assert panel["needs_attention"] is True  # 1:1 guess needs confirmation


def test_crossfamily_chip_is_incompatible_add_factor():
    panel = build_uom_panel(
        client_id=CLIENT, material_code="M1", official="pcs",
        uom_bcct=[{"unit": "kg", "n_rows": 1, "n_decls": 1}], uom_bom=[],
    )
    chip = panel["bcct"][0]
    assert chip["state"] == "incompatible"
    assert chip["remediation"] == "add_factor"
    assert panel["needs_attention"] is True


def test_unknown_token_is_incompatible_add_alias():
    panel = build_uom_panel(
        client_id=CLIENT, material_code="M1", official="pcs",
        uom_bcct=[{"unit": "ZZZ", "n_rows": 1, "n_decls": 1}], uom_bom=[],
    )
    assert panel["bcct"][0]["state"] == "incompatible"
    assert panel["bcct"][0]["remediation"] == "add_alias"


def test_no_official_uom_no_divergence():
    panel = build_uom_panel(
        client_id=CLIENT, material_code="M1", official=None,
        uom_bcct=[{"unit": "kg", "n_rows": 1, "n_decls": 1}], uom_bom=[],
    )
    assert panel["bcct"][0]["state"] == "equivalent"
    assert panel["has_divergence"] is False
