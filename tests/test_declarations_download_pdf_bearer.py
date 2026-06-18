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
import shutil
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

# These exercise the real LibreOffice render path. soffice is a declared
# dependency (Dockerfile + CI install it); skip rather than hard-fail on a
# machine that doesn't have it, so the suite stays portable.
pytestmark = pytest.mark.skipif(
    shutil.which("soffice") is None,
    reason="LibreOffice (soffice) not installed",
)

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


def _image_pdf(px: int = 700) -> bytes:
    """A one-page PDF with a single px×px RGB image stored RAW (no
    compression) — a predictable large `file_kind="pdf"` blob for sizing
    the split (`max_part_bytes`) parts deterministically. Raw byte size ≈
    px*px*3 (e.g. px=300 ≈ 270 KB, px=500 ≈ 750 KB, px=900 ≈ 2.43 MB)."""
    w = h = px
    raw = bytearray()
    for y in range(h):
        for x in range(w):
            raw += bytes(((x * 255) // w, (y * 255) // h,
                          ((x + y) * 255) // (w + h)))
    raw = bytes(raw)
    content = b"q 200 0 0 200 50 600 cm /Im0 Do Q"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length %d >>\nstream\n"
        % (w, h, len(raw)) + raw + b"\nendstream",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.5\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for off in offs:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
            % (len(objs) + 1, xref))
    return bytes(out)


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


# ─── Perf headers + compact + split (new) ────────────────────────────


def _seed_imgs(cid: str, decls: list[tuple[str, bytes]],
               *, direction: str = "import") -> None:
    """Seed a client with one `pdf`-kind file per (decl_no, blob). No BCCT
    rows needed — inclusion is file-driven."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing", (cid, "pdf perf test"),
        )
        for decl_no, blob in decls:
            _seed_file(cur, client_id=cid, decl_no=decl_no, direction=direction,
                       marker="", filename=f"{decl_no}.pdf",
                       file_kind="pdf", blob=blob)


def test_no_new_params_adds_headers_unchanged_body(seeded):
    """Omitting quality + max_part_bytes: same X-Declarations-* contract,
    single application/pdf, with the additive perf headers present and
    quality defaulting to print."""
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001,DEC003"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["X-Declarations-Requested"] == "2"
    assert r.headers["X-Declarations-Included"] == "2"
    # Additive headers always present.
    assert int(r.headers["X-Render-Ms"]) >= 0
    assert int(r.headers["X-Pdf-Bytes"]) == len(r.content)
    assert r.headers["X-Pdf-Parts"] == "1"
    assert r.headers["X-Pdf-Quality"] == "print"
    assert "X-Render-CacheHits" in r.headers
    assert "X-Render-CacheMisses" in r.headers
    # No split → no oversize header.
    assert "X-Pdf-Oversize-Nos" not in r.headers


def test_warm_cache_hits_and_faster(seeded):
    """First call renders the .xls (miss); identical second call serves it
    from the render cache (hit) and is faster."""
    params = {"direction": "import", "declaration_nos": "DEC001"}
    r1 = _client().get(_url(seeded), params=params)
    assert r1.status_code == 200
    assert int(r1.headers["X-Render-CacheMisses"]) >= 1
    r2 = _client().get(_url(seeded), params=params)
    assert r2.status_code == 200
    assert int(r2.headers["X-Render-CacheHits"]) >= 1
    assert int(r2.headers["X-Render-CacheMisses"]) == 0
    # soffice render dominates the cold call; the warm call only reads the
    # cache + concatenates, so it is strictly faster.
    assert int(r2.headers["X-Render-Ms"]) < int(r1.headers["X-Render-Ms"])
    # Same body content.
    assert _pdf_text(r1.content).strip() == _pdf_text(r2.content).strip()


def test_compact_lossless_dedup_smaller_no_field_loss(files_root, auth_disabled):
    """quality=compact (lossless object dedup): 200 pdf, smaller X-Pdf-Bytes
    than print, same page count, text fields preserved. Several declarations
    sharing the same .xls render embed duplicate font programs after the
    merge; dedup merges them with zero quality loss."""
    cid = "pdf-cmp-" + secrets.token_hex(4)
    try:
        # Same form content under 4 declaration_nos → many duplicate objects
        # in the merge for dedup to collapse (a realistic shape: every tờ
        # khai uses the same embedded fonts).
        blob = _decl_xls("MARKFIELD")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s,%s) "
                "on conflict do nothing", (cid, "compact test"),
            )
            for n in ("DEC701", "DEC702", "DEC703", "DEC704"):
                _seed_file(cur, client_id=cid, decl_no=n, direction="import",
                           marker="", filename=f"{n}.xls", blob=blob)
        nos = "DEC701,DEC702,DEC703,DEC704"
        base = {"direction": "import", "declaration_nos": nos}
        rp = _client().get(_url(cid), params={**base, "quality": "print"})
        rc = _client().get(_url(cid), params={**base, "quality": "compact"})
        assert rp.status_code == 200 and rc.status_code == 200
        assert rc.headers["content-type"] == "application/pdf"
        assert rc.headers["X-Pdf-Quality"] == "pypdf-dedup-1"
        print_bytes = int(rp.headers["X-Pdf-Bytes"])
        compact_bytes = int(rc.headers["X-Pdf-Bytes"])
        assert compact_bytes < print_bytes
        # Lossless: text survives, page count preserved.
        assert "MARKFIELD" in _pdf_text(rc.content)
        assert _page_count(rc.content) == _page_count(rp.content)
    finally:
        _teardown(cid)


def test_max_part_bytes_under_limit_returns_single_pdf(files_root, auth_disabled):
    """When the merged PDF already fits under the cap, return a single
    application/pdf (no zip)."""
    cid = "pdf-fit-" + secrets.token_hex(4)
    try:
        _seed_imgs(cid, [("DEC010", _image_pdf(300))])  # ~270 KB << 2 MB
        r = _client().get(
            _url(cid),
            params={"direction": "import", "declaration_nos": "DEC010",
                    "max_part_bytes": "2000000"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.headers["X-Pdf-Parts"] == "1"
        assert "X-Pdf-Oversize-Nos" not in r.headers
    finally:
        _teardown(cid)


def test_max_part_bytes_over_limit_returns_zip_parts(files_root, auth_disabled):
    """Merged PDF over the cap → application/zip of declaration-boundary
    parts, each ≤ cap (except a declaration that alone exceeds it),
    deterministic names + order, reassembling to the same page set."""
    import io
    import zipfile

    cid = "pdf-zip-" + secrets.token_hex(4)
    cap = 2_000_000
    try:
        # 4 × ~750 KB (pack 2/part) + 1 × ~2.43 MB (oversize, own part).
        _seed_imgs(cid, [
            ("DEC301", _image_pdf(500)),
            ("DEC302", _image_pdf(500)),
            ("DEC303", _image_pdf(500)),
            ("DEC304", _image_pdf(500)),
            ("DECBIG", _image_pdf(900)),
        ])
        nos = "DEC301,DEC302,DEC303,DEC304,DECBIG"
        r = _client().get(
            _url(cid),
            params={"direction": "import", "declaration_nos": nos,
                    "max_part_bytes": str(cap)},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert "attachment" in r.headers["content-disposition"]
        assert r.headers["content-disposition"].endswith('.zip"')
        nparts = int(r.headers["X-Pdf-Parts"])
        assert nparts >= 2
        # DECBIG alone exceeds the cap → flagged oversize.
        assert r.headers["X-Pdf-Oversize-Nos"] == "DECBIG"

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        # Deterministic names + order.
        expected = [f"declarations_{cid}_import-part-{i:03d}.pdf"
                    for i in range(1, nparts + 1)]
        assert names == expected
        # Sum of part bytes == X-Pdf-Bytes.
        assert sum(len(zf.read(n)) for n in names) == int(r.headers["X-Pdf-Bytes"])
        # Every part ≤ cap except the one carrying the oversize declaration.
        over = [len(zf.read(n)) > cap for n in names]
        assert sum(over) == 1  # exactly the oversize part
        # Reassemble: total pages across parts == one page per declaration.
        total_pages = sum(_page_count(zf.read(n)) for n in names)
        assert total_pages == 5
    finally:
        _teardown(cid)


def test_compact_plus_max_part_bytes_combined(files_root, auth_disabled):
    """compact + max_part_bytes together: declaration units are deduped,
    then packed. Each declaration alone is small here, so the result is a
    single application/pdf ≤ cap (lossless), proving the two params compose."""
    cid = "pdf-cs-" + secrets.token_hex(4)
    cap = 2_000_000
    try:
        blob = _decl_xls("MARKCS")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s,%s) "
                "on conflict do nothing", (cid, "compact+split test"),
            )
            for n in ("DEC801", "DEC802", "DEC803", "DEC804"):
                _seed_file(cur, client_id=cid, decl_no=n, direction="import",
                           marker="", filename=f"{n}.xls", blob=blob)
        nos = "DEC801,DEC802,DEC803,DEC804"
        rc = _client().get(
            _url(cid),
            params={"direction": "import", "declaration_nos": nos,
                    "quality": "compact", "max_part_bytes": str(cap)},
        )
        assert rc.status_code == 200
        assert rc.headers["content-type"] == "application/pdf"
        assert rc.headers["X-Pdf-Parts"] == "1"
        assert int(rc.headers["X-Pdf-Bytes"]) <= cap
        assert "MARKCS" in _pdf_text(rc.content)
        assert _page_count(rc.content) >= 4  # ≥ one page per declaration
    finally:
        _teardown(cid)


def test_invalid_quality_returns_400(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001",
                "quality": "ultra"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_quality"


def test_invalid_max_part_bytes_returns_400(seeded):
    for bad in ("0", "-5", "abc"):
        r = _client().get(
            _url(seeded),
            params={"direction": "import", "declaration_nos": "DEC001",
                    "max_part_bytes": bad},
        )
        assert r.status_code == 400, bad
        assert r.json()["detail"] == "invalid_max_part_bytes"
