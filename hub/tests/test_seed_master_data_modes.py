"""Tests for DATA_HUB_REFERENCE_DATA_MODE: oneshot / upsert / migration_only.

Mechanism: app.seed_master_data.seed_master_data(mode=...) reads the
mode arg or the env var. Behavior matrix:

  oneshot         existing default — seed only when target table is empty
  upsert          re-seed every call; INSERT ... ON CONFLICT DO UPDATE
  migration_only  no-op even when target is empty

Tests use a sentinel code (`ZZ99`) that does not appear in real YAML
seeds, with SEEDS_ROOT redirected to a tmp dir, so they don't pollute
the shared session DB beyond the sentinel rows (cleaned up per test).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app import seed_master_data as smd
from app.database import connect


SENTINEL_CODE = "ZZ99"


def _write_yaml(root: Path, description: str) -> None:
    (root / "declaration_types.yaml").write_text(
        textwrap.dedent(
            f"""
            declaration_types:
              - code: {SENTINEL_CODE}
                direction: import
                description: {description}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "client_type_presets.yaml").write_text("presets: []\n", encoding="utf-8")


def _delete_sentinel() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.declaration_type_catalog where code = %s",
            (SENTINEL_CODE,),
        )


def _read_sentinel_description() -> str | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select description from hub.declaration_type_catalog where code = %s",
            (SENTINEL_CODE,),
        )
        row = cur.fetchone()
        return None if row is None else row[0]


@pytest.fixture
def isolated_seeds(tmp_path, monkeypatch):
    """Redirect SEEDS_ROOT to a tmp dir; cleanup sentinel row after."""
    monkeypatch.setattr(smd, "SEEDS_ROOT", tmp_path)
    _delete_sentinel()
    yield tmp_path
    _delete_sentinel()


def test_upsert_mode_updates_existing_row(isolated_seeds):
    # Pre-existing row with one description.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.declaration_type_catalog (code, direction, description) "
            "values (%s, 'import', 'old description')",
            (SENTINEL_CODE,),
        )
    # YAML carries a different description.
    _write_yaml(isolated_seeds, description="new description from yaml")

    smd.seed_master_data(mode="upsert")

    assert _read_sentinel_description() == "new description from yaml"


def test_migration_only_mode_does_not_seed(isolated_seeds):
    _write_yaml(isolated_seeds, description="should not appear")

    smd.seed_master_data(mode="migration_only")

    assert _read_sentinel_description() is None


def test_oneshot_mode_preserves_existing_when_table_nonempty(isolated_seeds):
    # The catalog table is non-empty in the test session (conftest seeded it).
    # Insert sentinel with one description, run oneshot — sentinel should NOT
    # be replaced even though YAML differs, because oneshot only seeds when
    # the target table is empty.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.declaration_type_catalog (code, direction, description) "
            "values (%s, 'import', 'untouched')",
            (SENTINEL_CODE,),
        )
    _write_yaml(isolated_seeds, description="should be ignored")

    smd.seed_master_data(mode="oneshot")

    assert _read_sentinel_description() == "untouched"


def test_mode_from_env_when_arg_omitted(isolated_seeds, monkeypatch):
    monkeypatch.setenv("DATA_HUB_REFERENCE_DATA_MODE", "upsert")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.declaration_type_catalog (code, direction, description) "
            "values (%s, 'import', 'before')",
            (SENTINEL_CODE,),
        )
    _write_yaml(isolated_seeds, description="after")

    smd.seed_master_data()  # mode reads from env

    assert _read_sentinel_description() == "after"


def test_invalid_mode_raises(isolated_seeds):
    with pytest.raises(ValueError, match="DATA_HUB_REFERENCE_DATA_MODE"):
        smd.seed_master_data(mode="bogus")
