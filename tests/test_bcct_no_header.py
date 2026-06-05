"""Phase 5: no-header BCCT files via positional (column-index) mapping.

A headerless file must keep ALL rows as data — the first data row is no
longer consumed as a header.
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from app.parsers.bcct import parse_bcct_workbook


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
    from app.auth.session import create_session, hash_password, SESSION_COOKIE
    from app.database import connect
    from app.main import app

    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    import app.storage as storage_mod
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
