"""Track D Phase D — UI badges + API exposure for stale BOM artifacts.

API: GET /api/v1/products/{product_code}/bom?artifact_id=<id> response
includes is_stale + stale_reasons in artifact dict.

UI: bom_artifacts.html row + bom_artifact_detail.html section render
a "stale" badge when is_stale=true.

Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`,
"UI surface" + "API surface (BCQT/CO consumer)" sections.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app


CLIENT = "track_d_uiapi_test"
USER_ID = "test_track_d_uiapi_user"
USER_EMAIL = "track_d_uiapi@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "Track D ui+api test"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) values (%s, %s, 'tester', %s, "
            "'admin', 'active') on conflict (user_id) do update set "
            "role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-password")),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


@pytest.fixture
def http():
    sid = create_session(USER_ID)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, sid)
    return c


def _insert_stale(artifact_id: str, *, is_stale: bool = True,
                   product_code: str = "P_UI") -> None:
    reasons = [{"dim": "catalog_category",
                 "source_table": "hub.materials",
                 "source_pk": f"{CLIENT}/M-X",
                 "observed_at": "2026-05-11T00:00:00Z"}]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at, is_stale, "
            "stale_reasons) values (%s, %s, %s, 1, 'published', "
            "'agency_staff', 'asserted_technical', '{}', %s, 0, "
            "'technical_flattened', 'flattened', 'technical_exploded', "
            "'staff_form', 'default', '{}', 'as_provided', 'v1', "
            "now(), %s, %s::jsonb)",
            (artifact_id, CLIENT, product_code, f"h_{artifact_id}",
             is_stale, json.dumps(reasons if is_stale else [])),
        )
        conn.commit()


# ────────────────────────────────────────────────────────────────────
# API: artifact endpoint exposes is_stale + stale_reasons.
# ────────────────────────────────────────────────────────────────────


def _bearer_token() -> str:
    from app import jwt_issuer
    return jwt_issuer.make_token(
        user_id=USER_ID, email=USER_EMAIL, role="admin",
        display_name="API tester",
    )["access_token"]


def test_api_artifact_endpoint_includes_is_stale(http):
    aid = "ba_api_stale"
    _insert_stale(aid, is_stale=True)
    token = _bearer_token()

    r = http.get(
        f"/v1/hub/products/P_UI/bom?client_id={CLIENT}&artifact_id={aid}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    artifact = body["artifact"]
    assert artifact["is_stale"] is True, (
        f"Artifact dict must expose is_stale; keys={list(artifact.keys())}"
    )
    assert "stale_reasons" in artifact
    assert isinstance(artifact["stale_reasons"], list)
    assert len(artifact["stale_reasons"]) == 1
    assert artifact["stale_reasons"][0]["dim"] == "catalog_category"


def test_api_artifact_endpoint_is_stale_false_when_fresh(http):
    aid = "ba_api_fresh"
    _insert_stale(aid, is_stale=False)
    token = _bearer_token()

    r = http.get(
        f"/v1/hub/products/P_UI/bom?client_id={CLIENT}&artifact_id={aid}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    artifact = r.json()["artifact"]
    assert artifact["is_stale"] is False
    assert artifact["stale_reasons"] == []


# ────────────────────────────────────────────────────────────────────
# UI: stale badge appears in bom_artifact_detail page.
# ────────────────────────────────────────────────────────────────────


def test_artifact_detail_renders_stale_badge_when_stale(http):
    aid = "ba_ui_stale"
    _insert_stale(aid, is_stale=True)

    r = http.get(f"/clients/{CLIENT}/bom/artifact/{aid}")
    assert r.status_code == 200, r.text
    body = r.text
    # Use the stable i18n key for the badge so the test doesn't break
    # on copy edits.
    assert 'data-stale-badge="1"' in body, (
        "Detail page must render a stale badge (look for "
        "data-stale-badge=\"1\" element). HTML lacks the marker."
    )
    # Refresh button should be present.
    assert "refresh" in body.lower(), (
        "Detail page must offer a refresh button when artifact is stale."
    )


def test_artifact_detail_no_stale_badge_when_fresh(http):
    aid = "ba_ui_fresh"
    _insert_stale(aid, is_stale=False)

    r = http.get(f"/clients/{CLIENT}/bom/artifact/{aid}")
    assert r.status_code == 200
    assert 'data-stale-badge="1"' not in r.text


def test_artifacts_list_renders_per_row_stale_marker(http):
    aid_stale = "ba_list_stale"
    aid_fresh = "ba_list_fresh"
    _insert_stale(aid_stale, is_stale=True, product_code="P_LIST")
    _insert_stale(aid_fresh, is_stale=False, product_code="P_LIST")

    r = http.get(f"/clients/{CLIENT}/bom/P_LIST/artifacts")
    assert r.status_code == 200, r.text
    # Stable marker on the stale row only.
    assert 'data-stale-row="ba_list_stale"' in r.text
    assert 'data-stale-row="ba_list_fresh"' not in r.text
