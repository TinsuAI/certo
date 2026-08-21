"""Tests for app.data_promotion.export_client.

Bundle format (per .ai/features/2026-05-04-data-promotion/brief.md):

  bundle.tar.gz
  ├── manifest.json    {client_id, schema_version, created_at, source, format_version}
  ├── db/NNN_<table>.sql   one file per table, ordered for FK-safe import
  └── files/<rel>          appfiles/<client_id>/* mirrored

Test client `expt-` is created per-test and torn down. Sentinel rows in
bcct_rows / materials / parser_mappings exercise the per-table scope
filtering (other clients' rows must NOT appear in the bundle).
"""
from __future__ import annotations

import json
import secrets
import tarfile
from pathlib import Path

import pytest

from hub.app.data_promotion import export_client
from hub.app.database import connect


@pytest.fixture
def isolated_client():
    cid = "expt-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.clients
              (client_id, name, code_resolution_mode, bom_proposal_mode)
            values (%s, 'Export Test', 'identity', 'auto')
            """,
            (cid,),
        )
    yield cid
    # `on delete cascade` from per-client tables → one DELETE wipes all.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _open_bundle(path: Path) -> tarfile.TarFile:
    return tarfile.open(path, "r:gz")


def _read_member(tar: tarfile.TarFile, name: str) -> str:
    f = tar.extractfile(name)
    assert f is not None, f"member {name!r} missing in bundle"
    return f.read().decode("utf-8")


def test_export_creates_targz(isolated_client, tmp_path):
    out = tmp_path / "bundle.tar.gz"

    export_client(client_id=isolated_client, out_path=out)

    assert out.exists()
    assert out.stat().st_size > 0
    with _open_bundle(out) as tar:
        names = tar.getnames()
    assert "manifest.json" in names


def test_manifest_carries_metadata(isolated_client, tmp_path):
    out = tmp_path / "bundle.tar.gz"

    export_client(client_id=isolated_client, out_path=out)

    with _open_bundle(out) as tar:
        manifest = json.loads(_read_member(tar, "manifest.json"))
    assert manifest["client_id"] == isolated_client
    assert manifest["format_version"] == 1
    assert isinstance(manifest["schema_version"], str) and manifest["schema_version"]
    assert "created_at" in manifest
    assert "source" in manifest


def test_manifest_schema_version_matches_db(isolated_client, tmp_path):
    out = tmp_path / "bundle.tar.gz"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select max(filename) from hub.schema_migrations"
        )
        (latest,) = cur.fetchone()
    assert latest is not None

    export_client(client_id=isolated_client, out_path=out)

    with _open_bundle(out) as tar:
        manifest = json.loads(_read_member(tar, "manifest.json"))
    assert manifest["schema_version"] == latest


def test_bundle_contains_client_row(isolated_client, tmp_path):
    out = tmp_path / "bundle.tar.gz"

    export_client(client_id=isolated_client, out_path=out)

    with _open_bundle(out) as tar:
        names = tar.getnames()
        # There should be a db file for hub.clients.
        clients_sql_member = next(
            (n for n in names if n.startswith("db/") and n.endswith("clients.sql")),
            None,
        )
        assert clients_sql_member, f"no clients.sql in {names}"
        body = _read_member(tar, clients_sql_member)
    assert isolated_client in body
    assert "Export Test" in body


def test_bundle_excludes_other_clients(isolated_client, tmp_path):
    other = "expt-other-" + secrets.token_hex(3)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, 'Other', 'identity', 'auto')",
            (other,),
        )
    try:
        out = tmp_path / "bundle.tar.gz"
        export_client(client_id=isolated_client, out_path=out)

        with _open_bundle(out) as tar:
            for name in tar.getnames():
                if name.startswith("db/") and name.endswith(".sql"):
                    body = _read_member(tar, name)
                    assert other not in body, (
                        f"other client {other!r} leaked into {name}"
                    )
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (other,))


def test_bundle_carries_appfiles(isolated_client, tmp_path, monkeypatch):
    files_root = tmp_path / "appfiles_src"
    # Real storage layout: {root}/{module}/{client_id}/{file}
    bcct_files = files_root / "bcct" / isolated_client
    bcct_files.mkdir(parents=True)
    sample = bcct_files / "sample.txt"
    sample.write_text("hello", encoding="utf-8")

    # File under a different client in the same module must NOT travel.
    other_files = files_root / "bcct" / "expt-other"
    other_files.mkdir(parents=True)
    (other_files / "leak.txt").write_text("nope", encoding="utf-8")

    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(files_root))

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=isolated_client, out_path=out)

    with _open_bundle(out) as tar:
        names = tar.getnames()
    assert f"files/bcct/{isolated_client}/sample.txt" in names
    assert not any("leak.txt" in n for n in names)


def test_export_refuses_unknown_client(tmp_path):
    out = tmp_path / "bundle.tar.gz"
    with pytest.raises(LookupError, match="client_id"):
        export_client(client_id="ghost-does-not-exist", out_path=out)
    assert not out.exists()
