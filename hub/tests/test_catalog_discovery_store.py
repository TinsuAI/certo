"""Decision store for the discovery feed (#34): accept → materials,
reject → suppression, unreject → lift only. Replaces the old
accept_candidate state-machine tests.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.app.stores.catalog_discovery import (
    AlreadyInCatalog,
    accept_code,
    reject_code,
    unreject_code,
)


CLIENT = "_test_disc_store"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'ds test') "
            "on conflict do nothing",
            (CLIENT,),
        )
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.bom_audit_events "
            "where client_id=%s and event_type='catalog_candidate_decision'",
            (CLIENT,),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.bom_audit_events "
            "where client_id=%s and event_type='catalog_candidate_decision'",
            (CLIENT,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_link(txn, customs, nb):
    """A BCCT row + its persisted paren link (the automap substrate)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
            " declaration_no, customs_code, goods_name, registration_date, "
            " payload) "
            "values (%s, %s, '1', %s, %s, %s, '2026-04-01', '{}'::jsonb)",
            (CLIENT, txn, txn, customs, f"{customs} ({nb})"),
        )
        cur.execute(
            "insert into hub.bcct_nb_codes (client_id, transaction_key, "
            " line_no, nb_code) values (%s, %s, '1', %s) "
            "on conflict do nothing",
            (CLIENT, txn, nb),
        )


def _material(code):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select source, code_kind, status from hub.materials "
            "where client_id=%s and material_code=%s",
            (CLIENT, code),
        )
        return cur.fetchone()


def _mappings():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select internal_code, customs_code from hub.code_mappings "
            "where client_id=%s order by 1, 2",
            (CLIENT,),
        )
        return cur.fetchall()


def _audit_actions():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select details->>'action', details->>'code' "
            "from hub.bom_audit_events "
            "where client_id=%s and event_type='catalog_candidate_decision' "
            "order by event_id",
            (CLIENT,),
        )
        return cur.fetchall()


def test_accept_inserts_material_with_stream_source():
    accept_code(CLIENT, code="019.X", code_kind="nb", actor="t@x",
                name="linh kiện", category="nvl",
                sources=["bom"])
    assert _material("019.X") == ("bom_observed", "nb", "active")
    assert ("accept", "019.X") in _audit_actions()


def test_accept_defaults_to_active():
    """#49: accepting a candidate lands it active. The old default was
    under_review, which inverted the trust ordering — BCCT ingest
    auto-inserts active with no review at all."""
    accept_code(CLIENT, code="019.ACT", code_kind="nb", actor="t@x",
                name="x", category="nvl", sources=["bcct"])
    assert _material("019.ACT")[2] == "active"


def test_accept_source_priority_bcct_over_bom():
    accept_code(CLIENT, code="019.Y", code_kind="nb", actor="t@x",
                name="x", category="nvl", sources=["bcct", "bom"])
    assert _material("019.Y")[0] == "bcct_observed"


def test_accept_bqd_only_is_client_declared():
    accept_code(CLIENT, code="019.Z", code_kind="nb", actor="t@x",
                name="x", category="nvl", sources=["bqd"])
    assert _material("019.Z")[0] == "client_declared"


def test_accept_existing_material_raises():
    accept_code(CLIENT, code="DUP", code_kind="unified", actor="t@x",
                name="x", category="nvl", sources=["bcct"])
    with pytest.raises(AlreadyInCatalog):
        accept_code(CLIENT, code="DUP", code_kind="unified", actor="t@x",
                    name="y", category="tp", sources=["bcct"])
    # The first accept's data is untouched (no clobber — old bug C.9).
    assert _material("DUP") == ("bcct_observed", "unified", "active")


def test_accept_hq_automaps_to_existing_nb_materials():
    _seed_link("TX1", "BUCKET", "019.A")
    _seed_link("TX2", "BUCKET", "019.B")
    # Only 019.A is a material yet.
    accept_code(CLIENT, code="019.A", code_kind="nb", actor="t@x",
                name="a", category="nvl", sources=["bcct"])
    accept_code(CLIENT, code="BUCKET", code_kind="hq", actor="t@x",
                name="bucket", category="nvl", sources=["bcct"])
    assert ("019.A", "BUCKET") in _mappings()
    assert ("019.B", "BUCKET") not in _mappings()  # not a material yet


def test_accept_nb_automaps_to_existing_hq_material():
    _seed_link("TX1", "BUCKET", "019.A")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source, code_kind) "
            "values (%s, 'BUCKET', 'bucket', 'nvl', 'active', "
            " 'bcct_observed', 'hq')",
            (CLIENT,),
        )
    accept_code(CLIENT, code="019.A", code_kind="nb", actor="t@x",
                name="a", category="nvl", sources=["bcct"])
    assert ("019.A", "BUCKET") in _mappings()


def test_accept_automap_idempotent():
    _seed_link("TX1", "BUCKET", "019.A")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.code_mappings (client_id, internal_code, "
            " customs_code) values (%s, '019.A', 'BUCKET')",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source, code_kind) "
            "values (%s, 'BUCKET', 'b', 'nvl', 'active', 'bcct_observed', 'hq')",
            (CLIENT,),
        )
    accept_code(CLIENT, code="019.A", code_kind="nb", actor="t@x",
                name="a", category="nvl", sources=["bcct"])
    assert _mappings() == [("019.A", "BUCKET")]


def test_accept_lifts_prior_rejection():
    reject_code(CLIENT, code="RETHINK", code_kind="hq", actor="t@x",
                reason="meh")
    accept_code(CLIENT, code="RETHINK", code_kind="hq", actor="t@x",
                name="ok", category="nvl", sources=["bcct"])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.catalog_rejections "
            "where client_id=%s and code='RETHINK'", (CLIENT,),
        )
        assert cur.fetchone()[0] == 0


def test_unreject_lifts_only_suppression():
    """The old unreject left the accepted material + mappings behind by
    accident; the new one touches nothing but the suppression row."""
    accept_code(CLIENT, code="KEEP", code_kind="unified", actor="t@x",
                name="k", category="nvl", sources=["bcct"])
    reject_code(CLIENT, code="OTHER", code_kind="hq", actor="t@x")
    assert unreject_code(CLIENT, code="OTHER", actor="t@x") is True
    assert unreject_code(CLIENT, code="OTHER", actor="t@x") is False
    assert _material("KEEP") is not None
    acts = [a for a, _ in _audit_actions()]
    assert acts == ["accept", "reject", "unreject"]
