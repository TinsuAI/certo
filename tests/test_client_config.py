"""Piece 1 of Hướng B: hub.client_config + presets + declaration catalog.

Integration tests against Postgres. Stores live in app/stores/. See
.ai/features/2026-05-02-client-config-refactor-and-contract-versioning.md
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.stores import client_config, client_type_presets, declaration_types


@pytest.fixture
def test_client():
    cid = "ccfg-" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients
                  (client_id, name, code_resolution_mode, bom_proposal_mode)
                values (%s, 'CC Test', 'identity', 'auto')
                """,
                (cid,),
            )
    yield cid
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.client_config where client_id = %s", (cid,))
            cur.execute("delete from hub.clients where client_id = %s", (cid,))


def test_seed_loaded_declaration_types():
    rows = declaration_types.list_all()
    codes = {r["code"] for r in rows}
    # Spot-check the canonical preset codes are present after seed.
    assert {"E11", "E15", "E31", "E42", "E62", "E21", "E52"} <= codes
    assert all(r["direction"] in ("import", "export") for r in rows)


def test_seed_loaded_presets():
    presets = client_type_presets.list_all()
    keys = {p["preset_key"] for p in presets}
    assert {"dncx", "sxxk", "gia_cong", "manual"} <= keys
    dncx = client_type_presets.get("dncx")
    assert dncx is not None
    assert dncx["is_system"] is True
    assert "E11" in dncx["default_eligible_import"]
    assert "E42" in dncx["default_relevant_export"]


def test_declaration_types_filter_by_direction():
    imports = declaration_types.list_all(direction="import")
    exports = declaration_types.list_all(direction="export")
    assert all(r["direction"] == "import" for r in imports)
    assert all(r["direction"] == "export" for r in exports)


def test_declaration_types_create_and_disable():
    code = f"X{secrets.token_hex(2).upper()[:3]}"  # unique test code
    try:
        created = declaration_types.create(
            code=code, direction="import", description="test code"
        )
        assert created["code"] == code
        assert created["is_active"] is True
        updated = declaration_types.update(code, is_active=False)
        assert updated is not None
        assert updated["is_active"] is False
        actives = declaration_types.list_all(only_active=True)
        assert code not in {r["code"] for r in actives}
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from hub.declaration_type_catalog where code = %s",
                    (code,),
                )


def test_system_preset_cannot_be_deleted():
    with pytest.raises(ValueError, match="System presets"):
        client_type_presets.delete("dncx")


def test_user_preset_lifecycle():
    key = "test-" + secrets.token_hex(3)
    try:
        created = client_type_presets.create(
            preset_key=key,
            display_name="Test preset",
            default_eligible_import=["a11", " e11 "],
            default_relevant_export=["b11"],
        )
        assert created["is_system"] is False
        # Whitespace + case normalized.
        assert created["default_eligible_import"] == ["A11", "E11"]
        deleted = client_type_presets.delete(key)
        assert deleted is True
        assert client_type_presets.get(key) is None
    finally:
        # Defensive cleanup if the assertion path didn't run delete.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from hub.client_type_presets where preset_key = %s",
                    (key,),
                )


def test_client_config_get_or_default(test_client):
    default = client_config.get_or_default(test_client)
    assert default["client_id"] == test_client
    assert default["preset_key"] is None
    assert default["eligible_import_declaration_types"] == []
    assert default["config_version"] == 0
    assert default["config_hash"]  # populated even for the virtual default


def test_client_config_upsert_bumps_version_and_hash(test_client):
    first = client_config.upsert(
        client_id=test_client,
        preset_key=None,
        eligible_import_declaration_types=["E11"],
        relevant_export_declaration_types=["E42"],
        fiscal_year_start_month=1,
    )
    assert first["config_version"] == 1
    second = client_config.upsert(
        client_id=test_client,
        preset_key=None,
        eligible_import_declaration_types=["E11", "E15"],
        relevant_export_declaration_types=["E42"],
    )
    assert second["config_version"] == 2
    assert second["config_hash"] != first["config_hash"]


def test_client_config_noop_save_does_not_bump_version(test_client):
    first = client_config.upsert(
        client_id=test_client,
        preset_key=None,
        eligible_import_declaration_types=["E11"],
        relevant_export_declaration_types=["E42"],
    )
    second = client_config.upsert(
        client_id=test_client,
        preset_key=None,
        eligible_import_declaration_types=["E11"],
        relevant_export_declaration_types=["E42"],
    )
    assert first["config_version"] == second["config_version"] == 1
    assert first["config_hash"] == second["config_hash"]


def test_client_config_normalizes_input(test_client):
    row = client_config.upsert(
        client_id=test_client,
        preset_key=None,
        eligible_import_declaration_types=[" e11 ", "E11", "e15"],  # dup + case + space
        relevant_export_declaration_types=["E42"],
    )
    assert row["eligible_import_declaration_types"] == ["E11", "E15"]


def test_apply_preset_snapshots_defaults(test_client):
    row = client_config.apply_preset(test_client, "dncx")
    assert row["preset_key"] == "dncx"
    # dncx defaults from seed: import E11/E15, export E42.
    assert set(row["eligible_import_declaration_types"]) == {"E11", "E15"}
    assert set(row["relevant_export_declaration_types"]) == {"E42"}


def test_apply_preset_does_not_cascade(test_client):
    """Editing a preset after a client snapshot does not change the client."""
    # Seed-then-snapshot.
    client_config.apply_preset(test_client, "sxxk")
    snap = client_config.get(test_client)
    assert set(snap["eligible_import_declaration_types"]) == {"E31"}

    # Edit the preset to add A12. Existing client must NOT change.
    test_key = "snap-test-" + secrets.token_hex(3)
    try:
        client_type_presets.create(
            preset_key=test_key,
            display_name="Snap test",
            default_eligible_import=["E11"],
            default_relevant_export=["E42"],
        )
        client_config.apply_preset(test_client, test_key)
        assert client_config.get(test_client)["eligible_import_declaration_types"] == ["E11"]
        client_type_presets.update(
            test_key,
            default_eligible_import=["E11", "A12"],
        )
        # Client unchanged (snapshot semantics).
        still = client_config.get(test_client)
        assert still["eligible_import_declaration_types"] == ["E11"]
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.client_config set preset_key = null where preset_key = %s",
                    (test_key,),
                )
                cur.execute(
                    "delete from hub.client_type_presets where preset_key = %s",
                    (test_key,),
                )


def test_fiscal_year_validation(test_client):
    with pytest.raises(ValueError, match="fiscal_year_start_month"):
        client_config.upsert(
            client_id=test_client,
            preset_key=None,
            eligible_import_declaration_types=[],
            relevant_export_declaration_types=[],
            fiscal_year_start_month=13,
        )


def test_apply_preset_then_manual_edit_clears_preset(test_client):
    """User flow: apply a preset, then manually save → preset_key clears.

    The store-level upsert with preset_key=None is what the UI route
    `POST /clients/{id}/declaration-config` does on every manual save.
    """
    client_config.apply_preset(test_client, "dncx")
    assert client_config.get(test_client)["preset_key"] == "dncx"

    # Simulate the manual save path (route hardcodes preset_key=None).
    client_config.upsert(
        client_id=test_client,
        preset_key=None,
        eligible_import_declaration_types=["E11", "E15", "A12"],  # added a code
        relevant_export_declaration_types=["E42"],
    )
    after = client_config.get(test_client)
    assert after["preset_key"] is None
    assert "A12" in after["eligible_import_declaration_types"]


def test_to_api_payload_shape(test_client):
    row = client_config.upsert(
        client_id=test_client,
        preset_key="dncx",
        eligible_import_declaration_types=["E11"],
        relevant_export_declaration_types=["E42"],
        fiscal_year_start_month=4,
    )
    payload = client_config.to_api_payload(row)
    assert set(payload.keys()) == {
        "schema_version", "client_id", "preset_key",
        "eligible_import_declaration_types",
        "relevant_export_declaration_types",
        "fiscal_year_start_month",
        "config_version", "config_hash",
    }
    assert payload["fiscal_year_start_month"] == 4
    assert payload["preset_key"] == "dncx"
