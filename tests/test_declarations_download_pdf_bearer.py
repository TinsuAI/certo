"""Provider tests for the Bearer merge-to-PDF endpoint
`GET /v1/hub/clients/{c}/declarations/download.pdf`.

Merges each declaration's stored `.xls` (the ECUS print form) into one
print-standard "tờ khai ghép" PDF, in `sort` order, skipping
declarations with no file and reporting them via X-Declarations-* headers.

Source-document case B: the stored `.xls` IS the official print form;
LibreOffice renders it to the "PDF chuẩn". These tests build synthetic
2-sheet `.xls` fixtures (xlwt) carrying a unique alnum marker per file
so ordering can be asserted from extracted PDF text. They invoke real
soffice, so each render path adds ~1-2s.

The render-fidelity golden test against a real Johnson declaration is
env-gated (`DATA_HUB_REAL_DATA_DIR`) to keep customer data out of the repo.
"""
from __future__ import annotations

import os
import secrets
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
import xlwt
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import jwt_issuer, settings_store
from app.database import connect
from app.main import app
from app.storage import get_backend, sha256_bytes
from app.stores import service_accounts as sa_store

URL_TMPL = "/v1/hub/clients/{cid}/declarations/download.pdf"


def _url(client_id: str) -> str:
    return URL_TMPL.format(cid=client_id)


def _client() -> TestClient:
    return TestClient(app)


def _auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _decl_xls(marker: str) -> bytes:
    """Minimal 2-sheet declaration .xls resembling the ECUS print form,
    carrying `marker` (alnum, survives PDF text extraction) so we can
    assert merge order from the rendered text."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet("TKN")
    ws.write(0, 5, "Tờ khai hàng hóa nhập khẩu (thông quan)")
    ws.write(1, 2, marker)
    hang = wb.add_sheet("HANG")  # supplementary tab — not in print area
    hang.write(0, 0, "data")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_text(content: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(content)).pages)


def _page_count(content: bytes) -> int:
    return len(PdfReader(BytesIO(content)).pages)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def files_root(tmp_path, monkeypatch):
    root = tmp_path / "files"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(root))
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield root
    storage_mod._BACKEND = None


def _seed_bcct(cur, *, client_id, decl_no, direction, registration_date):
    cur.execute(
        """insert into hub.bcct_rows
           (client_id, transaction_key, line_no, declaration_no,
            declaration_type, direction, registration_date,
            customs_code, goods_name, payload)
           values (%s, %s, '1', %s, %s, %s, %s,
                   'MAT-X', 'desc', '{}'::jsonb)""",
        (client_id, f"TX-{decl_no}-{direction}", decl_no,
         "E11" if direction == "import" else "E42", direction,
         registration_date),
    )


def _seed_file(cur, *, client_id, decl_no, direction, marker,
               filename, file_kind="xls", blob=None):
    backend = get_backend()
    if blob is None:
        blob = _decl_xls(marker)
    key = f"customs_declarations/{client_id}/{secrets.token_hex(4)}_{filename}"
    backend.put(blob, key=key)
    cur.execute(
        """insert into hub.customs_declaration_files
           (client_id, declaration_no, direction, file_kind,
            backend_key, original_filename, sha256, size_bytes)
           values (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (client_id, decl_no, direction, file_kind, key, filename,
         sha256_bytes(blob), len(blob)),
    )


def _seed(cid: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing",
            (cid, "PDF merge test"),
        )
        # Imports: DEC003 (later date), DEC001 (earliest), DEC002 (mid, NO file)
        _seed_bcct(cur, client_id=cid, decl_no="DEC003", direction="import",
                   registration_date="2026-04-23")
        _seed_bcct(cur, client_id=cid, decl_no="DEC001", direction="import",
                   registration_date="2026-04-19")
        _seed_bcct(cur, client_id=cid, decl_no="DEC002", direction="import",
                   registration_date="2026-04-21")
        _seed_file(cur, client_id=cid, decl_no="DEC001", direction="import",
                   marker="MARKDECONE", filename="dec001.xls")
        _seed_file(cur, client_id=cid, decl_no="DEC003", direction="import",
                   marker="MARKDECTHREE", filename="dec003.xls")
        # DEC002 has a BCCT row but NO file → missing.
        # Export DEC500: single declaration, two files (ordering by filename).
        _seed_bcct(cur, client_id=cid, decl_no="DEC500", direction="export",
                   registration_date="2026-04-25")
        _seed_file(cur, client_id=cid, decl_no="DEC500", direction="export",
                   marker="MARKFILEB", filename="b_second.xls")
        _seed_file(cur, client_id=cid, decl_no="DEC500", direction="export",
                   marker="MARKFILEA", filename="a_first.xls")


def _teardown(cid: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(files_root, auth_disabled):
    cid = "pdf-" + secrets.token_hex(4)
    _seed(cid)
    yield cid
    _teardown(cid)


# ─── Happy paths ─────────────────────────────────────────────────────


def test_multi_declaration_import_merges_in_declaration_no_order(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import",
                "declaration_nos": "DEC003,DEC001,DEC002"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    # 3 requested; DEC001+DEC003 have files, DEC002 does not.
    assert r.headers["X-Declarations-Requested"] == "3"
    assert r.headers["X-Declarations-Included"] == "2"
    assert r.headers["X-Declarations-Missing"] == "1"
    assert r.headers["X-Declarations-Missing-Nos"] == "DEC002"
    assert r.headers["X-Render-Version"]
    # Valid PDF, ≥ one page per included declaration.
    assert _page_count(r.content) >= 2
    text = _pdf_text(r.content)
    # Default sort=declaration_no: DEC001 body before DEC003 body.
    assert text.index("MARKDECONE") < text.index("MARKDECTHREE")


def test_default_filename_when_omitted(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 200
    assert f'declarations_{seeded}_import.pdf' in r.headers["content-disposition"]


def test_custom_filename_sanitized(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001",
                "filename": "6. TKN GHEP"},
    )
    assert r.status_code == 200
    assert 'filename="6. TKN GHEP.pdf"' in r.headers["content-disposition"]


def test_single_declaration_multiple_files_ordered_by_filename(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "export", "declaration_nos": "DEC500"},
    )
    assert r.status_code == 200
    assert r.headers["X-Declarations-Included"] == "1"
    assert _page_count(r.content) >= 2
    text = _pdf_text(r.content)
    # a_first.xls before b_second.xls regardless of seed/insert order.
    assert text.index("MARKFILEA") < text.index("MARKFILEB")


def test_sort_registration_date(seeded):
    # By declaration_no DEC001 < DEC003, but by registration_date
    # DEC001 (04-19) < DEC003 (04-23) — here they agree, so add a third
    # whose declaration_no order differs from date order.
    with connect() as conn, conn.cursor() as cur:
        _seed_bcct(cur, client_id=seeded, decl_no="DEC900",
                   direction="import", registration_date="2026-04-01")
        _seed_file(cur, client_id=seeded, decl_no="DEC900",
                   direction="import", marker="MARKEARLIEST",
                   filename="dec900.xls")
    r = _client().get(
        _url(seeded),
        params={"direction": "import",
                "declaration_nos": "DEC001,DEC900",
                "sort": "registration_date"},
    )
    assert r.status_code == 200
    text = _pdf_text(r.content)
    # DEC900 registered 04-01 (earliest) → appears before DEC001 (04-19),
    # the opposite of declaration_no order.
    assert text.index("MARKEARLIEST") < text.index("MARKDECONE")


def test_mixed_present_missing_reports_headers(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import",
                "declaration_nos": "DEC001,DEC002,NOPE"},
    )
    assert r.status_code == 200
    assert r.headers["X-Declarations-Requested"] == "3"
    assert r.headers["X-Declarations-Included"] == "1"
    missing = r.headers["X-Declarations-Missing-Nos"].split(",")
    assert set(missing) == {"DEC002", "NOPE"}
    # PDF still valid + only the present declaration's pages.
    assert _page_count(r.content) >= 1
    assert "MARKDECONE" in _pdf_text(r.content)


def test_zero_match_returns_info_page(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DOES-NOT-EXIST"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["X-Declarations-Included"] == "0"
    assert r.headers["X-Declarations-Missing"] == "1"
    assert _page_count(r.content) == 1
    assert "Không có tờ khai" in _pdf_text(r.content)


# ─── Error paths ─────────────────────────────────────────────────────


def test_missing_direction_returns_400(seeded):
    r = _client().get(_url(seeded), params={"declaration_nos": "DEC001"})
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_direction"


def test_invalid_direction_returns_400(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "sideways", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_direction"


def test_missing_declaration_nos_returns_400(seeded):
    r = _client().get(_url(seeded), params={"direction": "import"})
    assert r.status_code == 400
    assert r.json()["detail"] == "declaration_nos_required"


def test_too_many_declaration_nos_returns_400(seeded):
    nos = ",".join(f"D{i:04d}" for i in range(501))
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": nos},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "too_many_declaration_nos"


def test_invalid_sort_returns_400(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001",
                "sort": "banana"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_sort"


def test_unknown_client_returns_404(auth_disabled, files_root):
    r = _client().get(
        _url("does-not-exist"),
        params={"direction": "import", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 404


# ─── Strict-mode auth (service token) ────────────────────────────────


@pytest.fixture
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_on(isolated_keys_dir):
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def auth_seeded(files_root, strict_mode_on):
    cid = "pdf-auth-" + secrets.token_hex(4)
    _seed(cid)
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.service_accounts where name like 'sa_test_%'"
        )
        cur.execute(
            "delete from hub.revoked_service_tokens "
            "where revoked_by='sa_test_runner'"
        )
    _teardown(cid)


def test_service_token_with_hub_read_returns_pdf(auth_seeded):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_service_token_without_hub_read_rejected(auth_seeded):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["bom:propose"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["bom:propose"], client_ids=None,
    )
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403


def test_service_token_client_whitelist_blocks_non_listed(auth_seeded):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=["a-different-client"], created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"],
        client_ids=["a-different-client"],
    )
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403


def test_no_bearer_in_strict_mode_returns_401(auth_seeded):
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 401


# ─── Render fidelity (env-gated on real sample data) ─────────────────


@pytest.mark.skipif(
    not os.environ.get("DATA_HUB_REAL_DATA_DIR"),
    reason="needs DATA_HUB_REAL_DATA_DIR pointing at a real declaration .xls dir",
)
def test_render_fidelity_real_declaration(files_root, auth_disabled):
    """Golden: a real ECUS .xls renders to the official tờ khai layout
    (the <IMP>/<EXP> watermark + title + page X/N markers present, no
    data loss). Reads from the real-data dir, never the repo."""
    real_dir = Path(os.environ["DATA_HUB_REAL_DATA_DIR"])
    samples = sorted(real_dir.rglob("*.xls"))
    samples = [s for s in samples if "_" in s.stem and s.stem.split("_")[-1].isdigit()]
    if not samples:
        pytest.skip("no per-declaration .xls under DATA_HUB_REAL_DATA_DIR")
    sample = samples[0]
    decl_no = sample.stem.split("_")[-1]
    cid = "pdf-real-" + secrets.token_hex(4)
    blob = sample.read_bytes()
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s,%s) "
                "on conflict do nothing", (cid, "real fidelity"),
            )
            _seed_bcct(cur, client_id=cid, decl_no=decl_no,
                       direction="import", registration_date="2026-01-01")
            _seed_file(cur, client_id=cid, decl_no=decl_no,
                       direction="import", marker="", filename=sample.name,
                       blob=blob)
        r = _client().get(
            _url(cid),
            params={"direction": "import", "declaration_nos": decl_no},
        )
        assert r.status_code == 200
        assert r.headers["X-Declarations-Included"] == "1"
        text = _pdf_text(r.content)
        assert "Tờ khai hàng hóa" in text
        assert "<IMP>" in text or "<EXP>" in text
        assert _page_count(r.content) >= 1
    finally:
        _teardown(cid)
