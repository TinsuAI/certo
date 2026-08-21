"""Provider tests for POST /v1/hub/products/bom/artifacts:batch.

The batch endpoint is the multi-product fan-in of the per-product
GET /v1/hub/products/{product_code}/bom/artifacts. Its contract:
each results[product_code] envelope must be byte-identical to the
per-product endpoint with the same filters (plus embedded rows when
include_rows=true). These tests pin that parity + the batch-only
behaviours (pagination, missing, dedupe, fan-in).
"""
from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import connect
from app.stores import bom as bom_store

BATCH_URL = "/v1/hub/products/bom/artifacts:batch"
PER_PRODUCT_URL = "/v1/hub/products/{pc}/bom/artifacts"
PINNED_URL = "/v1/hub/products/{pc}/bom"


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


def _bearer(headers: dict | None = None) -> dict:
    h = dict(headers or {})
    h["authorization"] = "Bearer smoke"
    return h


def _mk_client(cur, cid: str) -> None:
    cur.execute(
        "insert into hub.clients (client_id, name, code_resolution_mode, "
        "bom_proposal_mode) values (%s, %s, 'simple_mapping', 'auto')",
        (cid, "batch-test"),
    )


def _ins(cur, *, aid, client, product, intent="staff_edit",
         status="published", tombstoned=False,
         flatten_status="not_applicable",
         flatten_strategy="manual_flat_as_provided",
         variant="default", artifact_no=1, published_iso=None,
         context: dict | None = None) -> None:
    """Insert one bom_artifacts row (no detail rows) with test defaults."""
    cur.execute(
        """insert into hub.bom_artifacts
           (artifact_id, client_id, product_code, artifact_no,
            status, actor, intent, context, normalized_hash, row_count,
            source_bom_kind, flatten_status, flatten_strategy,
            source_channel, bom_variant_id, lineage,
            flatten_method, flatten_method_version,
            published_at, tombstoned_at)
           values (%s, %s, %s, %s, %s, 'agency_staff', %s, %s::jsonb,
                   %s, 0, 'technical_flattened', %s, %s, 'staff_form',
                   %s, '{}', 'as_provided', 'v1',
                   %s, %s)""",
        (aid, client, product, artifact_no, status, intent,
         json.dumps(context or {}),
         f"h_{aid}", flatten_status, flatten_strategy, variant,
         published_iso, "2026-05-01T00:00:00Z" if tombstoned else None),
    )


def _seed_with_rows(cid: str, product: str, *, intent="staff_edit",
                    flatten_status="not_applicable",
                    flatten_strategy="manual_flat_as_provided",
                    context: dict | None = None,
                    material="NVL-1", qty=1.5) -> str:
    """Create a published, active+flat artifact carrying one detail row
    via the real store path (so payload mirrors production exactly)."""
    return bom_store.create_artifact(
        client_id=cid, product_code=product,
        rows=[{
            "material_code": material, "bom_code": product,
            "bom_variant_id": "default", "qty_per_unit": qty, "uom": "PCS",
            "material_name": "PET film", "description": "PET film 50um",
            "hs_code": "3920.62.90", "material_hs_code": "3920.62.90",
            "scrap_rate": 0.02,
        }],
        actor="agency_staff", intent=intent, parent_artifact_id=None,
        context=context or {}, source_upload_id=None,
        flatten_status=flatten_status, flatten_strategy=flatten_strategy,
        bom_code=product, bom_variant_id="default",
    )


def _new_cid() -> str:
    return "batch-" + secrets.token_hex(4)


def _cleanup(cid: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_artifact_rows r using hub.bom_artifacts a "
                    "where r.artifact_id = a.artifact_id and a.client_id = %s", (cid,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ── happy path: two products, rows embedded, filter_applied echoed ──

def test_two_products_rows_embedded(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        _seed_with_rows(cid, "P1")
        _seed_with_rows(cid, "P2")
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1", "P2"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["results"].keys()) == {"P1", "P2"}
        assert body["missing"] == []
        assert body["next_cursor"] is None
        for pc in ("P1", "P2"):
            env = body["results"][pc]
            assert len(env["items"]) == 1
            item = env["items"][0]
            assert item["intent"] == "staff_edit"
            assert item["client_id"] == cid  # rich shape carries client_id
            assert item["product_code"] == pc
            row = item["rows"][0]
            assert row["material_code"] == "NVL-1"
            assert str(row["qty_per_unit"]) in ("1.5", "1.50")
            assert row["uom"] == "PCS"
            assert row["payload"]["material_name"] == "PET film"
            assert row["payload"]["hs_code"] == "3920.62.90"
            assert row["payload"]["material_hs_code"] == "3920.62.90"
            assert "scrap_rate" in row["payload"]
            assert item["unresolved"] == []
            assert item["decisions"] == []
            assert env["filter_applied"] == {
                "lifecycle": "active", "shape": "flat", "depth": "any",
                "intents": None, "latest_per_variant": True,
                "case_id": None, "exclude_non_declarable": False,
            }
    finally:
        _cleanup(cid)


# ── include_rows=false: no rows, and NO per-artifact row fetch ──

def test_include_rows_false_no_fetch(auth_disabled, monkeypatch):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        _seed_with_rows(cid, "P1")

        called = {"rows": 0}
        orig = bom_store.get_rows_for_artifacts

        def _spy(artifact_ids):
            called["rows"] += 1
            return orig(artifact_ids)

        monkeypatch.setattr(bom_store, "get_rows_for_artifacts", _spy)

        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"], "include_rows": False,
        })
        assert r.status_code == 200, r.text
        item = r.json()["results"]["P1"]["items"][0]
        assert "rows" not in item
        assert "unresolved" not in item
        assert "decisions" not in item
        assert called["rows"] == 0
    finally:
        _cleanup(cid)


# ── GOLDEN: same filter -> same artifacts (same set + order) as per-product ──
# Items carry the richer single-artifact shape (see test_artifact_field_parity),
# but the SET and ORDER of artifacts surviving the filter must match the
# per-product LIST endpoint exactly.

def test_same_artifact_set_as_per_product(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
        # active+flat kept; draft dropped by lifecycle; raw_graph dropped by
        # shape; tombstoned dropped; older flat collapsed by latest_per_variant.
        _ins(cur, aid=f"{cid}_a1", client=cid, product="P1", artifact_no=1,
             published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_a2", client=cid, product="P1", artifact_no=2,
             published_iso="2026-05-12T00:00:00Z")
        _ins(cur, aid=f"{cid}_draft", client=cid, product="P1",
             status="draft", artifact_no=3, published_iso=None)
        _ins(cur, aid=f"{cid}_raw", client=cid, product="P1",
             flatten_status="non_flattened", flatten_strategy="no_strategy",
             artifact_no=4, published_iso="2026-05-11T00:00:00Z")
        _ins(cur, aid=f"{cid}_tomb", client=cid, product="P1", tombstoned=True,
             artifact_no=5, published_iso="2026-05-09T00:00:00Z")
    try:
        params = {
            "client_id": cid, "lifecycle": "active", "shape": "flat",
            "latest_per_variant": "true",
        }
        per = _client().get(PER_PRODUCT_URL.format(pc="P1"),
                            params=params, headers=_bearer())
        assert per.status_code == 200, per.text
        per_ids = [it["artifact_id"] for it in per.json()["items"]]

        batch = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"],
            "lifecycle": "active", "shape": "flat",
            "latest_per_variant": True, "include_rows": False,
        })
        assert batch.status_code == 200, batch.text
        batch_ids = [it["artifact_id"]
                     for it in batch.json()["results"]["P1"]["items"]]

        assert batch_ids == per_ids
        assert batch_ids == [f"{cid}_a2"]
    finally:
        _cleanup(cid)


# ── ARTIFACT FIELD PARITY: batch item (minus embeds) == single-artifact GET ──

def test_artifact_field_parity(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        aid = bom_store.create_artifact(
            client_id=cid, product_code="P1",
            rows=[{
                "material_code": "NVL-1", "bom_code": "P1",
                "bom_variant_id": "default", "qty_per_unit": 1.5, "uom": "PCS",
                "material_name": "PET film", "hs_code": "3920.62.90",
            }],
            actor="agency_staff", intent="staff_edit", parent_artifact_id=None,
            context={}, source_upload_id=None,
            flatten_status="not_applicable",
            flatten_strategy="manual_flat_as_provided",
            bom_code="P1", bom_variant_id="default",
            lineage={"origin": "field-parity-test"},
            flatten_method="manual_test", flatten_method_version="9",
        )
        batch = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"],
        })
        assert batch.status_code == 200, batch.text
        item = batch.json()["results"]["P1"]["items"][0]

        single = _client().get(
            f"/v1/hub/products/P1/bom/artifacts/{aid}",
            params={"client_id": cid}, headers=_bearer(),
        )
        assert single.status_code == 200, single.text
        artifact_obj = single.json()["artifact"]

        batch_minus = {k: v for k, v in item.items()
                       if k not in ("rows", "unresolved", "decisions")}
        # Field-for-field identical to the single-artifact `artifact` object.
        assert batch_minus == artifact_obj

        # The 7 fields the list-summary build was missing must be present + equal.
        for f in ("client_id", "flatten_method", "flatten_method_version",
                  "lineage", "uom_drift_resolved_at", "stale_resolved_at",
                  "stale_first_at"):
            assert f in batch_minus, f
            assert batch_minus[f] == artifact_obj[f], f

        # Prove real enrichment (these are NULL/absent in the list summary).
        assert batch_minus["client_id"] == cid
        assert batch_minus["product_code"] == "P1"
        assert batch_minus["flatten_method"] == "manual_test"
        assert batch_minus["flatten_method_version"] == "9"
        assert batch_minus["lineage"] == {"origin": "field-parity-test"}
    finally:
        _cleanup(cid)


# ── row-shape parity vs the single-artifact read (get_artifact_with_rows) ──

def test_row_shape_parity(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        aid = _seed_with_rows(cid, "P1", material="NVL-9", qty=3.25)
        batch = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"],
        })
        assert batch.status_code == 200, batch.text
        batch_rows = batch.json()["results"]["P1"]["items"][0]["rows"]

        single = _client().get(PINNED_URL.format(pc="P1"),
                               params={"client_id": cid, "artifact_id": aid},
                               headers=_bearer())
        assert single.status_code == 200, single.text
        assert batch_rows == single.json()["rows"]
    finally:
        _cleanup(cid)


# ── dual-source: both legs as separate items, never 409 ──

def test_dual_source_both_legs_no_409(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        _seed_with_rows(cid, "P1", flatten_status="flattened",
                        flatten_strategy="technical_exploded", material="A")
        _seed_with_rows(cid, "P1", flatten_status="flattened",
                        flatten_strategy="purchased_btp_as_leaf", material="B")
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"],
            "latest_per_variant": True,
        })
        assert r.status_code == 200, r.text
        items = r.json()["results"]["P1"]["items"]
        strategies = {it["flatten_strategy"] for it in items}
        assert strategies == {"technical_exploded", "purchased_btp_as_leaf"}
        assert len(items) == 2
    finally:
        _cleanup(cid)


# ── modified_for_case: case-scoped drafts only; other intents unfiltered ──

def test_modified_for_case_scoping(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        _seed_with_rows(cid, "P1", intent="staff_edit", material="S")
        _seed_with_rows(cid, "P1", intent="modified_for_case",
                        context={"case_id": "co-1"}, material="C1")
        _seed_with_rows(cid, "P1", intent="modified_for_case",
                        context={"case_id": "co-2"}, material="C2")
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"],
            "intents": ["staff_edit", "modified_for_case"],
            "case_id": "co-1", "latest_per_variant": False,
        })
        assert r.status_code == 200, r.text
        items = r.json()["results"]["P1"]["items"]
        intents = sorted(it["intent"] for it in items)
        # staff_edit kept; only the co-1 modified_for_case kept; co-2 dropped.
        assert intents == ["modified_for_case", "staff_edit"]
        mfc = [it for it in items if it["intent"] == "modified_for_case"]
        assert mfc[0]["context"]["case_id"] == "co-1"
    finally:
        _cleanup(cid)


def test_modified_for_case_requires_case_id(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1"],
            "intents": ["modified_for_case"],
        })
        assert r.status_code == 400
        assert r.json()["detail"] == "case_id_required"
    finally:
        _cleanup(cid)


# ── zero-artifact product -> missing, not 404 ──

def test_zero_artifact_product_in_missing(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        _seed_with_rows(cid, "P1")
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1", "PZ"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "P1" in body["results"]
        assert "PZ" not in body["results"]
        assert body["missing"] == ["PZ"]
    finally:
        _cleanup(cid)


# ── pagination: next_cursor, no product split, pages concat == full set ──

def test_pagination_no_split_concat(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
        # 3 products, 2 active+flat artifacts each (distinct variants so
        # latest_per_variant keeps both). lifecycle active, shape flat.
        for p in ("P1", "P2", "P3"):
            _ins(cur, aid=f"{cid}_{p}_v1", client=cid, product=p,
                 variant="default", artifact_no=1,
                 published_iso="2026-05-10T00:00:00Z")
            _ins(cur, aid=f"{cid}_{p}_v2", client=cid, product=p,
                 variant="alt", artifact_no=1,
                 published_iso="2026-05-11T00:00:00Z")
    try:
        base = {
            "client_id": cid, "product_codes": ["P1", "P2", "P3"],
            "lifecycle": "active", "shape": "flat",
            "latest_per_variant": True, "include_rows": False,
        }
        full = _client().post(BATCH_URL, headers=_bearer(),
                              json={**base, "limit": 999}).json()
        assert set(full["results"]) == {"P1", "P2", "P3"}
        assert all(len(full["results"][p]["items"]) == 2 for p in full["results"])

        # limit=3 forces page boundaries at product edges (2 items each ->
        # one product per page, never split).
        merged: dict[str, list] = {}
        cursor = None
        pages = 0
        while True:
            page = _client().post(BATCH_URL, headers=_bearer(),
                                  json={**base, "limit": 3, "cursor": cursor}).json()
            pages += 1
            for pc, env in page["results"].items():
                assert pc not in merged, "product split across pages"
                merged[pc] = env["items"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
            assert pages < 10
        assert merged.keys() == full["results"].keys()
        for pc in merged:
            assert merged[pc] == full["results"][pc]["items"]
    finally:
        _cleanup(cid)


# ── dedupe duplicate product_codes ──

def test_dedupe_product_codes(auth_disabled):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        _seed_with_rows(cid, "P1")
        _seed_with_rows(cid, "P2")
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": ["P1", "P1", "P2", "P1"],
        })
        assert r.status_code == 200, r.text
        assert set(r.json()["results"]) == {"P1", "P2"}
    finally:
        _cleanup(cid)


# ── negative validation ──

@pytest.mark.parametrize("payload,code", [
    ({"product_codes": ["P1"]}, "missing_client_id"),
    ({"client_id": "c", "product_codes": []}, "empty_product_codes"),
    ({"client_id": "c", "product_codes": [f"P{i}" for i in range(501)]},
     "too_many_product_codes"),
    ({"client_id": "c", "product_codes": ["P1"], "lifecycle": "bogus"},
     "invalid_lifecycle"),
    ({"client_id": "c", "product_codes": ["P1"], "shape": "bogus"},
     "invalid_shape"),
    ({"client_id": "c", "product_codes": ["P1"], "intents": ["nope"]},
     "invalid_intents"),
])
def test_negative_validation(auth_disabled, payload, code):
    r = _client().post(BATCH_URL, headers=_bearer(), json=payload)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == code


# ── auth: scope + client scoping (real service tokens, auth NOT disabled) ──

def test_service_token_without_hub_read_403(monkeypatch):
    monkeypatch.delenv("DATA_HUB_API_AUTH_DISABLED", raising=False)
    from app import jwt_issuer
    from app.stores import service_accounts as sa_store
    name = "sa_batch_noscope_" + secrets.token_hex(3)
    sa_store.create_account(name=name, description="",
                            scopes=["hub:write"], client_ids=None,
                            created_by="test")
    out = jwt_issuer.make_service_token(name=name, scopes=["hub:write"],
                                        client_ids=None)
    r = _client().post(BATCH_URL,
                       headers={"authorization": f"Bearer {out['access_token']}"},
                       json={"client_id": "any", "product_codes": ["P1"]})
    assert r.status_code == 403, r.text


def test_service_token_client_outside_scope_403(monkeypatch):
    monkeypatch.delenv("DATA_HUB_API_AUTH_DISABLED", raising=False)
    from app import jwt_issuer
    from app.stores import service_accounts as sa_store
    name = "sa_batch_otherclient_" + secrets.token_hex(3)
    sa_store.create_account(name=name, description="",
                            scopes=["hub:read"], client_ids=["other-client"],
                            created_by="test")
    out = jwt_issuer.make_service_token(name=name, scopes=["hub:read"],
                                        client_ids=["other-client"])
    r = _client().post(BATCH_URL,
                       headers={"authorization": f"Bearer {out['access_token']}"},
                       json={"client_id": "not-other", "product_codes": ["P1"]})
    assert r.status_code == 403, r.text


# ── fan-in: ONE artifact query class regardless of product count ──

def test_fan_in_single_query_class(auth_disabled, monkeypatch):
    cid = _new_cid()
    with connect() as conn, conn.cursor() as cur:
        _mk_client(cur, cid)
    try:
        codes = [f"P{i}" for i in range(20)]
        for c in codes:
            _seed_with_rows(cid, c)

        calls = {"artifacts": 0, "rows": 0, "unresolved": 0, "decisions": 0}
        for attr, key in (
            ("list_artifact_meta_for_products", "artifacts"),
            ("get_rows_for_artifacts", "rows"),
            ("get_unresolved_for_artifacts", "unresolved"),
            ("get_decisions_for_artifacts", "decisions"),
        ):
            orig = getattr(bom_store, attr)

            def _wrap(*a, _orig=orig, _key=key, **kw):
                calls[_key] += 1
                return _orig(*a, **kw)

            monkeypatch.setattr(bom_store, attr, _wrap)

        # request 500 codes (only 20 seeded; rest land in missing) to prove
        # cost is independent of product count.
        big = codes + [f"X{i}" for i in range(480)]
        r = _client().post(BATCH_URL, headers=_bearer(), json={
            "client_id": cid, "product_codes": big, "limit": 999,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["results"]) == 20
        assert len(body["missing"]) == 480
        # The whole batch is ONE artifact query + ONE of each row-bundle
        # query — not a per-product loop.
        assert calls == {"artifacts": 1, "rows": 1,
                         "unresolved": 1, "decisions": 1}
    finally:
        _cleanup(cid)
