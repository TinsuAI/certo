"""Upload-route flatten tests via FastAPI TestClient.
Spec items: 19 (non_flattened cannot be materialized without explicit
confirmation), 26 (preview/confirm creates expected versions/statuses/
evidence/decisions/rows).
"""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.database import connect
from app.main import app
from app.stores import flatten_decisions as decisions_store


CLIENT = "flat_test_upload"


@pytest.fixture(autouse=True)
def setup_client_and_user():
    """Insert a test client + ensure the dev admin can edit it. Tear down."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, %s) on conflict (client_id) do nothing
                """,
                (CLIENT, "flatten upload test"),
            )
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


@pytest.fixture
def auth_client():
    """Authenticated TestClient using the dev admin user (auto-loaded by
    seed). The session cookie is set by login first."""
    client = TestClient(app, follow_redirects=False)
    resp = client.post("/login",
                       data={"email": "admin@data-hub.local", "password": "admin123"})
    # Either 200 or 303 depending on whether already logged in.
    assert resp.status_code in (200, 303)
    return client


def _xlsx(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Item 26: preview/confirm creates expected versions ────────────────

def test_technical_flatten_preview_then_confirm(auth_client):
    """Upload a 2-product BOM where TP-A explodes through BTP-B which
    has NVL-1 in catalog. Preview lands; confirm materializes both TP-A
    and BTP-B with structured identity."""
    # Seed catalog: NVL-1 is active NVL with kg unit; BTP-B is btp_sx; TP-A is tp.
    with connect() as conn:
        with conn.cursor() as cur:
            for code, cat, unit in [("FT_U_NVL-1", "nvl", "kg"),
                                    ("FT_U_BTP-B", "btp_sx", "kg"),
                                    ("FT_U_TP-A",  "tp",     "kg")]:
                cur.execute(
                    """
                    insert into hub.materials (client_id, customs_code, category, unit, status)
                    values (%s, %s, %s, %s, 'active')
                    on conflict do nothing
                    """,
                    (CLIENT, code, cat, unit),
                )
    blob = _xlsx([
        ("Mã SP",      "Mã NVL",       "Định mức", "ĐVT"),
        ("FT_U_TP-A",  "FT_U_BTP-B",   1,          "kg"),
        ("FT_U_BTP-B", "FT_U_NVL-1",   2,          "kg"),
    ])
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": ("bom.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303
    assert "/bom/flatten-preview/" in resp.headers["location"]
    pending_id = resp.headers["location"].split("/")[-1]

    # Preview renders.
    resp = auth_client.get(f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}")
    assert resp.status_code == 200
    assert b"technical_flatten" in resp.content
    assert b"FT_U_TP-A" in resp.content

    # Confirm with no decisions (no dual-source, no UOM issues — should
    # still materialize because all decisions for plain technical_exploded
    # are auto-statused or none required).
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
        data={},
    )
    assert resp.status_code == 303

    # Both TP-A and BTP-B should be flattened versions in the DB.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select product_code, source_bom_kind, flatten_status, flatten_strategy
                from hub.bom_artifacts
                where client_id = %s
                  and product_code in ('FT_U_TP-A', 'FT_U_BTP-B')
                order by product_code
                """,
                (CLIENT,),
            )
            rows = cur.fetchall()
    assert len(rows) == 2
    by_code = {r[0]: r for r in rows}
    assert by_code["FT_U_TP-A"][1] == "technical_flattened"
    assert by_code["FT_U_TP-A"][2] == "flattened"
    assert by_code["FT_U_TP-A"][3] == "technical_exploded"
    assert by_code["FT_U_BTP-B"][2] == "flattened"


# ── Item 19: non_flattened cannot be materialized without confirmation ──

def test_non_flattened_blocked_without_confirmation(auth_client):
    """Upload a TP whose component has no evidence anywhere — yields
    non_flattened version. Confirm without confirming the
    `non_flattened_publish` decision should NOT materialize the version.
    """
    blob = _xlsx([
        ("Mã SP",         "Mã NVL",      "Định mức", "ĐVT"),
        ("FT_U_BLOCK",    "FT_U_GHOST",  1,          "kg"),
    ])
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": ("bom.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303
    pending_id = resp.headers["location"].split("/")[-1]

    # Confirm with NO confirmation flags — non_flattened_publish is rejected.
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
        data={},
    )
    assert resp.status_code == 303
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.bom_artifacts "
                "where client_id = %s and product_code = 'FT_U_BLOCK'",
                (CLIENT,),
            )
            (n,) = cur.fetchone()
    assert n == 0, "non_flattened version was materialized without confirmation"


def test_non_flattened_published_when_confirmed(auth_client):
    """Same scenario, but staff explicitly confirms the
    non_flattened_publish decision with publish_with_review_required."""
    blob = _xlsx([
        ("Mã SP",         "Mã NVL",          "Định mức", "ĐVT"),
        ("FT_U_REVIEW",   "FT_U_GHOST2",     1,          "kg"),
    ])
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": ("bom.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    pending_id = resp.headers["location"].split("/")[-1]
    decisions = decisions_store.decisions_for_pending(pending_id)
    nf = next(d for d in decisions if d["decision_type"] == "non_flattened_publish")

    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
        data={
            f"confirm_{nf['decision_id']}": "on",
            f"choose_{nf['decision_id']}": "publish_with_review_required",
        },
    )
    assert resp.status_code == 303
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select flatten_status from hub.bom_artifacts
                where client_id = %s and product_code = 'FT_U_REVIEW'
                """,
                (CLIENT,),
            )
            row = cur.fetchone()
    assert row is not None
    assert row[0] == "non_flattened"


# ── /rev finding C1: dual-source variants blocked without confirmation ──

def test_dual_source_blocked_without_explicit_confirmation(auth_client):
    """Spec §11 — dual-source variants MUST NOT materialize unless staff
    explicitly confirms the dual_source_variant decision. Empty form →
    both candidate variants are filtered out by publish_filter."""
    # Seed BCCT-import evidence for FT_U_DBTP — gives flatten engine
    # the dual-source signal alongside the same-upload child BOM.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, registration_date,
                   declaration_no, declaration_type, direction,
                   customs_code, goods_name)
                values (%s, 'FT_DUAL_TX', '1', '2026-01-01',
                        'FT_DUAL_DECL', 'E11', 'import',
                        'FT_U_DBTP', 'imported BTP')
                """,
                (CLIENT,),
            )
            for code, cat, unit in [("FT_U_DNVL", "nvl", "kg"),
                                    ("FT_U_DBTP", "btp_sx", "kg")]:
                cur.execute(
                    """
                    insert into hub.materials (client_id, customs_code, category, unit, status)
                    values (%s, %s, %s, %s, 'active')
                    on conflict do nothing
                    """,
                    (CLIENT, code, cat, unit),
                )
    blob = _xlsx([
        ("Mã SP",      "Mã NVL",      "Định mức", "ĐVT"),
        ("FT_U_DTP",   "FT_U_DBTP",   1,          "kg"),
        ("FT_U_DBTP",  "FT_U_DNVL",   0.5,        "kg"),
    ])
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": ("bom.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303
    pending_id = resp.headers["location"].split("/")[-1]

    # Sanity: engine emitted a dual_source_variant decision.
    decisions = decisions_store.decisions_for_pending(pending_id)
    assert any(d["decision_type"] == "dual_source_variant" for d in decisions)

    # Confirm with empty form — no dual_source_variant confirmation.
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
        data={},
    )
    assert resp.status_code == 303

    # Neither dual-source variant of FT_U_DTP should land. BTP-B can land
    # on its own (it's a separate version, no dual_source_variant
    # decision for it).
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*) from hub.bom_artifacts
                where client_id = %s and product_code = 'FT_U_DTP'
                """,
                (CLIENT,),
            )
            (n_tp,) = cur.fetchone()
    assert n_tp == 0, ("dual-source TP variants materialized without "
                       "explicit staff confirmation")


def test_dual_source_publishes_chosen_variant_when_confirmed(auth_client):
    """Same scenario, but staff confirms with chosen='purchased_btp_as_leaf'.
    Only the purchased variant should land; self_produced should not."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, registration_date,
                   declaration_no, declaration_type, direction,
                   customs_code, goods_name)
                values (%s, 'FT_DUAL2_TX', '1', '2026-01-01',
                        'FT_DUAL2_DECL', 'E11', 'import',
                        'FT_U_PBTP', 'imported BTP 2')
                """,
                (CLIENT,),
            )
            for code, cat, unit in [("FT_U_PNVL", "nvl", "kg"),
                                    ("FT_U_PBTP", "btp_sx", "kg")]:
                cur.execute(
                    """
                    insert into hub.materials (client_id, customs_code, category, unit, status)
                    values (%s, %s, %s, %s, 'active')
                    on conflict do nothing
                    """,
                    (CLIENT, code, cat, unit),
                )
    blob = _xlsx([
        ("Mã SP",      "Mã NVL",     "Định mức", "ĐVT"),
        ("FT_U_PTP",   "FT_U_PBTP",  1,          "kg"),
        ("FT_U_PBTP",  "FT_U_PNVL",  0.5,        "kg"),
    ])
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": ("bom.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    pending_id = resp.headers["location"].split("/")[-1]
    decisions = decisions_store.decisions_for_pending(pending_id)
    dual = next(d for d in decisions if d["decision_type"] == "dual_source_variant")

    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
        data={
            f"confirm_{dual['decision_id']}": "on",
            f"choose_{dual['decision_id']}": "purchased_btp_as_leaf",
        },
    )
    assert resp.status_code == 303

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select flatten_strategy from hub.bom_artifacts
                where client_id = %s and product_code = 'FT_U_PTP'
                """,
                (CLIENT,),
            )
            strategies = [r[0] for r in cur.fetchall()]
    assert strategies == ["purchased_btp_as_leaf"]


# ── Idempotent re-upload (same blob twice → 0 new versions) ──────────

def test_duplicate_technical_flatten_upload_is_idempotent(auth_client):
    """Spec §"append-only versioning preserved" — same content uploaded
    twice yields the same artifact_ids; create_artifact's idempotency
    lookup returns existing rows on the second pass.
    """
    blob = _xlsx([
        ("Mã SP",       "Mã NVL",      "Định mức", "ĐVT"),
        ("FT_DUP_TP",   "FT_DUP_NVL",  1,          "kg"),
    ])
    # Seed material so it lands as catalog leaf (flattens cleanly without
    # any pending decisions).
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials (client_id, customs_code, category, unit, status)
            values (%s, 'FT_DUP_NVL', 'nvl', 'kg', 'active')
            on conflict do nothing
            """,
            (CLIENT,),
        )

    def _upload_and_confirm() -> int:
        resp = auth_client.post(
            f"/clients/{CLIENT}/bom/upload",
            data={"profile": "technical_flatten"},
            files={"file": ("bom.xlsx", blob,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code == 303
        pending_id = resp.headers["location"].split("/")[-1]
        resp = auth_client.post(
            f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
            data={},
        )
        assert resp.status_code == 303
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.bom_artifacts "
                "where client_id = %s and product_code = 'FT_DUP_TP'",
                (CLIENT,),
            )
            return cur.fetchone()[0]

    n_first = _upload_and_confirm()
    n_second = _upload_and_confirm()
    assert n_first == 1
    assert n_second == 1, "duplicate upload created a new version"


# ── Johnson SAP exploded parser feeds the flatten engine cleanly ─────

def test_johnson_sap_fixture_flattens_via_sap_indented_walk(auth_client):
    """SAP-indented Johnson fixture is parsed by `sap_indented_walk`
    (filename stem becomes root code). The adapter pre-multiplies qty
    through the ancestor chain and emits leaf rows with
    explicit_context='do_not_explode' — engine treats them as explicit
    leaves with no decisions required, materializing ONE flattened
    version under the filename root (no intermediate BTP versions).
    """
    fixture = Path("tests/fixtures/edge_cases/johnson_sap_english_headers.xlsx")
    if not fixture.exists():
        pytest.skip(f"missing fixture: {fixture}")
    blob = fixture.read_bytes()
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": (fixture.name, blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303, f"upload didn't reach preview: {resp.text}"
    assert "/flatten-preview/" in resp.headers["location"]

    pending_id = resp.headers["location"].split("/")[-1]
    decisions = decisions_store.decisions_for_pending(pending_id)
    # No decisions = clean flatten. The pre-flatten path emits leaves
    # via explicit_purchased evidence, so no staff gates fire.
    assert all(d["status"] == "auto" for d in decisions), \
        "sap_indented_walk should emit no pending decisions"

    # Confirm with empty form → clean materialization.
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/flatten-preview/{pending_id}/confirm",
        data={},
    )
    assert resp.status_code == 303
    # Exactly ONE BOM version under the filename stem; no intermediate BTPs.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select product_code, source_bom_kind, flatten_status
            from hub.bom_artifacts
            where client_id = %s
              and product_code = 'johnson_sap_english_headers'
            """,
            (CLIENT,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "technical_flattened"
    assert rows[0][2] == "flattened"


# ── Growatt Chinese-headers fixture also flattens via fallback ───────

def test_growatt_chinese_fixture_flattens_via_manual_flat(auth_client):
    """The Growatt fixture has Chinese headers but the manual_flat
    aliases include zh terms — so it parses with manual_flat and the
    engine runs without falling through. Asserts the upload reaches
    preview (i.e. the parser worked)."""
    fixture = Path("tests/fixtures/edge_cases/growatt_bom_chinese_headers.xlsx")
    if not fixture.exists():
        pytest.skip(f"missing fixture: {fixture}")
    blob = fixture.read_bytes()
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "technical_flatten"},
        files={"file": (fixture.name, blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303
    assert "/flatten-preview/" in resp.headers["location"]


# ── manual_flat path is unaffected ────────────────────────────────────

def test_manual_flat_profile_routes_to_mapping_page(auth_client):
    """Slice 3 of the unified upload flow: manual_flat first goes through
    the interactive mapping page on cache miss (was: straight to preview).
    Crucially does NOT route to flatten-preview, since profile is not
    technical_flatten."""
    blob = _xlsx([
        ("Mã SP",      "Mã NVL",   "Định mức", "ĐVT"),
        ("FT_U_LEGACY","FT_U_M",   1,          "kg"),
    ])
    resp = auth_client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": "manual_flat"},
        files={"file": ("bom.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 303
    assert "/bom/upload/mapping/" in resp.headers["location"]
    assert "/bom/flatten-preview/" not in resp.headers["location"]
