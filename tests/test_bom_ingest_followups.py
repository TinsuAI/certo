"""BOM ingest follow-ups (backlog B): detect ranking, multi-role warning,
friendly parse-error UX, and an end-to-end upload→preview→confirm guard.

  - B.1.5  adapter detect() / match_score ranking in parse_with_fallback
  - B.2.5  multi-role warning at upload (exported code added as BTP)
  - B.3    parse-error renders friendly HTML, not raw FastAPI JSON
  - B.2.7  regression: auto upload → preview → confirm
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app
from app.parsers import bom_adapters
from app.stores.bom_multirole import compute_multirole_warnings


CLIENT = "bom_followup_test"
USER_ID = "u_bom_followup"
USER_EMAIL = "bom-followup@test.local"


# ─────────────────────────── fixtures ───────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_files_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield
    storage_mod._BACKEND = None


@pytest.fixture(autouse=True)
def setup_client_and_user():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "bom followup test"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) "
            "values (%s, %s, 'BOM Followup', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-password")),
        )
    session_id = create_session(USER_ID)
    yield {"session_id": session_id}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.upload_pending where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.file_uploads where uploader_user_id=%s", (USER_ID,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))


@pytest.fixture
def http(setup_client_and_user):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, setup_client_and_user["session_id"])
    return c


def _save_xlsx(rows: list[tuple], title="BOM") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(c, blob, *, profile="auto", filename="bom.xlsx"):
    return c.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": profile},
        files={"file": (filename, blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )


# ───────────────────── B.1.5 detect / match_score ───────────────────────

# An ambiguous workbook: manual_flat sees product+material+qty columns AND
# sap_exploded_levels sees material+Level. Without scoring, manual_flat
# (registered earlier) would grab it and flatten the tree.
_AMBIGUOUS = [
    ("Mã SP", "Mã NVL", "Level", "Định mức", "ĐVT"),
    ("TP1",   "TP1",    1,       0,           ""),
    ("TP1",   "C1",     2,       3,           "kg"),
    ("TP1",   "C2",     2,       2,           "pcs"),
]

# A plain flat workbook with no Level column — both SAP adapters abstain.
_PLAIN_FLAT = [
    ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
    ("P-A",   "M-1",    1,           "kg"),
    ("P-A",   "M-2",    2,           "pcs"),
]


def test_detect_ranks_sap_exploded_over_manual_flat():
    """Ambiguous file (Level column present) must resolve to the
    structure-aware adapter, not generic manual_flat."""
    blob = _save_xlsx(_AMBIGUOUS)
    result = bom_adapters.parse_with_fallback(blob)
    assert result is not None
    _products, name = result
    assert name == "sap_exploded_levels", name


def test_detect_abstain_preserves_registration_order():
    """No Level column → all detect() abstain → registration order →
    manual_flat wins (no behaviour change vs. pre-scoring)."""
    blob = _save_xlsx(_PLAIN_FLAT)
    result = bom_adapters.parse_with_fallback(blob)
    assert result is not None
    _products, name = result
    assert name == "manual_flat", name


def test_detect_helpers_abstain_on_garbage():
    """_safe_detect swallows errors; ranking returns full registry."""
    assert bom_adapters._safe_detect(
        bom_adapters.resolve("manual_flat"), b"junk", None) is None
    ranked = bom_adapters._ranked_adapters(b"junk", None)
    assert len(ranked) == len(list(bom_adapters.adapters()))


# ───────────────────────── B.2.5 multi-role ─────────────────────────────

def _insert_export_bcct(code: str, *, decl="DEXP01", line="1"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bcct_rows "
            "(client_id, transaction_key, line_no, declaration_no, "
            " declaration_type, direction, registration_date, "
            " customs_code, goods_name, payload) "
            "values (%s, %s, %s, %s, 'B11', 'export', '2026-01-10', "
            "        %s, 'desc', '{}'::jsonb)",
            (CLIENT, f"{decl}-{line}", line, decl, code),
        )


def test_multirole_warns_only_for_exported_component():
    _insert_export_bcct("EXP1")
    products = {"TP": [
        {"material_code": "EXP1", "qty_per_unit": 1},   # exported → flagged
        {"material_code": "NVLX", "qty_per_unit": 2},   # never exported
    ]}
    warnings = compute_multirole_warnings(CLIENT, products)
    codes = {w["code"] for w in warnings}
    assert codes == {"EXP1"}
    assert warnings[0]["export_count"] == 1
    assert warnings[0]["export_declarations"] == 1


def test_multirole_empty_when_no_components():
    assert compute_multirole_warnings(CLIENT, {}) == []
    assert compute_multirole_warnings(CLIENT, {"TP": []}) == []


def test_multirole_warning_renders_in_preview(http):
    _insert_export_bcct("PV-EXPORTED")
    blob = _save_xlsx([
        ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
        ("ROOT-MR", "PV-EXPORTED", 1, "pcs"),
        ("ROOT-MR", "PLAIN-NVL", 2, "kg"),
    ])
    r = _upload(http, blob, profile="manual_flat", filename="mr.xlsx")
    # manual_flat cache-miss routes through the mapping page; drive it.
    assert r.status_code == 303
    loc = r.headers["location"]
    if "/upload/mapping/" in loc:
        upload_id = loc.rsplit("/", 1)[-1].split("?")[0]
        r = http.post(
            f"/clients/{CLIENT}/bom/upload/mapping/{upload_id}/parse",
            data={"header_row_override": "1",
                  "col_0__field": "product_code",  "col_0__header": "Mã SP",
                  "col_1__field": "material_code", "col_1__header": "Mã NVL",
                  "col_2__field": "qty_per_unit",  "col_2__header": "Định mức",
                  "col_3__field": "uom",           "col_3__header": "ĐVT"},
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        loc = r.headers["location"]
    assert "/preview/" in loc, loc
    pending_id = loc.rsplit("/", 1)[-1].split("?")[0]
    prev = http.get(f"/clients/{CLIENT}/bom/preview/{pending_id}")
    assert prev.status_code == 200
    assert "đa vai trò" in prev.text
    assert "PV-EXPORTED" in prev.text


# ─────────────────────── B.3 friendly parse error ───────────────────────

def test_parse_error_renders_html_not_json(http):
    """Garbage upload under auto → 400 with an HTML recovery page, not the
    raw FastAPI {"detail": ...} JSON."""
    r = _upload(http, b"definitely not an xlsx", profile="auto")
    assert r.status_code == 400
    ctype = r.headers["content-type"]
    assert ctype.startswith("text/html"), ctype
    assert '{"detail"' not in r.text
    # Recovery affordances from the template.
    assert "Tải lại file" in r.text
    assert f"/clients/{CLIENT}/bom/upload" in r.text


# ─────────────────── B.2.7 end-to-end upload regression ──────────────────

def test_auto_upload_preview_confirm_end_to_end(http):
    blob = _save_xlsx([
        ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
        ("E2E-TP", "E2E-M1", 2, "kg"),
        ("E2E-TP", "E2E-M2", 1, "pcs"),
    ], title="E2E-TP")
    # sheet_per_product layout (sheet title = product) lands on preview
    # directly under auto.
    r = _upload(http, blob, profile="auto", filename="E2E-TP.xlsx")
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert "/preview/" in loc, loc
    pending_id = loc.rsplit("/", 1)[-1].split("?")[0]

    prev = http.get(f"/clients/{CLIENT}/bom/preview/{pending_id}")
    assert prev.status_code == 200
    assert "E2E-TP" in prev.text

    conf = http.post(
        f"/clients/{CLIENT}/bom/preview/{pending_id}/confirm",
        follow_redirects=False,
    )
    assert conf.status_code == 303, conf.text
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts "
            "where client_id=%s and product_code=%s",
            (CLIENT, "E2E-TP"),
        )
        assert cur.fetchone()[0] >= 1
