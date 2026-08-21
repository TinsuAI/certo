"""Tests for hub.customs_declaration_files store."""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.app.routes.clients import upsert_client
from hub.app.stores.customs_declaration_files import (
    delete_declaration_file,
    file_count_per_declaration,
    get_declaration_file,
    insert_declaration_file,
    list_declarations_with_status,
    list_files_for_declaration,
)


@pytest.fixture
def client_id() -> str:
    cid = "test-tk-client-vn"
    upsert_client(
        client_id=cid, name="Test TK Client",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _insert(client_id: str, **overrides) -> tuple[int, bool]:
    defaults = dict(
        declaration_no="107000000001", direction="import", file_kind="xls",
        backend_key="customs_declarations/test/abc.xls",
        original_filename="test_107000000001.xls",
        sha256="a" * 64, size_bytes=1234,
    )
    defaults.update(overrides)
    return insert_declaration_file(client_id=client_id, **defaults)


def test_insert_basic(client_id):
    fid, created = _insert(client_id)
    assert created is True
    assert fid > 0


def test_insert_idempotent_same_sha(client_id):
    fid1, c1 = _insert(client_id)
    fid2, c2 = _insert(client_id)
    assert c1 is True
    assert c2 is False
    assert fid1 == fid2


def test_insert_different_sha_creates_new(client_id):
    fid1, _ = _insert(client_id, sha256="a" * 64)
    fid2, c2 = _insert(client_id, sha256="b" * 64,
                        backend_key="customs_declarations/test/abc2.xls")
    assert c2 is True
    assert fid1 != fid2


def test_insert_different_direction_separate(client_id):
    fid1, _ = _insert(client_id, direction="import")
    fid2, _ = _insert(client_id, direction="export")
    assert fid1 != fid2


def test_insert_rejects_bad_direction(client_id):
    with pytest.raises(ValueError):
        _insert(client_id, direction="both")


def test_insert_rejects_bad_file_kind(client_id):
    with pytest.raises(ValueError):
        _insert(client_id, file_kind="exe")


def test_get_returns_full_dataclass(client_id):
    fid, _ = _insert(client_id, original_filename="seq_107000000001.xls")
    f = get_declaration_file(fid)
    assert f is not None
    assert f.id == fid
    assert f.declaration_no == "107000000001"
    assert f.original_filename == "seq_107000000001.xls"
    assert f.size_bytes == 1234


def test_get_missing_returns_none():
    assert get_declaration_file(99999999) is None


def test_list_files_for_declaration(client_id):
    _insert(client_id, sha256="a" * 64,
            backend_key="customs_declarations/test/a.xls")
    _insert(client_id, sha256="b" * 64,
            backend_key="customs_declarations/test/b.xls")
    files = list_files_for_declaration(client_id, "107000000001")
    assert len(files) == 2


def test_list_files_filtered_by_direction(client_id):
    _insert(client_id, direction="import", sha256="a" * 64)
    _insert(client_id, direction="export", sha256="b" * 64,
            backend_key="customs_declarations/test/b.xls")
    imp = list_files_for_declaration(client_id, "107000000001", direction="import")
    exp = list_files_for_declaration(client_id, "107000000001", direction="export")
    assert len(imp) == 1
    assert len(exp) == 1
    assert imp[0].direction == "import"


def test_file_count_per_declaration(client_id):
    _insert(client_id, declaration_no="100001", sha256="a" * 64)
    _insert(client_id, declaration_no="100001", sha256="b" * 64,
            backend_key="customs_declarations/test/b.xls")
    _insert(client_id, declaration_no="100002", sha256="c" * 64,
            backend_key="customs_declarations/test/c.xls")
    counts = file_count_per_declaration(client_id)
    assert counts[("100001", "import")] == 2
    assert counts[("100002", "import")] == 1


def test_delete(client_id):
    fid, _ = _insert(client_id)
    assert delete_declaration_file(fid) is True
    assert delete_declaration_file(fid) is False
    assert get_declaration_file(fid) is None


def test_list_declarations_with_status_combines_bcct_and_files(client_id):
    """Synthesize a couple of bcct rows + files, verify summary."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.file_uploads
              (upload_id, client_id, module, original_filename,
               stored_path, content_sha256, size_bytes, parse_status, row_count)
            values ('test-bcct-up', %s, 'bcct', 't.xls', 't', 'x', 0, 'done', 0)
            on conflict do nothing
            """, (client_id,),
        )
        for decl, line_no in [
            ("100001", "1"), ("100001", "2"), ("100002", "1"),
        ]:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, hs_code, quantity, unit,
                   total_value, currency_nt, upload_id)
                values (%s, %s, %s, %s, 'E11', 'import', '2026-04-01',
                        'X1', 'goods', '12345678', 1.0, 'pcs',
                        100.0, 'USD', 'test-bcct-up')
                """,
                (client_id, f"{decl}-{line_no}", line_no, decl),
            )
        conn.commit()

    # File only on 100001.
    _insert(client_id, declaration_no="100001", sha256="a" * 64)

    summaries = list_declarations_with_status(client_id, limit=10)
    assert len(summaries) == 2
    by_decl = {s.declaration_no: s for s in summaries}
    assert by_decl["100001"].file_count == 1
    assert by_decl["100001"].bcct_line_count == 2
    assert by_decl["100002"].file_count == 0
    assert by_decl["100002"].bcct_line_count == 1


def test_list_declarations_filter_has_files(client_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.file_uploads
              (upload_id, client_id, module, original_filename,
               stored_path, content_sha256, size_bytes, parse_status, row_count)
            values ('test-bcct-up2', %s, 'bcct', 't.xls', 't', 'x', 0, 'done', 0)
            on conflict do nothing
            """, (client_id,),
        )
        for decl in ["200001", "200002"]:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, hs_code, quantity, unit,
                   total_value, currency_nt, upload_id)
                values (%s, %s, '1', %s, 'E11', 'import', '2026-04-01',
                        'X1', 'goods', '12345678', 1.0, 'pcs',
                        100.0, 'USD', 'test-bcct-up2')
                """,
                (client_id, f"{decl}-1", decl),
            )
        conn.commit()
    _insert(client_id, declaration_no="200001", sha256="a" * 64)

    with_files = list_declarations_with_status(client_id, has_files=True)
    without_files = list_declarations_with_status(client_id, has_files=False)
    assert {s.declaration_no for s in with_files} == {"200001"}
    assert {s.declaration_no for s in without_files} == {"200002"}
