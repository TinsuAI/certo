"""Phase 3 G — refresh-time UoM conversion preview.

`plan_refresh(client_id, artifact_id)` is the pure planner that
re-walks SQL (or reconstructs manual_flat originals), converts to
catalog UoM, but DOES NOT persist. Returns a RefreshPlan with per-row
plan + drift summary + would_be_hash + has_blocking. Used by the
GET preview route to render the conversion plan before staff confirms.

Spec: `.ai/features/2026-05-13-bom-refresh-preview/brief.md` decision 3.
"""
from __future__ import annotations

import json

import pytest

from hub.app.database import connect


CLIENT = "_plan_refresh_test"


def _seed_client(cur):
    cur.execute(
        "insert into hub.clients (client_id, name) values (%s, %s) "
        "on conflict (client_id) do nothing",
        (CLIENT, "plan-refresh test"),
    )


def _seed_material(cur, code: str, *, category: str = "nvl",
                    uom: str | None = "kg"):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, %s, 'active', %s) "
        "on conflict (client_id, material_code) do update set "
        "category=excluded.category, uom=excluded.uom",
        (CLIENT, code, code, category, uom),
    )


def _insert_raw_artifact(cur, artifact_id: str, product_code: str,
                          edges: list[tuple[str, str, float, str]]) -> None:
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'asserted_technical', '{}', %s, %s, 'technical_raw', "
        "'non_flattened', 'no_strategy', 'agency_upload', "
        "'default', '{}', 'as_provided', 'v1', now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}", len(edges)),
    )
    for idx, (parent, child, qty, uom) in enumerate(edges):
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (artifact_id, idx, product_code, parent, child, qty, uom),
        )


def _insert_derived_stale(cur, artifact_id: str, product_code: str,
                            strategy: str = "technical_exploded") -> None:
    reasons = [{"dim": "catalog_category", "source_table": "hub.materials",
                "source_pk": f"{CLIENT}/seed", "observed_at":
                "2026-05-12T00:00:00Z"}]
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at, is_stale, "
        "stale_reasons, stale_first_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'derived', '{}', %s, 0, 'technical_flattened', "
        "'flattened', %s, 'migration', 'default', '{}', 'recursive_sql', "
        "'1', now(), true, %s::jsonb, now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}", strategy,
         json.dumps(reasons)),
    )


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        _seed_client(cur)
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute(
            "delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_uom_overrides where client_id=%s",
            (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


# ── plan_refresh contract ────────────────────────────────────────────


def test_plan_refresh_tier_b_blocking():
    """Tier-B (count → mass, no override): plan flags row blocking,
    has_blocking=True, no DB writes performed."""
    from hub.app.stores.bom_staleness import plan_refresh

    raw_id = "ba_plan_raw_b"
    derived_id = "ba_plan_der_b"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_PB", category="tp", uom="KG")
        _seed_material(cur, "M_PB", category="nvl", uom="KG")
        _insert_raw_artifact(cur, raw_id, "TP_PB",
                              edges=[("TP_PB", "M_PB", 7.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_PB",
                                strategy="technical_exploded")
        cur.execute("select count(*) from hub.bom_artifacts "
                    "where client_id=%s", (CLIENT,))
        artifacts_before = cur.fetchone()[0]

    plan = plan_refresh(CLIENT, derived_id)

    assert plan["artifact_id"] == derived_id
    assert plan["flatten_strategy"] == "technical_exploded"
    assert plan["has_blocking"] is True
    assert plan["skipped_reason"] is None
    rows = plan["rows"]
    assert len(rows) == 1
    r = rows[0]
    assert r["material_code"] == "M_PB"
    assert r["source_uom"] == "EA"
    assert r["target_uom"] == "KG"
    assert r["status"] == "blocked_no_factor", (
        f"Tier-B without override must be blocked; got status={r['status']}"
    )
    assert r["factor"] is None
    assert plan["would_be_hash"] is not None

    # Pure planner: artifact count must be unchanged.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.bom_artifacts "
                    "where client_id=%s", (CLIENT,))
        artifacts_after = cur.fetchone()[0]
    assert artifacts_after == artifacts_before, (
        "plan_refresh must not write any new artifacts"
    )


def test_plan_refresh_tier_a_unconfirmed_default():
    """Tier-A (count → assembly): factor 1.0 default, status unconfirmed_default."""
    from hub.app.stores.bom_staleness import plan_refresh

    raw_id = "ba_plan_raw_a"
    derived_id = "ba_plan_der_a"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_PA", category="tp", uom="SETS")
        _seed_material(cur, "M_PA", category="nvl", uom="SETS")
        _insert_raw_artifact(cur, raw_id, "TP_PA",
                              edges=[("TP_PA", "M_PA", 4.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_PA",
                                strategy="technical_exploded")

    plan = plan_refresh(CLIENT, derived_id)

    assert plan["has_blocking"] is False, "Tier A is warning, not blocking"
    r = plan["rows"][0]
    assert r["status"] == "unconfirmed_default"
    assert float(r["factor"]) == pytest.approx(1.0)
    assert r["factor_source"] == "unconfirmed_default"
    assert r["target_uom"] == "SETS"


def test_plan_refresh_same_family_ready():
    """Same-family (g → kg): silent convert, status ready, no blocking."""
    from hub.app.stores.bom_staleness import plan_refresh

    raw_id = "ba_plan_raw_sf"
    derived_id = "ba_plan_der_sf"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_PSF", category="tp", uom="kg")
        _seed_material(cur, "M_PSF", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP_PSF",
                              edges=[("TP_PSF", "M_PSF", 2500.0, "g")])
        _insert_derived_stale(cur, derived_id, "TP_PSF",
                                strategy="technical_exploded")

    plan = plan_refresh(CLIENT, derived_id)

    assert plan["has_blocking"] is False
    r = plan["rows"][0]
    assert r["status"] == "ready"
    assert r["target_uom"] == "kg"
    assert float(r["factor"]) == pytest.approx(0.001)


def test_plan_refresh_unknown_artifact_raises():
    from hub.app.stores.bom_staleness import plan_refresh
    with pytest.raises(LookupError):
        plan_refresh(CLIENT, "ba_does_not_exist")


def test_plan_refresh_cross_tenant_raises():
    from hub.app.stores.bom_staleness import plan_refresh
    raw_id = "ba_plan_raw_tenant"
    derived_id = "ba_plan_der_tenant"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_T", category="tp", uom="kg")
        _seed_material(cur, "M_T", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP_T",
                              edges=[("TP_T", "M_T", 1.0, "kg")])
        _insert_derived_stale(cur, derived_id, "TP_T",
                                strategy="technical_exploded")

    with pytest.raises(LookupError):
        plan_refresh("a_different_client_id", derived_id)


def test_plan_refresh_skipped_when_no_raw_ancestor():
    """Derived artifact with no raw ancestor → skipped, no rows."""
    from hub.app.stores.bom_staleness import plan_refresh
    derived_id = "ba_plan_der_orphan"
    with connect() as conn, conn.cursor() as cur:
        _insert_derived_stale(cur, derived_id, "TP_NO_RAW",
                                strategy="technical_exploded")

    plan = plan_refresh(CLIENT, derived_id)
    assert plan["skipped_reason"] == "no_raw_ancestor"
    assert plan["rows"] == []
    assert plan["would_be_hash"] is None


# ── commit_refresh contract ──────────────────────────────────────────


def test_commit_refresh_skip_no_state_change_audit_row():
    """skip=True writes bom_audit_events row, leaves artifact untouched."""
    from hub.app.stores.bom_staleness import commit_refresh

    raw_id = "ba_commit_skip_raw"
    derived_id = "ba_commit_skip_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_SK", category="tp", uom="KG")
        _seed_material(cur, "M_SK", category="nvl", uom="KG")
        _insert_raw_artifact(cur, raw_id, "TP_SK",
                              edges=[("TP_SK", "M_SK", 7.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_SK",
                                strategy="technical_exploded")
        cur.execute("select count(*) from hub.bom_audit_events "
                    "where client_id=%s and event_type='refresh.skipped'",
                    (CLIENT,))
        skip_audit_before = cur.fetchone()[0]

    result = commit_refresh(
        CLIENT, derived_id, skip=True, triggered_by_user_id="staff_a",
    )

    assert result["new_artifact_ids"] == [], "skip must not mint artifacts"
    assert result["skipped_reason"] == "staff_skip"

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select is_stale from hub.bom_artifacts where artifact_id=%s",
                    (derived_id,))
        assert cur.fetchone()[0] is True, "skip must not clear is_stale"
        cur.execute("select count(*) from hub.bom_audit_events "
                    "where client_id=%s and event_type='refresh.skipped'",
                    (CLIENT,))
        skip_audit_after = cur.fetchone()[0]
        assert skip_audit_after == skip_audit_before + 1
        cur.execute(
            "select actor, artifact_id, details from hub.bom_audit_events "
            "where client_id=%s and event_type='refresh.skipped' "
            "order by occurred_at desc limit 1",
            (CLIENT,))
        actor, aid, details = cur.fetchone()
        assert aid == derived_id
        assert actor == "staff_a"
        assert "blocking_count" in details, (
            "audit details must include plan summary"
        )


def test_commit_refresh_edits_persist_factor_then_refreshes():
    """edits=[{material_code, from_uom, to_uom, factor, source}] writes
    client_uom_overrides BEFORE refresh, so the previously-blocking row
    becomes ready and the new artifact mints successfully."""
    from hub.app.stores.bom_staleness import commit_refresh

    raw_id = "ba_commit_edit_raw"
    derived_id = "ba_commit_edit_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_ED", category="tp", uom="KG")
        _seed_material(cur, "M_ED", category="nvl", uom="KG")
        _insert_raw_artifact(cur, raw_id, "TP_ED",
                              edges=[("TP_ED", "M_ED", 1000.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_ED",
                                strategy="technical_exploded")

    result = commit_refresh(
        CLIENT, derived_id,
        edits=[{
            "material_code": "M_ED", "from_uom": "EA", "to_uom": "KG",
            "factor": 0.5, "source": "staff_form",
        }],
        triggered_by_user_id="staff_b",
    )

    assert result["new_artifact_ids"], "edit must enable refresh to succeed"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select factor from hub.client_uom_overrides "
            "where client_id=%s and material_code=%s "
            "  and from_uom=%s and to_uom=%s",
            (CLIENT, "M_ED", "EA", "KG"))
        row = cur.fetchone()
        assert row is not None, "factor row must persist to client_uom_overrides"
        assert float(row[0]) == pytest.approx(0.5)

        new_id = result["new_artifact_ids"][0]
        cur.execute(
            "select qty_per_unit, uom from hub.bom_artifact_rows "
            "where artifact_id=%s", (new_id,))
        qty, uom = cur.fetchone()
        assert uom == "KG"
        assert float(qty) == pytest.approx(500.0)  # 1000 * 0.5


def test_refresh_artifact_delegates_to_commit_refresh():
    """Existing public API stays — same fixture produces same outcome."""
    from hub.app.stores.bom_staleness import refresh_artifact, commit_refresh
    raw_id = "ba_delegate_raw"
    derived_id = "ba_delegate_der"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_DL", category="tp", uom="kg")
        _seed_material(cur, "M_DL", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP_DL",
                              edges=[("TP_DL", "M_DL", 2500.0, "g")])
        _insert_derived_stale(cur, derived_id, "TP_DL",
                                strategy="technical_exploded")

    r1 = refresh_artifact(CLIENT, derived_id)
    # Cleanup the new artifact and re-seed for the second call so we
    # exercise both paths against equivalent state.
    new_id = r1["new_artifact_ids"][0] if r1["new_artifact_ids"] else None
    with connect() as conn, conn.cursor() as cur:
        if new_id:
            cur.execute("delete from hub.bom_artifact_rows where artifact_id=%s",
                        (new_id,))
            cur.execute("delete from hub.bom_artifacts where artifact_id=%s",
                        (new_id,))
        cur.execute(
            "update hub.bom_artifacts set is_stale=true, "
            "stale_reasons='[{\"dim\":\"catalog_category\"}]'::jsonb, "
            "tombstoned_at=null, tombstone_reason=null "
            "where artifact_id=%s",
            (derived_id,))

    r2 = commit_refresh(CLIENT, derived_id)
    assert sorted(r1.keys()) == sorted(r2.keys())
    assert r1["cleared"] == r2["cleared"]
    # Both should have minted (or both skipped). Hashes must match since
    # raw + catalog state is identical.
    assert bool(r1["new_artifact_ids"]) == bool(r2["new_artifact_ids"])


def test_plan_refresh_same_hash_on_already_converted():
    """If commit_refresh would produce the same hash as the existing
    artifact, would_be_hash equals artifact.normalized_hash → caller
    can detect no-op without writing."""
    from hub.app.stores.bom_staleness import plan_refresh
    from hub.app.stores.bom import create_artifact, normalized_hash

    raw_id = "ba_plan_raw_nh"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_NH", category="tp", uom="kg")
        _seed_material(cur, "M_NH", category="nvl", uom="kg")
        _insert_raw_artifact(cur, raw_id, "TP_NH",
                              edges=[("TP_NH", "M_NH", 2.0, "kg")])

    # Mint a derived artifact via the production path so its rows match
    # what convert + create_artifact would produce now.
    converted_rows = [{
        "material_code": "M_NH", "qty_per_unit": 2.0, "uom": "kg",
        "source_uom": "kg", "applied_uom_factor": 1.0,
        "applied_uom_source": "alias",
    }]
    derived_id = create_artifact(
        client_id=CLIENT, product_code="TP_NH", rows=converted_rows,
        actor="agency_staff", intent="derived",
        parent_artifact_id=raw_id, context={"channel": "test"},
        source_upload_id=None, source_bom_kind="technical_flattened",
        flatten_status="flattened", flatten_strategy="technical_exploded",
        source_channel="migration", flatten_method="recursive_sql_with_uom_conversion",
        flatten_method_version="2",
    )
    # Force is_stale so plan_refresh doesn't reject for any other reason.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.bom_artifacts set is_stale=true, "
            "stale_reasons='[]'::jsonb where artifact_id=%s",
            (derived_id,))
        cur.execute(
            "select normalized_hash from hub.bom_artifacts where artifact_id=%s",
            (derived_id,))
        existing_hash = cur.fetchone()[0]

    plan = plan_refresh(CLIENT, derived_id)
    assert plan["would_be_hash"] == existing_hash, (
        "would_be_hash must equal existing artifact's hash for no-op detection"
    )
