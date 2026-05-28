"""Provider tests for `/v1/hub/products/{p}/bom/artifacts` picker filters.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-28-bom-artifacts-active-flat-filter.md`.

Defaults preserve back-compat (lifecycle=all, shape=any,
latest_per_variant=false). CO picker passes explicit filters; admin /
debug tools that need raw history don't pass anything.
"""
from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def _bearer(headers: dict | None = None) -> dict:
    h = dict(headers or {})
    h["authorization"] = "Bearer smoke"
    return h


def _ins(cur, *, aid, client, product, intent="staff_edit",
         status="published", tombstoned=False,
         flatten_status="flattened",
         flatten_strategy="technical_exploded",
         variant="default", artifact_no=1, published_iso=None,
         context: dict | None = None) -> None:
    """Insert one bom_artifacts row with sensible test defaults."""
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


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(auth_disabled):
    """Throwaway client + a few artifacts covering all filter dimensions:

    Product PA (lifecycle/shape mix):
      v1 published  flattened    → eligible everything
      v2 draft      flattened    → drops on lifecycle=active
      v3 published  flattened    tombstoned → drops on lifecycle=active
      v4 published  non_flattened → drops on shape=flat

    Product PB (intent mix):
      v1 staff_edit         flattened
      v2 derived            flattened
      v3 modified_for_case (case_id='A')
      v4 modified_for_case (case_id='B')
      v5 modified_for_case (no context.case_id)

    Product PC (latest_per_variant: same partition, 3 versions):
      v5 published @ t0
      v6 published @ t1
      v7 published @ t2   (winner)
      all default variant + technical_exploded.

    Product PD (dual-source: two partitions, both alive):
      v1 default / technical_exploded
      v2 default / purchased_btp_as_leaf
    """
    cid = "bom-picker-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, %s, 'simple_mapping', 'auto')",
            (cid, "picker-test"),
        )
        # Product PA
        _ins(cur, aid=f"{cid}_PA_v1", client=cid, product="PA",
             artifact_no=1, published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_PA_v2", client=cid, product="PA",
             artifact_no=2, status="draft", published_iso=None)
        _ins(cur, aid=f"{cid}_PA_v3", client=cid, product="PA",
             artifact_no=3, tombstoned=True,
             published_iso="2026-05-11T00:00:00Z")
        _ins(cur, aid=f"{cid}_PA_v4", client=cid, product="PA",
             artifact_no=4, flatten_status="non_flattened",
             flatten_strategy="no_strategy",
             published_iso="2026-05-12T00:00:00Z")
        # Product PB — distinct strategy per intent so latest_per_variant
        # does not collapse them when we test single-intent filtering.
        _ins(cur, aid=f"{cid}_PB_v1", client=cid, product="PB",
             artifact_no=1, intent="staff_edit",
             flatten_strategy="technical_exploded",
             published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_PB_v2", client=cid, product="PB",
             artifact_no=2, intent="derived",
             flatten_strategy="purchased_btp_as_leaf",
             published_iso="2026-05-11T00:00:00Z")
        _ins(cur, aid=f"{cid}_PB_v3", client=cid, product="PB",
             artifact_no=3, intent="modified_for_case",
             flatten_strategy="manual_flat_as_provided",
             context={"case_id": "A"},
             published_iso="2026-05-12T00:00:00Z")
        _ins(cur, aid=f"{cid}_PB_v4", client=cid, product="PB",
             artifact_no=4, intent="modified_for_case",
             flatten_strategy="manual_flat_as_provided",
             context={"case_id": "B"},
             published_iso="2026-05-13T00:00:00Z")
        _ins(cur, aid=f"{cid}_PB_v5", client=cid, product="PB",
             artifact_no=5, intent="modified_for_case",
             flatten_strategy="manual_flat_as_provided",
             context={},
             published_iso="2026-05-14T00:00:00Z")
        # Product PC — same partition × 3 versions
        for n, ts in [(5, "2026-05-10T00:00:00Z"),
                      (6, "2026-05-11T00:00:00Z"),
                      (7, "2026-05-12T00:00:00Z")]:
            _ins(cur, aid=f"{cid}_PC_v{n}", client=cid, product="PC",
                 artifact_no=n, published_iso=ts)
        # Product PD — dual-source variants (one variant, two strategies)
        _ins(cur, aid=f"{cid}_PD_v1", client=cid, product="PD",
             artifact_no=1, flatten_strategy="technical_exploded",
             published_iso="2026-05-10T00:00:00Z")
        _ins(cur, aid=f"{cid}_PD_v2", client=cid, product="PD",
             artifact_no=2, flatten_strategy="purchased_btp_as_leaf",
             published_iso="2026-05-11T00:00:00Z")
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _url(product: str) -> str:
    return f"/v1/hub/products/{product}/bom/artifacts"


# ─── Default back-compat ─────────────────────────────────────────────


def test_default_params_keep_raw_history_and_echo_filters(seeded):
    r = _client().get(_url("PA"), params={"client_id": seeded},
                       headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    # Back-compat: no filters applied → all 4 PA versions present.
    assert len(body["items"]) == 4
    assert body["filter_applied"] == {
        "lifecycle": "all", "shape": "any",
        "intents": None, "latest_per_variant": False,
        "case_id": None,
    }


# ─── Lifecycle / shape ───────────────────────────────────────────────


def test_lifecycle_active_drops_draft_and_tombstoned(seeded):
    r = _client().get(_url("PA"), params={
        "client_id": seeded, "lifecycle": "active",
    }, headers=_bearer())
    assert r.status_code == 200
    aids = {it["artifact_id"] for it in r.json()["items"]}
    # v1 (eligible) + v4 (eligible — non_flattened but lifecycle=active passes).
    assert aids == {f"{seeded}_PA_v1", f"{seeded}_PA_v4"}


def test_shape_flat_drops_non_flattened(seeded):
    r = _client().get(_url("PA"), params={
        "client_id": seeded, "shape": "flat",
    }, headers=_bearer())
    assert r.status_code == 200
    aids = {it["artifact_id"] for it in r.json()["items"]}
    # v4 is non_flattened → drops. v1, v2 (draft), v3 (tombstoned) still in.
    assert f"{seeded}_PA_v4" not in aids
    assert {f"{seeded}_PA_v1", f"{seeded}_PA_v2", f"{seeded}_PA_v3"} <= aids


# ─── Intents ─────────────────────────────────────────────────────────


def test_intents_filter_single_value(seeded):
    r = _client().get(_url("PB"), params={
        "client_id": seeded, "intents": "staff_edit",
    }, headers=_bearer())
    assert r.status_code == 200
    aids = {it["artifact_id"] for it in r.json()["items"]}
    assert aids == {f"{seeded}_PB_v1"}


def test_intents_modified_for_case_requires_case_id(seeded):
    r = _client().get(_url("PB"), params={
        "client_id": seeded, "intents": "modified_for_case",
    }, headers=_bearer())
    assert r.status_code == 400
    assert r.json()["detail"] == "case_id_required"


def test_intents_modified_for_case_scoped_by_case_id(seeded):
    r = _client().get(_url("PB"), params={
        "client_id": seeded,
        "intents": "staff_edit,derived,modified_for_case",
        "case_id": "A",
    }, headers=_bearer())
    assert r.status_code == 200
    aids = {it["artifact_id"] for it in r.json()["items"]}
    # Keep: staff_edit (v1), derived (v2), modified_for_case with case_id=A (v3).
    # Drop: modified_for_case with case_id=B (v4) and missing case_id (v5).
    assert aids == {f"{seeded}_PB_v1", f"{seeded}_PB_v2", f"{seeded}_PB_v3"}


def test_conflicting_intent_params_400(seeded):
    r = _client().get(_url("PB"), params={
        "client_id": seeded,
        "intent": "staff_edit", "intents": "derived",
    }, headers=_bearer())
    assert r.status_code == 400
    assert r.json()["detail"] == "conflicting_intent_params"


# ─── latest_per_variant ──────────────────────────────────────────────


def test_latest_per_variant_keeps_newest(seeded):
    r = _client().get(_url("PC"), params={
        "client_id": seeded, "latest_per_variant": "true",
    }, headers=_bearer())
    assert r.status_code == 200
    aids = [it["artifact_id"] for it in r.json()["items"]]
    assert aids == [f"{seeded}_PC_v7"]


def test_latest_per_variant_dual_source_returns_both(seeded):
    r = _client().get(_url("PD"), params={
        "client_id": seeded, "latest_per_variant": "true",
    }, headers=_bearer())
    assert r.status_code == 200
    aids = {it["artifact_id"] for it in r.json()["items"]}
    # Different flatten_strategy = different partition → both kept.
    assert aids == {f"{seeded}_PD_v1", f"{seeded}_PD_v2"}


# ─── Picker combination ─────────────────────────────────────────────


def test_picker_full_combination(seeded):
    """The exact call the CO picker makes per request spec."""
    r = _client().get(_url("PA"), params={
        "client_id": seeded, "lifecycle": "active", "shape": "flat",
        "latest_per_variant": "true",
        "intents": "asserted_technical,staff_edit,derived,customs_declared",
    }, headers=_bearer())
    assert r.status_code == 200
    body = r.json()
    aids = {it["artifact_id"] for it in body["items"]}
    # v1 is the only PA row that survives lifecycle=active + shape=flat +
    # intent=staff_edit.
    assert aids == {f"{seeded}_PA_v1"}
    fa = body["filter_applied"]
    assert fa["lifecycle"] == "active"
    assert fa["shape"] == "flat"
    assert fa["latest_per_variant"] is True
    assert set(fa["intents"]) == {
        "asserted_technical", "staff_edit", "derived", "customs_declared",
    }


# ─── Error cases ─────────────────────────────────────────────────────


def test_invalid_lifecycle_returns_400(seeded):
    r = _client().get(_url("PA"), params={
        "client_id": seeded, "lifecycle": "weird",
    }, headers=_bearer())
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_lifecycle"


def test_invalid_shape_returns_400(seeded):
    r = _client().get(_url("PA"), params={
        "client_id": seeded, "shape": "twisted",
    }, headers=_bearer())
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_shape"


def test_invalid_intents_returns_400(seeded):
    r = _client().get(_url("PA"), params={
        "client_id": seeded, "intents": "staff_edit,bogus_intent",
    }, headers=_bearer())
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_intents"
