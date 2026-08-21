"""Phase 5: no-header BCCT files via positional (column-index) mapping.

A headerless file must keep ALL rows as data — the first data row is no
longer consumed as a header.
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from hub.app.parsers.bcct import parse_bcct_workbook


def _xlsx(rows):
    wb = Workbook(); ws = wb.active; ws.title = "BCCT"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


_POSITIONAL = {
    0: "declaration_no", 1: "line_no", 2: "declaration_type",
    3: "registration_date", 4: "customs_code", 5: "goods_name",
    6: "quantity", 7: "unit", 8: "total_value", 9: "currency_nt",
}


def test_positional_keeps_all_rows_no_header_consumed():
    blob = _xlsx([
        ("308400001", "1", "E11", "2026-05-18", "PE-1", "Poly", "100", "kg", "250", "USD"),
        ("308400002", "1", "E11", "2026-05-18", "PE-2", "PP", "80", "kg", "200", "USD"),
        ("308400003", "1", "E11", "2026-05-18", "PE-3", "PVC", "60", "kg", "150", "USD"),
    ])
    rows = parse_bcct_workbook(blob, positional_override=_POSITIONAL)
    # all 3 data rows kept (none consumed as header)
    assert len(rows) == 3
    decls = {r["declaration_no"] for r in rows}
    assert decls == {"308400001", "308400002", "308400003"}
    r0 = next(r for r in rows if r["declaration_no"] == "308400001")
    assert r0["customs_code"] == "PE-1"
    assert r0["registration_date"].isoformat() == "2026-05-18"
    assert float(r0["quantity"]) == 100.0


def test_no_header_flow_keeps_all_rows(tmp_path, monkeypatch):
    import re
    import pytest
    from fastapi.testclient import TestClient
    from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE
    from hub.app.database import connect
    from hub.app.main import app

    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    import hub.app.storage as storage_mod
    storage_mod._BACKEND = None

    cid, uid = "noheader-route", "u_noheader_route"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("insert into hub.clients (client_id,name) values (%s,'x') "
                    "on conflict do nothing", (cid,))
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'noheader@t.local','N',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin',status='active'",
            (uid, hash_password("pw")))
    try:
        c = TestClient(app)
        c.cookies.set(SESSION_COOKIE, create_session(uid))
        blob = _xlsx([
            ("308400001", "1", "E11", "2026-05-18", "PE-1", "Poly", "100", "kg", "250", "USD"),
            ("308400002", "1", "E11", "2026-05-18", "PE-2", "PP", "80", "kg", "200", "USD"),
        ])
        up = c.post(f"/clients/{cid}/bcct/upload",
                    files={"file": ("t.xlsx", blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    follow_redirects=False)
        assert "/upload/mapping/" in up.headers["location"]
        upload_id = re.search(r"/upload/mapping/([^/?]+)", up.headers["location"]).group(1)
        data = {"header_row_override": "0", "extra_required_fields": ""}
        for i, f in _POSITIONAL.items():
            data[f"col_{i}__field"] = f
        pr = c.post(f"/clients/{cid}/bcct/upload/mapping/{upload_id}/parse",
                    data=data, follow_redirects=False)
        assert pr.status_code == 303, pr.text
        assert "/upload/preview/" in pr.headers["location"]
        pid = pr.headers["location"].rsplit("/", 1)[-1]
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select parsed_rows from hub.upload_pending where pending_id=%s", (pid,))
            parsed = cur.fetchone()[0]
        # both rows kept — first data row NOT consumed as header
        assert len(parsed) == 2
        assert {r["declaration_no"] for r in parsed} == {"308400001", "308400002"}
    finally:
        with connect() as conn, conn.cursor() as cur:
            for t in ("bcct_rows", "upload_pending", "file_uploads"):
                cur.execute(f"delete from hub.{t} where client_id=%s", (cid,))
            cur.execute("delete from hub.sessions where user_id=%s", (uid,))
            cur.execute("delete from hub.clients where client_id=%s", (cid,))
            cur.execute("delete from hub.users where user_id=%s", (uid,))


def test_infer_distinctive_columns_by_value():
    from hub.app.parsers.bcct_infer import infer_bcct_columns_by_values
    rows = [
        ["108212187420", "1", "E11", "2026-05-18", "PE-001", "Nhựa PE nguyên sinh",
         "100", "kg", "250000", "0.05", "1300", "9.5", "USD", "26138"],
        ["108212187421", "2", "E42", "2026-05-19", "AL-200", "Nhôm tấm cán nguội",
         "80", "kg", "200000", "0.04", "1100", "8.0", "USD", "26140"],
    ]
    m = infer_bcct_columns_by_values(rows)
    assert m[0] == "declaration_no"
    assert m[2] == "declaration_type"
    assert m[3] == "registration_date"
    assert m[4] == "customs_code"      # PE-001 / AL-200 are distinctive
    assert m[5] == "goods_name"
    assert m[13 - 1] == "currency_nt"  # idx 12
    # ambiguous numeric columns are NOT inferred
    for num_idx in (6, 8, 9, 10, 11):
        assert num_idx not in m


def test_infer_skips_pure_numeric_columns():
    from hub.app.parsers.bcct_infer import infer_bcct_columns_by_values
    rows = [["100", "250", "1300"], ["80", "200", "1100"]]
    assert infer_bcct_columns_by_values(rows) == {}


def test_build_context_prefills_inferred_on_no_header():
    from hub.app.routes._mapping_flow import _build_mapping_context
    from hub.app.routes.bcct import BCCT_MAPPING_CFG
    blob = _xlsx([
        ("108212187420", "1", "E11", "2026-05-18", "PE-001", "Nhựa PE nguyên sinh",
         "100", "kg", "250000", "0.05", "1300", "9.5", "USD", "26138"),
        ("108212187421", "2", "E42", "2026-05-19", "AL-200", "Nhôm tấm",
         "80", "kg", "200000", "0.04", "1100", "8.0", "USD", "26140"),
    ])
    ctx = _build_mapping_context(
        client_id="no-such-client", upload_id="u", cfg=BCCT_MAPPING_CFG,
        blob=blob, file_signature=None, extra={}, rigid_only=True)
    assert ctx["suggest_no_header"] is True
    proposed = {c["index"]: c["proposed"] for c in ctx["column_map"] if c["proposed"]}
    assert proposed.get(0) == "declaration_no"
    assert proposed.get(3) == "registration_date"
    assert proposed.get(12) == "currency_nt"


def test_headerless_file_suggests_no_header():
    from hub.app.routes._mapping_flow import _build_mapping_context
    from hub.app.routes.bcct import BCCT_MAPPING_CFG
    blob = _xlsx([
        ("308400001", "1", "E11", "2026-05-18", "PE-1", "Poly", "100", "kg", "250", "USD"),
        ("308400002", "1", "E11", "2026-05-18", "PE-2", "PP", "80", "kg", "200", "USD"),
    ])
    ctx = _build_mapping_context(
        client_id="no-such-client", upload_id="u", cfg=BCCT_MAPPING_CFG,
        blob=blob, file_signature=None, extra={}, rigid_only=True)
    assert ctx["suggest_no_header"] is True


def test_standard_header_file_does_not_suggest_no_header():
    from hub.app.routes._mapping_flow import _build_mapping_context
    from hub.app.routes.bcct import BCCT_MAPPING_CFG
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        ("308400001", 1, "E11", "2026-05-18", "PE-1", "Poly", 100, "kg", 250, "USD"),
    ])
    ctx = _build_mapping_context(
        client_id="no-such-client", upload_id="u", cfg=BCCT_MAPPING_CFG,
        blob=blob, file_signature=None, extra={}, rigid_only=True)
    assert ctx["suggest_no_header"] is False


def test_positional_skips_identifierless_row():
    # A row with no declaration_no AND no customs_code is skipped, not parsed.
    blob = _xlsx([
        ("308400001", "1", "E11", "2026-05-18", "PE-1", "Poly", "100", "kg", "250", "USD"),
        ("", "1", "E11", "2026-05-18", "", "blank-ids", "5", "kg", "9", "USD"),
    ])
    rows, skipped = parse_bcct_workbook(
        blob, positional_override=_POSITIONAL, return_skipped=True)
    assert len(rows) == 1 and rows[0]["declaration_no"] == "308400001"
    assert len(skipped) == 1
