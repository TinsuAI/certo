"""Tests for app.uploads.declaration_zip — bulk ZIP upload pipeline.

Pure-function layer first (validate / extract / staging hygiene), then
DB-coupled layer (parse + dedup + commit) further down.
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
import xlwt

from hub.app.database import connect
from hub.app.routes.clients import upsert_client
from hub.app.stores.customs_declaration_files import (
    insert_declaration_file,
    list_files_for_declaration,
)
from hub.app.uploads.declaration_zip import (
    MAX_EXTRACTED_BYTES,
    MAX_MEMBER_BYTES,
    MAX_MEMBERS,
    MAX_ZIP_BYTES,
    STAGING_ROOT,
    ZipBombError,
    ZipCorruptError,
    ZipMemberTooLargeError,
    ZipPathTraversalError,
    ZipTooLargeError,
    ZipTooManyMembersError,
    annotate_dedup_status,
    cancel_staging,
    commit_staged_files,
    extract_to_staging,
    get_staging_path,
    parse_staged_files,
    reap_expired_staging,
    validate_zip,
)


# ─── helpers ───────────────────────────────────────────────────────────


def _make_xls_bytes(decl_no: str) -> bytes:
    """Minimal valid XLS containing the declaration number."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet("TKN")
    ws.write(3, 4, decl_no)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_zip(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _make_zip_bomb_synthetic(declared_size_per_member: int, n_members: int) -> bytes:
    """Build a ZIP whose ZipInfo.file_size claims very large sizes without
    actually writing them. Used to test the pre-extraction sum check.

    Writes small actual content but forges the uncompressed-size header
    by writing real content of the declared size (still small enough to
    fit in test RAM).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Compressible bytes so the ZIP itself stays small.
        payload = b"a" * declared_size_per_member
        for i in range(n_members):
            zf.writestr(f"foo_{1070000000000 + i}.xls", payload)
    return buf.getvalue()


@pytest.fixture
def staging_root(tmp_path) -> Path:
    return tmp_path / "staging"


# ─── validate_zip: caps + bomb + traversal + corruption ───────────────


def test_validate_zip_under_caps_passes():
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
        ("00000002_107000000002.xls", _make_xls_bytes("107000000002")),
    ])
    validate_zip(z)  # no raise


def test_validate_zip_corrupt_raises():
    with pytest.raises(ZipCorruptError):
        validate_zip(b"not a zip file at all")


def test_validate_zip_too_large_raises():
    big = b"x" * (MAX_ZIP_BYTES + 1)
    with pytest.raises(ZipTooLargeError):
        validate_zip(big)


def test_validate_zip_too_many_members_raises():
    # Use stored (no-compress) tiny members so ZIP stays small.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        # +1 over MAX_MEMBERS — count only files matching the per-decl pattern.
        for i in range(MAX_MEMBERS + 1):
            zf.writestr(f"foo_{1070000000000 + i}.xls", b"x")
    with pytest.raises(ZipTooManyMembersError):
        validate_zip(buf.getvalue())


def test_validate_zip_member_too_large_raises():
    z = _make_zip([
        ("00000001_107000000001.xls", b"x" * (MAX_MEMBER_BYTES + 1)),
    ])
    with pytest.raises(ZipMemberTooLargeError):
        validate_zip(z)


def test_validate_zip_bomb_total_extracted_exceeds_cap():
    # Synthesize members whose ZipInfo.file_size sums to > 2GB without
    # holding 2GB in memory: each member declares 100MB and we have 25+.
    # We can't actually create 2GB of payload in test RAM; instead patch
    # the cap to a small value for this test only.
    z = _make_zip([
        ("00000001_107000000001.xls", b"x" * 1024),
        ("00000002_107000000002.xls", b"x" * 1024),
    ])
    # Force a tiny cap so the check fires on this small ZIP.
    with pytest.raises(ZipBombError):
        validate_zip(z, _max_extracted_bytes=1500)


def test_validate_zip_path_traversal_raises():
    z = _make_zip([
        ("../etc/passwd_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    with pytest.raises(ZipPathTraversalError):
        validate_zip(z)


def test_validate_zip_absolute_path_raises():
    z = _make_zip([
        ("/etc/foo_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    with pytest.raises(ZipPathTraversalError):
        validate_zip(z)


# ─── extract_to_staging ───────────────────────────────────────────────


def test_extract_to_staging_writes_only_supported_files(staging_root):
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
        ("00000002_107000000002.xls", _make_xls_bytes("107000000002")),
        ("README.txt", b"readme content"),
        (".DS_Store", b"junk"),
    ])
    result = extract_to_staging(z, staging_root=staging_root)
    assert result.total_in_zip == 4
    assert result.ignored_non_pattern == 2
    assert result.extracted == 2
    files = sorted(p.name for p in result.staging_path.iterdir())
    assert files == [
        "00000001_107000000001.xls", "00000002_107000000002.xls",
    ]


def test_extract_to_staging_strips_subdirectories(staging_root):
    z = _make_zip([
        ("subdir/00000001_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    result = extract_to_staging(z, staging_root=staging_root)
    assert result.extracted == 1
    files = list(result.staging_path.iterdir())
    assert len(files) == 1
    # Subdir stripped — only basename written to staging root.
    assert files[0].name == "00000001_107000000001.xls"
    # No subdirectory created.
    assert not (result.staging_path / "subdir").exists()


def test_extract_to_staging_filename_collision_keeps_one(staging_root):
    # Two members have the same basename after directory strip → second
    # write overwrites the first. Real ZIPs in the wild rarely have
    # this; document the behaviour.
    z = _make_zip([
        ("a/00000001_107000000001.xls", _make_xls_bytes("107000000001")),
        ("b/00000001_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    result = extract_to_staging(z, staging_root=staging_root)
    files = list(result.staging_path.iterdir())
    assert len(files) == 1


def test_extract_to_staging_rejects_traversal_before_extracting(staging_root):
    z = _make_zip([
        ("../bad_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    with pytest.raises(ZipPathTraversalError):
        extract_to_staging(z, staging_root=staging_root)
    # Staging dir for this attempt should be cleaned up.
    assert not staging_root.exists() or not any(staging_root.iterdir())


def test_extract_to_staging_returns_distinct_staging_ids(staging_root):
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    r1 = extract_to_staging(z, staging_root=staging_root)
    r2 = extract_to_staging(z, staging_root=staging_root)
    assert r1.staging_id != r2.staging_id
    assert r1.staging_path != r2.staging_path


# ─── get_staging_path: traversal hardening on the ID itself ───────────


def test_get_staging_path_resolves_valid_id(staging_root):
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    r = extract_to_staging(z, staging_root=staging_root)
    p = get_staging_path(r.staging_id, staging_root=staging_root)
    assert p == r.staging_path


def test_get_staging_path_rejects_traversal_id(staging_root):
    assert get_staging_path("../etc", staging_root=staging_root) is None
    assert get_staging_path("/etc", staging_root=staging_root) is None
    assert get_staging_path("foo/bar", staging_root=staging_root) is None


def test_get_staging_path_returns_none_for_unknown_id(staging_root):
    staging_root.mkdir(parents=True)
    # Valid format, just doesn't exist.
    assert get_staging_path(
        "zip-00000000-0000-0000-0000-000000000000",
        staging_root=staging_root,
    ) is None


# ─── reap_expired_staging + cancel_staging ────────────────────────────


def test_cancel_staging_removes_dir(staging_root):
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    r = extract_to_staging(z, staging_root=staging_root)
    assert r.staging_path.exists()
    assert cancel_staging(r.staging_id, staging_root=staging_root) is True
    assert not r.staging_path.exists()


def test_cancel_staging_returns_false_for_unknown_id(staging_root):
    staging_root.mkdir(parents=True)
    ok = cancel_staging(
        "zip-00000000-0000-0000-0000-000000000000",
        staging_root=staging_root,
    )
    assert ok is False


def test_cancel_staging_rejects_traversal_id(staging_root):
    staging_root.mkdir(parents=True)
    # Should not delete anything outside staging_root.
    sibling = staging_root.parent / "sibling"
    sibling.mkdir()
    assert cancel_staging("../sibling", staging_root=staging_root) is False
    assert sibling.exists()


def test_reap_expired_staging_removes_old_dirs(staging_root):
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
    ])
    old = extract_to_staging(z, staging_root=staging_root)
    fresh = extract_to_staging(z, staging_root=staging_root)
    # Age the old dir.
    old_mtime = time.time() - 7200  # 2 hours ago
    import os
    os.utime(old.staging_path, (old_mtime, old_mtime))
    removed = reap_expired_staging(
        staging_root=staging_root, ttl_seconds=3600,
    )
    assert removed == 1
    assert not old.staging_path.exists()
    assert fresh.staging_path.exists()


def test_reap_expired_staging_handles_missing_root(tmp_path):
    # No staging root yet → no-op, no crash.
    assert reap_expired_staging(
        staging_root=tmp_path / "does-not-exist",
        ttl_seconds=3600,
    ) == 0


def test_reap_expired_staging_ignores_unrelated_files(staging_root):
    staging_root.mkdir(parents=True)
    # A loose file in staging_root (not a zip-* dir) should be left alone.
    (staging_root / "loose.txt").write_text("hello")
    (staging_root / "not-a-staging-dir").mkdir()
    removed = reap_expired_staging(
        staging_root=staging_root, ttl_seconds=0,
    )
    assert removed == 0
    assert (staging_root / "loose.txt").exists()


# ─── parse_staged_files + annotate_dedup_status (DB-coupled) ──────────


@pytest.fixture
def bulk_test_client() -> str:
    cid = "test-bulk-zip-vn"
    upsert_client(
        client_id=cid, name="Test Bulk ZIP",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def test_parse_staged_files_classifies_ok_mismatch_parse_error(staging_root):
    # Build a ZIP with 3 files: 1 valid, 1 mismatch, 1 unreadable XLS.
    z = _make_zip([
        ("00000001_107000000001.xls", _make_xls_bytes("107000000001")),
        ("00000002_107000000002.xls", _make_xls_bytes("999999999999")),  # mismatch
        ("00000003_107000000003.xls", b"not a real xls"),                # parse error
    ])
    r = extract_to_staging(z, staging_root=staging_root)
    files = parse_staged_files(r.staging_path)
    by_name = {f.name: f for f in files}
    assert by_name["00000001_107000000001.xls"].status == "ok"
    assert by_name["00000001_107000000001.xls"].declaration_no == "107000000001"
    assert by_name["00000002_107000000002.xls"].status == "mismatch"
    assert by_name["00000002_107000000002.xls"].declaration_no == "107000000002"
    assert by_name["00000003_107000000003.xls"].status == "parse_error"


def test_annotate_dedup_status_flips_ok_to_duplicate(
    staging_root, bulk_test_client,
):
    decl_no = "107888000001"
    xls_bytes = _make_xls_bytes(decl_no)
    z = _make_zip([(f"00000001_{decl_no}.xls", xls_bytes)])
    r = extract_to_staging(z, staging_root=staging_root)
    files = parse_staged_files(r.staging_path)
    assert files[0].status == "ok"
    # First annotate: nothing in DB yet → stays 'ok'.
    files = annotate_dedup_status(
        files, client_id=bulk_test_client, direction="import",
    )
    assert files[0].status == "ok"
    # Insert into DB with the same sha256 the parser would compute.
    sha = files[0].sha256
    insert_declaration_file(
        client_id=bulk_test_client,
        declaration_no=decl_no, direction="import", file_kind="xls",
        backend_key="customs_declarations/test/x.xls",
        original_filename=f"00000001_{decl_no}.xls",
        sha256=sha, size_bytes=files[0].size_bytes,
        uploaded_by="test",
    )
    # Re-annotate: now should flip to 'duplicate'.
    files = parse_staged_files(r.staging_path)
    files = annotate_dedup_status(
        files, client_id=bulk_test_client, direction="import",
    )
    assert files[0].status == "duplicate"


# ─── commit_staged_files ──────────────────────────────────────────────


def test_commit_inserts_ok_skips_mismatch_and_parse_error(
    staging_root, bulk_test_client,
):
    z = _make_zip([
        ("00000001_107888100001.xls", _make_xls_bytes("107888100001")),
        ("00000002_107888100002.xls", _make_xls_bytes("999999999999")),
        ("00000003_107888100003.xls", b"corrupt"),
    ])
    r = extract_to_staging(z, staging_root=staging_root)
    result = commit_staged_files(
        r.staging_path,
        client_id=bulk_test_client, direction="import",
        uploaded_by="test",
    )
    assert result.inserted == 1
    assert result.deduped == 0
    assert result.mismatch_skipped == 1
    assert result.parse_error_skipped == 1
    assert result.store_errors == 0
    # Verify DB row.
    rows = list_files_for_declaration(bulk_test_client, "107888100001")
    assert len(rows) == 1


def test_commit_is_idempotent(staging_root, bulk_test_client):
    z = _make_zip([
        ("00000001_107888200001.xls", _make_xls_bytes("107888200001")),
        ("00000002_107888200002.xls", _make_xls_bytes("107888200002")),
    ])
    r = extract_to_staging(z, staging_root=staging_root)
    first = commit_staged_files(
        r.staging_path,
        client_id=bulk_test_client, direction="import",
        uploaded_by="test",
    )
    assert first.inserted == 2
    # Re-extract identical ZIP into a new staging dir and commit again.
    r2 = extract_to_staging(z, staging_root=staging_root)
    second = commit_staged_files(
        r2.staging_path,
        client_id=bulk_test_client, direction="import",
        uploaded_by="test",
    )
    assert second.inserted == 0
    assert second.deduped == 2


def test_commit_respects_direction_parameter(
    staging_root, bulk_test_client,
):
    # Same files committed once as 'import' and once as 'export' should
    # produce 2 rows for the same declaration_no — different directions
    # are distinct entries.
    z = _make_zip([
        ("00000001_107888300001.xls", _make_xls_bytes("107888300001")),
    ])
    r1 = extract_to_staging(z, staging_root=staging_root)
    commit_staged_files(
        r1.staging_path, client_id=bulk_test_client,
        direction="import", uploaded_by="test",
    )
    r2 = extract_to_staging(z, staging_root=staging_root)
    commit_staged_files(
        r2.staging_path, client_id=bulk_test_client,
        direction="export", uploaded_by="test",
    )
    rows = list_files_for_declaration(bulk_test_client, "107888300001")
    assert len(rows) == 2
    dirs = sorted(r.direction for r in rows)
    assert dirs == ["export", "import"]
