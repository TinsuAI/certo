"""Tests for app.data_promotion.import_client_bundle.

Covers:
- export → wipe → import roundtrip preserves the client subgraph
- schema_version mismatch refuses (no partial write)
- format_version mismatch refuses
- replace-mode wipes existing rows for the target client_id
- other clients on the target deployment are untouched
- files under appfiles/ are restored under the correct module/client path
"""
from __future__ import annotations

import json
import secrets
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

from app.data_promotion import (
    CorruptBundle,
    SchemaVersionMismatch,
    UnsupportedBundleFormat,
    export_client,
    import_client_bundle,
)
from app.database import connect


@pytest.fixture
def client_with_data():
    cid = "imp-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, 'Import Test', 'identity', 'auto')",
            (cid,),
        )
        cur.execute(
            "insert into hub.materials (client_id, material_code, "
            "name, category, status) values (%s, 'CUST-1', 'Widget', 'nvl', 'active')",
            (cid,),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _client_summary(cid: str) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select name from hub.clients where client_id = %s", (cid,))
        client_row = cur.fetchone()
        cur.execute(
            "select material_code, name, category "
            "from hub.materials where client_id = %s order by material_code",
            (cid,),
        )
        materials = cur.fetchall()
    return {"client": client_row, "materials": materials}


def test_roundtrip_preserves_client_data(client_with_data, tmp_path):
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)
    before = _client_summary(client_with_data)

    # Wipe the client (cascades).
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (client_with_data,))
    assert _client_summary(client_with_data) == {"client": None, "materials": []}

    import_client_bundle(bundle_path=out)

    after = _client_summary(client_with_data)
    assert after == before


def test_replace_mode_wipes_existing_client_rows(client_with_data, tmp_path):
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    # Mutate target before import — replace mode must drop the local change.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, "
            "name, category, status) values (%s, 'EXTRA', 'Stale', 'nvl', 'active')",
            (client_with_data,),
        )
        cur.execute(
            "update hub.clients set name = 'Mutated Locally' where client_id = %s",
            (client_with_data,),
        )

    import_client_bundle(bundle_path=out)

    summary = _client_summary(client_with_data)
    # The 'EXTRA' material added on the target should be gone (replace).
    assert all(m[0] != "EXTRA" for m in summary["materials"])
    # The client name should be the bundle's value, not the local mutation.
    assert summary["client"][0] == "Import Test"


def test_other_client_untouched(client_with_data, tmp_path):
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    bystander = "imp-bystander-" + secrets.token_hex(3)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, 'Bystander', 'identity', 'auto')",
            (bystander,),
        )
        cur.execute(
            "insert into hub.materials (client_id, material_code, "
            "name, category, status) values (%s, 'BY-1', 'Bystander Mat', 'nvl', 'active')",
            (bystander,),
        )
    try:
        import_client_bundle(bundle_path=out)

        with connect() as conn, conn.cursor() as cur:
            cur.execute("select name from hub.clients where client_id = %s", (bystander,))
            assert cur.fetchone()[0] == "Bystander"
            cur.execute(
                "select count(*) from hub.materials where client_id = %s",
                (bystander,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (bystander,))


def test_schema_version_mismatch_refuses(client_with_data, tmp_path):
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)
    forged = tmp_path / "forged.tar.gz"
    _rewrite_manifest(out, forged, schema_version="999_does_not_exist.sql")

    # Wipe to confirm import refuses cleanly without partial writes.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (client_with_data,))

    with pytest.raises(SchemaVersionMismatch):
        import_client_bundle(bundle_path=forged)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select 1 from hub.clients where client_id = %s", (client_with_data,))
        assert cur.fetchone() is None  # nothing leaked through despite the failed import


def test_unsupported_format_version_refuses(client_with_data, tmp_path):
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)
    forged = tmp_path / "forged.tar.gz"
    _rewrite_manifest(out, forged, format_version=999)

    with pytest.raises(UnsupportedBundleFormat):
        import_client_bundle(bundle_path=forged)


def test_roundtrip_with_array_columns(client_with_data, tmp_path):
    """Regression: hub.client_config has text[] columns; export must
    render them so that re-INSERT succeeds (not as ::jsonb cast)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.client_config
              (client_id, preset_key,
               eligible_import_declaration_types,
               relevant_export_declaration_types,
               fiscal_year_start_month, config_version, config_hash)
            values (%s, 'dncx', %s, %s, 1, 1, 'test-hash')
            """,
            (client_with_data, ["E11", "E15"], ["E42"]),
        )

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (client_with_data,))

    import_client_bundle(bundle_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select eligible_import_declaration_types, relevant_export_declaration_types "
            "from hub.client_config where client_id = %s",
            (client_with_data,),
        )
        eligible, relevant = cur.fetchone()
    assert eligible == ["E11", "E15"]
    assert relevant == ["E42"]


def test_stale_files_for_client_removed_on_import(client_with_data, tmp_path, monkeypatch):
    """Bundle is source of truth for the client. Files that exist on
    the target under <module>/<client>/ but aren't in the bundle must
    be removed; otherwise orphan files survive replace-mode imports."""
    src = tmp_path / "src_files"
    (src / "bcct" / client_with_data).mkdir(parents=True)
    (src / "bcct" / client_with_data / "fresh.txt").write_text("fresh", encoding="utf-8")
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(src))

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    target = tmp_path / "target_files"
    (target / "bcct" / client_with_data).mkdir(parents=True)
    (target / "bcct" / client_with_data / "stale.txt").write_text("stale", encoding="utf-8")
    # A different client's files in the same module must be left alone.
    (target / "bcct" / "other-client").mkdir(parents=True)
    (target / "bcct" / "other-client" / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(target))

    import_client_bundle(bundle_path=out)

    assert (target / "bcct" / client_with_data / "fresh.txt").exists()
    assert not (target / "bcct" / client_with_data / "stale.txt").exists()
    assert (target / "bcct" / "other-client" / "keep.txt").exists()


def test_files_restored(client_with_data, tmp_path, monkeypatch):
    src = tmp_path / "src_files"
    (src / "bcct" / client_with_data).mkdir(parents=True)
    (src / "bcct" / client_with_data / "doc.txt").write_text("payload", encoding="utf-8")
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(src))

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    # Switch to a clean target root for import.
    target = tmp_path / "target_files"
    target.mkdir()
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(target))

    import_client_bundle(bundle_path=out)

    restored = target / "bcct" / client_with_data / "doc.txt"
    assert restored.exists()
    assert restored.read_text(encoding="utf-8") == "payload"


def test_replace_handles_set_null_cascade_table(client_with_data, tmp_path):
    """Regression: file_uploads.client_id is `ON DELETE SET NULL`, not
    CASCADE. The cascade from DELETE hub.clients leaves file_uploads
    rows in place with client_id=NULL, and the bundle's re-INSERT hits
    a PK conflict on `upload_id`. Caught by real-Growatt round-trip.
    """
    upload_id = "up-rep-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.file_uploads
              (upload_id, client_id, module, original_filename,
               stored_path, content_sha256, size_bytes)
            values (%s, %s, 'bcct', 'r.xlsx', 'bcct/' || %s || '/r.xlsx',
                    'sha-' || %s, 100)
            """,
            (upload_id, client_with_data, client_with_data, upload_id),
        )

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    # Trigger replace: keep target's data (don't pre-delete) — import
    # must handle the SET NULL leftover gracefully.
    import_client_bundle(bundle_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select client_id from hub.file_uploads where upload_id = %s",
            (upload_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == client_with_data


def test_roundtrip_bcct_rows_with_upload_fk(client_with_data, tmp_path):
    """Regression: bcct_rows.upload_id FK references file_uploads.
    If file_uploads isn't in the bundle, fresh-target INSERT fails.
    Real Growatt has 23k bcct_rows all carrying upload_id."""
    upload_id = "up-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.file_uploads
              (upload_id, client_id, module, original_filename,
               stored_path, content_sha256, size_bytes)
            values (%s, %s, 'bcct', 'demo.xlsx', 'bcct/' || %s || '/demo.xlsx',
                    'sha-' || %s, 1024)
            """,
            (upload_id, client_with_data, client_with_data, upload_id),
        )
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               registration_date, customs_code, upload_id)
            values (%s, 'TXN-2', '0', 'DECL-2', '2026-04-01', 'C-2', %s)
            """,
            (client_with_data, upload_id),
        )

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (client_with_data,))
        cur.execute("delete from hub.file_uploads where upload_id = %s", (upload_id,))

    import_client_bundle(bundle_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select b.transaction_key, f.original_filename "
            "from hub.bcct_rows b join hub.file_uploads f "
            "on b.upload_id = f.upload_id where b.client_id = %s",
            (client_with_data,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row == ("TXN-2", "demo.xlsx")


def test_user_fk_columns_nulled_in_bundle(client_with_data, tmp_path):
    """Regression: parser_mappings.confirmed_by and similar FKs to
    hub.users are per-deployment. Bundle must NULL them out so imports
    don't fail when target has different user_ids."""
    # Use the seeded admin user (from conftest); the test only needs
    # SOME real user_id to make the source row valid.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select user_id from hub.users where email = 'admin@data-hub.local'")
        admin_user_id = cur.fetchone()[0]
        cur.execute(
            """
            insert into hub.parser_mappings
              (client_id, module, file_signature, mapping, sample_headers,
               proposed_by, confirmed_by)
            values (%s, 'bcct', 'sig-x', '{}'::jsonb, '[]'::jsonb,
                    'manual', %s)
            """,
            (client_with_data, admin_user_id),
        )

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    # Inspect the SQL — confirmed_by should be NULL in the bundle.
    with tarfile.open(out, "r:gz") as tar:
        for m in tar.getmembers():
            if m.name.endswith("_parser_mappings.sql"):
                body = tar.extractfile(m).read().decode("utf-8")
                break
    assert "parser_mappings" in body
    assert admin_user_id not in body, (
        f"user_id {admin_user_id!r} leaked into bundle SQL — should be NULL"
    )


def test_roundtrip_with_generated_columns(client_with_data, tmp_path):
    """Regression: bcct_rows.year is GENERATED ALWAYS STORED. Export
    must NOT emit it as an INSERT value; otherwise re-INSERT fails
    with `column "year" can only be updated to DEFAULT`.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               registration_date, customs_code)
            values (%s, 'TXN-1', '0', 'DECL-1', '2026-03-15', 'CUST-1')
            """,
            (client_with_data,),
        )

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (client_with_data,))

    import_client_bundle(bundle_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select transaction_key, declaration_no, registration_date, year "
            "from hub.bcct_rows where client_id = %s",
            (client_with_data,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "TXN-1"
    assert row[1] == "DECL-1"
    assert row[3] == 2026  # year derived from registration_date


def test_path_traversal_via_manifest_client_id_refused(client_with_data, tmp_path, monkeypatch):
    """Forging manifest.client_id to '..' would let _purge_client_files
    rmtree the entire files_root. Must be rejected upfront."""
    files_root = tmp_path / "target_files"
    (files_root / "bcct" / "victim").mkdir(parents=True)
    (files_root / "bcct" / "victim" / "data.txt").write_text("victim", encoding="utf-8")
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(files_root))

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    forged = tmp_path / "forged.tar.gz"
    _rewrite_manifest(out, forged, client_id="..")

    with pytest.raises(CorruptBundle, match="client_id"):
        import_client_bundle(bundle_path=forged)

    # Victim files untouched.
    assert (files_root / "bcct" / "victim" / "data.txt").exists()


def test_unknown_db_sql_file_refused(client_with_data, tmp_path):
    """A bundle with an extra `db/*.sql` file outside the allow-list
    must be refused — that file's contents would otherwise execute as
    arbitrary SQL on the target."""
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    forged = tmp_path / "forged.tar.gz"
    with tarfile.open(out, "r:gz") as src, tarfile.open(forged, "w:gz") as dst:
        for m in src.getmembers():
            ext = src.extractfile(m)
            dst.addfile(m) if ext is None else dst.addfile(m, ext)
        bad = b"-- arbitrary SQL\nselect 1;\n"
        info = tarfile.TarInfo(name="db/999_arbitrary.sql")
        info.size = len(bad)
        dst.addfile(info, BytesIO(bad))

    with pytest.raises(CorruptBundle, match="999_arbitrary"):
        import_client_bundle(bundle_path=forged)


def test_path_traversal_member_refused(client_with_data, tmp_path, monkeypatch):
    """A bundle with a `files/../escape.txt` member must be refused
    BEFORE any DB or filesystem write happens."""
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    forged = tmp_path / "forged.tar.gz"
    with tarfile.open(out, "r:gz") as src, tarfile.open(forged, "w:gz") as dst:
        for m in src.getmembers():
            ext = src.extractfile(m)
            if ext is None:
                dst.addfile(m)
            else:
                dst.addfile(m, ext)
        bad = b"pwned"
        info = tarfile.TarInfo(name="files/../escape.txt")
        info.size = len(bad)
        dst.addfile(info, BytesIO(bad))

    # Sandbox the files root so the (rejected) escape would have landed
    # under tmp_path if validation were missing.
    files_root = tmp_path / "target_files_root"
    files_root.mkdir()
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(files_root))

    # Sentinel mutation on the target — must survive the rejection.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.clients set name = 'pre-existing' where client_id = %s",
            (client_with_data,),
        )

    with pytest.raises(CorruptBundle, match="escapes"):
        import_client_bundle(bundle_path=forged)

    # Escape file did not land anywhere reachable from tmp_path.
    assert not (tmp_path / "escape.txt").exists()
    assert not list(files_root.rglob("escape.txt"))
    # DB unchanged.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select name from hub.clients where client_id = %s", (client_with_data,))
        assert cur.fetchone()[0] == "pre-existing"


def test_staging_dir_on_same_fs_as_files_root(client_with_data, tmp_path, monkeypatch):
    """Regression: Phase-3 os.replace fails cross-filesystem (EXDEV).
    Staging must be created UNDER DATA_HUB_FILES_ROOT, not in $TMPDIR."""
    files_root = tmp_path / "target_files"
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(files_root))

    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    import app.data_promotion as dp

    captured: dict = {}
    real_mkdtemp = tempfile.mkdtemp

    def spy(*args, **kwargs):
        captured["dir"] = kwargs.get("dir")
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(dp.tempfile, "mkdtemp", spy)

    import_client_bundle(bundle_path=out)

    assert captured.get("dir") is not None, "mkdtemp called without dir= argument"
    assert Path(captured["dir"]).resolve() == files_root.resolve(), (
        f"staging dir parent {captured['dir']!r} is not files_root {files_root!r}"
    )


def test_db_rolls_back_when_file_phase_fails(client_with_data, tmp_path, monkeypatch):
    """If file extraction fails, the DB transaction must NOT commit —
    target's pre-import state is preserved."""
    out = tmp_path / "bundle.tar.gz"
    export_client(client_id=client_with_data, out_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.clients set name = 'pre-existing' where client_id = %s",
            (client_with_data,),
        )

    import app.data_promotion as dp

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure during file extraction")

    monkeypatch.setattr(dp, "_extract_files_to_staging", _boom)

    with pytest.raises(OSError, match="simulated"):
        import_client_bundle(bundle_path=out)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select name from hub.clients where client_id = %s", (client_with_data,))
        assert cur.fetchone()[0] == "pre-existing"


# ---- helpers -----------------------------------------------------------

def _rewrite_manifest(src: Path, dst: Path, **patch) -> None:
    """Open src bundle, mutate manifest fields, write to dst."""
    with tarfile.open(src, "r:gz") as src_tar:
        members = src_tar.getmembers()
        with tarfile.open(dst, "w:gz") as dst_tar:
            for m in members:
                if m.name == "manifest.json":
                    body = json.loads(src_tar.extractfile(m).read().decode("utf-8"))
                    body.update(patch)
                    new_bytes = json.dumps(body).encode("utf-8")
                    new_info = tarfile.TarInfo(name="manifest.json")
                    new_info.size = len(new_bytes)
                    dst_tar.addfile(new_info, BytesIO(new_bytes))
                else:
                    extracted = src_tar.extractfile(m)
                    if extracted is None:
                        dst_tar.addfile(m)
                    else:
                        dst_tar.addfile(m, extracted)
