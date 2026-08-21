"""Provider tests for the `depth` picker filter on
`/v1/hub/products/{p}/bom/artifacts`.

`depth=full` excludes SHALLOW flats (flatten_strategy='purchased_btp_as_leaf'
and the conservatively-shallow mixed_confirmed / no_strategy flattened rows)
so a structurally-incomplete BOM can't leak into CO's certificate-of-origin
picker alongside the fully-exploded version. `depth=any` (default / omitted)
is a no-op: every existing caller is unchanged.

Authoritative classification lives in app.stores.bom.is_shallow_flatten
(single-sourced with bom_shape), NOT re-encoded here.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from tests.test_bom_artifacts_picker_filter import _ins


def _client() -> TestClient:
    return TestClient(app)


def _bearer() -> dict:
    return {"authorization": "Bearer smoke"}


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(auth_disabled):
    """Throwaway client + artifacts spanning the depth dimension.

    Product DA (strategy mix, all published + flat):
      full    technical_exploded        → kept by depth=full
      shallow purchased_btp_as_leaf     → DROPPED by depth=full
      manual  manual_flat_as_provided   → kept (leaf-complete by assertion)
      na      not_applicable/no_strategy → kept (not shallow)

    Product DB (only a shallow flat):
      shallow purchased_btp_as_leaf     → depth=full ⇒ empty

    Product DC (same bom_variant_id 'v', shallow + full):
      full    technical_exploded
      shallow purchased_btp_as_leaf     → separate partition, dropped by depth=full

    Product DD (full picker combination):
      full    published staff_edit technical_exploded
      shallow published staff_edit purchased_btp_as_leaf
      draft   draft     staff_edit technical_exploded (dropped by lifecycle)
    """
    cid = "bom-depth-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, %s, 'simple_mapping', 'auto')",
            (cid, "depth-test"),
        )
        # Product DA
        _ins(cur, aid=f"{cid}_DA_full", client=cid, product="DA",
             artifact_no=1, flatten_strategy="technical_exploded",
             published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_DA_shallow", client=cid, product="DA",
             artifact_no=2, flatten_strategy="purchased_btp_as_leaf",
             published_iso="2026-05-11T00:00:00Z")
        _ins(cur, aid=f"{cid}_DA_manual", client=cid, product="DA",
             artifact_no=3, flatten_strategy="manual_flat_as_provided",
             published_iso="2026-05-12T00:00:00Z")
        _ins(cur, aid=f"{cid}_DA_na", client=cid, product="DA",
             artifact_no=4, flatten_status="not_applicable",
             flatten_strategy="no_strategy",
             published_iso="2026-05-13T00:00:00Z")
        # Product DB — only shallow
        _ins(cur, aid=f"{cid}_DB_shallow", client=cid, product="DB",
             artifact_no=1, flatten_strategy="purchased_btp_as_leaf",
             published_iso="2026-05-10T00:00:00Z")
        # Product DC — same variant, two strategies (two partitions)
        _ins(cur, aid=f"{cid}_DC_full", client=cid, product="DC",
             artifact_no=1, variant="v", flatten_strategy="technical_exploded",
             published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_DC_shallow", client=cid, product="DC",
             artifact_no=2, variant="v",
             flatten_strategy="purchased_btp_as_leaf",
             published_iso="2026-05-11T00:00:00Z")
        # Product DD — full picker combination
        _ins(cur, aid=f"{cid}_DD_full", client=cid, product="DD",
             artifact_no=1, intent="staff_edit",
             flatten_strategy="technical_exploded",
             published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_DD_shallow", client=cid, product="DD",
             artifact_no=2, intent="staff_edit",
             flatten_strategy="purchased_btp_as_leaf",
             published_iso="2026-05-11T00:00:00Z")
        _ins(cur, aid=f"{cid}_DD_draft", client=cid, product="DD",
             artifact_no=3, intent="staff_edit", status="draft",
             flatten_strategy="technical_exploded", published_iso=None)
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _url(product: str) -> str:
    return f"/v1/hub/products/{product}/bom/artifacts"


def _aids(body) -> set[str]:
    return {it["artifact_id"] for it in body["items"]}


# ─── 1. depth=full excludes shallow, keeps the rest ──────────────────


def test_depth_full_excludes_only_shallow(seeded):
    r = _client().get(_url("DA"), params={
        "client_id": seeded, "shape": "flat", "depth": "full",
    }, headers=_bearer())
    assert r.status_code == 200, r.text
    aids = _aids(r.json())
    assert aids == {
        f"{seeded}_DA_full", f"{seeded}_DA_manual", f"{seeded}_DA_na",
    }
    assert f"{seeded}_DA_shallow" not in aids


# ─── 2. depth=any and omitted == current shape=flat behavior ─────────


def test_depth_any_and_omitted_match_legacy_flat(seeded):
    base = _client().get(_url("DA"), params={
        "client_id": seeded, "shape": "flat",
    }, headers=_bearer())
    any_ = _client().get(_url("DA"), params={
        "client_id": seeded, "shape": "flat", "depth": "any",
    }, headers=_bearer())
    assert base.status_code == 200 and any_.status_code == 200
    # shallow IS returned in both, and the two are identical.
    assert _aids(base.json()) == _aids(any_.json())
    assert f"{seeded}_DA_shallow" in _aids(base.json())


# ─── 3. only-shallow product + depth=full ⇒ empty ────────────────────


def test_depth_full_only_shallow_returns_empty(seeded):
    r = _client().get(_url("DB"), params={
        "client_id": seeded, "shape": "flat", "depth": "full",
    }, headers=_bearer())
    assert r.status_code == 200
    assert r.json()["items"] == []


# ─── 4. depth=full composes with the full picker filter set ──────────


def test_depth_full_composes_with_full_picker(seeded):
    r = _client().get(_url("DD"), params={
        "client_id": seeded, "lifecycle": "active", "shape": "flat",
        "intents": "staff_edit", "latest_per_variant": "true",
        "depth": "full", "case_id": "irrelevant",
    }, headers=_bearer())
    assert r.status_code == 200
    # draft drops on lifecycle, shallow drops on depth → only the full row.
    assert _aids(r.json()) == {f"{seeded}_DD_full"}


# ─── 5. latest_per_variant + depth=full drops the shallow partition ──


def test_latest_per_variant_depth_full_drops_shallow_partition(seeded):
    r = _client().get(_url("DC"), params={
        "client_id": seeded, "latest_per_variant": "true", "depth": "full",
    }, headers=_bearer())
    assert r.status_code == 200
    # shallow and full are SEPARATE partitions; depth=full removes the
    # shallow one entirely rather than letting it win.
    assert _aids(r.json()) == {f"{seeded}_DC_full"}


# ─── 6. filter_applied echoes depth ──────────────────────────────────


def test_filter_applied_echoes_depth(seeded):
    for supplied, expected in [(None, "any"), ("any", "any"), ("full", "full")]:
        params = {"client_id": seeded}
        if supplied is not None:
            params["depth"] = supplied
        r = _client().get(_url("DA"), params=params, headers=_bearer())
        assert r.status_code == 200
        assert r.json()["filter_applied"]["depth"] == expected


# ─── 7. invalid depth ⇒ 400 invalid_depth ────────────────────────────


def test_invalid_depth_returns_400(seeded):
    r = _client().get(_url("DA"), params={
        "client_id": seeded, "depth": "foo",
    }, headers=_bearer())
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_depth"


# ─── 8. is_shallow item flag ─────────────────────────────────────────


def test_is_shallow_flag_per_item(seeded):
    r = _client().get(_url("DA"), params={"client_id": seeded},
                      headers=_bearer())
    assert r.status_code == 200
    by_aid = {it["artifact_id"]: it for it in r.json()["items"]}
    assert by_aid[f"{seeded}_DA_shallow"]["is_shallow"] is True
    assert by_aid[f"{seeded}_DA_full"]["is_shallow"] is False
    assert by_aid[f"{seeded}_DA_manual"]["is_shallow"] is False
    assert by_aid[f"{seeded}_DA_na"]["is_shallow"] is False
