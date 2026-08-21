"""BCCT reject — the flow that had no way to discard a wrong file."""
from fastapi.testclient import TestClient
from app.main import app
from app.database import connect


def _login(c):
    c.post("/login", data={"email": "admin@data-hub.local", "password": "admin123"},
           follow_redirects=False)


def test_reject_route_is_registered():
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/clients/{client_id}/bcct/upload/preview/{pending_id}/reject" in paths


def test_reject_unknown_pending_is_404_not_500():
    c = TestClient(app); _login(c)
    r = c.post("/clients/demo-furniture/bcct/upload/preview/does-not-exist/reject",
               follow_redirects=False)
    assert r.status_code == 404, r.text[:200]


def test_reject_deletes_the_pending_and_marks_the_upload():
    """Seeds its own pending row so the assertion always runs — an earlier
    version skipped whenever the database happened to hold no stashed BCCT
    upload, which is most of the time."""
    c = TestClient(app); _login(c)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into hub.file_uploads
                 (upload_id, client_id, module, original_filename, stored_path,
                  content_sha256, size_bytes, parse_status)
               values ('up-reject-test', 'demo-furniture', 'bcct', 'wrong.xlsx',
                       'test/none.xlsx', 'sha-reject-test', 0, 'proposed_mapping')
               on conflict (upload_id) do update set parse_status='proposed_mapping'""")
        cur.execute(
            """insert into hub.upload_pending
                 (pending_id, client_id, module, upload_id, parsed_rows, diff_summary)
               values ('pend-reject-test', 'demo-furniture', 'bcct', 'up-reject-test',
                       '[]'::jsonb, '{}'::jsonb)
               on conflict (pending_id) do nothing""")

    r = c.post("/clients/demo-furniture/bcct/upload/preview/pend-reject-test/reject",
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/clients/demo-furniture/bcct?rejected=1"

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select 1 from hub.upload_pending where pending_id='pend-reject-test'")
        assert cur.fetchone() is None, "pending row survived the reject"
        cur.execute("select parse_status from hub.file_uploads where upload_id='up-reject-test'")
        assert cur.fetchone()[0] == "rejected"
        cur.execute("delete from hub.file_uploads where upload_id='up-reject-test'")


def test_preview_offers_both_leaving_and_rejecting():
    """The old template had only "Hủy", which navigates away and leaves the
    pending to expire. Both choices must be present and distinct."""
    import pathlib as _p
    markup = _p.Path("app/templates/clients/bcct_upload_preview.html").read_text(encoding="utf-8")
    assert "Quay lại sau (giữ pending)" in markup
    assert "/reject" in markup and "Bỏ file" in markup
