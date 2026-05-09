"""Accept + Reject + Un-reject — state machine transitions and auto-mapping.

Brief D5: bidirectional auto-mapping (idempotent, order-independent).
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.database import connect


CLIENT = "_test_accept_dual"
ACTOR = "test@example.com"


@pytest.fixture(autouse=True)
def setup_client():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'accept test') "
            "on conflict do nothing",
            (CLIENT,),
        )
        for tbl in ("catalog_candidates", "code_mappings", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,)
        )
        # Seed parser rule (paren-extract)
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test') "
            "on conflict do nothing",
            (CLIENT,),
        )
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()

    yield

    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_candidates", "code_mappings", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,)
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()


def _seed_bcct(rows):
    """rows: list of (decl, customs_code, goods_name, direction)."""
    with connect() as conn, conn.cursor() as cur:
        for i, (decl, cc, gn, dirn) in enumerate(rows):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', %s, '2026-04-01',
                        %s, %s, '{}'::jsonb)
                """,
                (CLIENT, f"TX_{decl}_{i}", decl, dirn, cc, gn),
            )


def _seed_candidate(code, kind, status="pending"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.catalog_candidates "
            " (client_id, code, code_kind, status, observed_count, sources) "
            "values (%s, %s, %s, %s, 1, '{bcct}') "
            "on conflict do nothing returning candidate_id",
            (CLIENT, code, kind, status),
        )
        result = cur.fetchone()
        return result[0] if result else None


def _seed_material(code, kind):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source, code_kind) "
            "values (%s, %s, 'x', 'nvl', 'active', 'client_declared', %s) "
            "on conflict (client_id, material_code) do nothing",
            (CLIENT, code, kind),
        )


def _materials():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, code_kind, name, category, status, source "
            "from hub.materials where client_id=%s order by material_code",
            (CLIENT,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _mappings():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select customs_code, internal_code from hub.code_mappings "
            "where client_id=%s order by customs_code, internal_code",
            (CLIENT,),
        )
        return cur.fetchall()


def _candidate_status(code, kind):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select status, decided_at, decided_by, decision_reason "
            "from hub.catalog_candidates where client_id=%s and code=%s "
            "and code_kind=%s",
            (CLIENT, code, kind),
        )
        return cur.fetchone()


# ── Accept: basic flow ────────────────────────────────────────────────────


def test_accept_inserts_material_and_marks_candidate_accepted():
    from app.stores.catalog_candidates import accept_candidate
    cid = _seed_candidate("DAUNOI", "hq")
    accept_candidate(cid, actor=ACTOR, name="Đầu nối", category="nvl",
                     status="active")
    mats = _materials()
    assert len(mats) == 1
    assert mats[0]["material_code"] == "DAUNOI"
    assert mats[0]["code_kind"] == "hq"
    assert mats[0]["category"] == "nvl"
    assert mats[0]["status"] == "active"
    assert mats[0]["source"] in ("bcct_observed", "bom_observed", "client_declared")
    cstat = _candidate_status("DAUNOI", "hq")
    assert cstat[0] == "accepted"
    assert cstat[1] is not None  # decided_at
    assert cstat[2] == ACTOR


def test_accept_unified_no_auto_mapping():
    """Johnson-shape: code_kind='unified' → no mapping work needed."""
    from app.stores.catalog_candidates import accept_candidate
    cid = _seed_candidate("1000527370", "unified")
    accept_candidate(cid, actor=ACTOR, name="Tấm đỡ", category="nvl",
                     status="under_review")
    assert _mappings() == []


# ── Accept HQ: auto-mapping bidirectional ─────────────────────────────────


def test_accept_hq_auto_maps_existing_nb():
    """Accept HQ when 50/100 NB are already in materials → 50 mappings."""
    from app.stores.catalog_candidates import accept_candidate
    _seed_bcct([
        ("D1", "DAUNOI", "DAUNOI (019.X)", "import"),
        ("D2", "DAUNOI", "DAUNOI (019.Y)", "import"),
        ("D3", "DAUNOI", "DAUNOI (019.Z)", "import"),
    ])
    # 2 of 3 NB already in materials
    _seed_material("019.X", "nb")
    _seed_material("019.Y", "nb")
    cid = _seed_candidate("DAUNOI", "hq")
    accept_candidate(cid, actor=ACTOR, name="Đầu nối", category="nvl",
                     status="active")
    maps = _mappings()
    # 019.X and 019.Y mapped; 019.Z skipped (not in materials yet)
    assert sorted(maps) == sorted([("DAUNOI", "019.X"), ("DAUNOI", "019.Y")])


def test_accept_hq_no_mapping_when_zero_nb_in_materials():
    """Accept HQ first; no NB exists yet → 0 mappings created. Self-heals on later NB Accept."""
    from app.stores.catalog_candidates import accept_candidate
    _seed_bcct([("D1", "DAUNOI", "DAUNOI (019.X)", "import")])
    cid = _seed_candidate("DAUNOI", "hq")
    accept_candidate(cid, actor=ACTOR, name="Đầu nối", category="nvl",
                     status="active")
    assert _mappings() == []


# ── Accept NB: auto-mapping retroactive ───────────────────────────────────


def test_accept_nb_auto_maps_existing_hq():
    """Accept NB after HQ already in materials → mapping created retroactively."""
    from app.stores.catalog_candidates import accept_candidate
    _seed_bcct([
        ("D1", "DAUNOI", "DAUNOI (019.X)", "import"),
        ("D2", "DOV",    "DOV (019.X)",    "import"),  # n-1 case
    ])
    _seed_material("DAUNOI", "hq")
    _seed_material("DOV", "hq")
    cid = _seed_candidate("019.X", "nb")
    accept_candidate(cid, actor=ACTOR, name="part", category="nvl",
                     status="active")
    maps = _mappings()
    assert sorted(maps) == sorted([("DAUNOI", "019.X"), ("DOV", "019.X")])


# ── Order-independence ────────────────────────────────────────────────────


def test_accept_order_independent_hq_first():
    """Accept HQ first, then NB → final state has mapping."""
    from app.stores.catalog_candidates import accept_candidate
    _seed_bcct([("D1", "DAUNOI", "DAUNOI (019.X)", "import")])
    cid_hq = _seed_candidate("DAUNOI", "hq")
    accept_candidate(cid_hq, actor=ACTOR, name="bucket", category="nvl",
                     status="active")
    cid_nb = _seed_candidate("019.X", "nb")
    accept_candidate(cid_nb, actor=ACTOR, name="part", category="nvl",
                     status="active")
    assert _mappings() == [("DAUNOI", "019.X")]


def test_accept_order_independent_nb_first():
    """Accept NB first, then HQ → same final state."""
    from app.stores.catalog_candidates import accept_candidate
    _seed_bcct([("D1", "DAUNOI", "DAUNOI (019.X)", "import")])
    cid_nb = _seed_candidate("019.X", "nb")
    accept_candidate(cid_nb, actor=ACTOR, name="part", category="nvl",
                     status="active")
    cid_hq = _seed_candidate("DAUNOI", "hq")
    accept_candidate(cid_hq, actor=ACTOR, name="bucket", category="nvl",
                     status="active")
    assert _mappings() == [("DAUNOI", "019.X")]


# ── Idempotency ───────────────────────────────────────────────────────────


def test_accept_idempotent_on_existing_mapping():
    """If mapping already exists (e.g. from BQD upload), Accept is no-op."""
    from app.stores.catalog_candidates import accept_candidate
    _seed_bcct([("D1", "DAUNOI", "DAUNOI (019.X)", "import")])
    _seed_material("019.X", "nb")
    # Pre-existing mapping (BQD-shape)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.code_mappings (client_id, internal_code, customs_code) "
            "values (%s, '019.X', 'DAUNOI')", (CLIENT,)
        )
    cid = _seed_candidate("DAUNOI", "hq")
    accept_candidate(cid, actor=ACTOR, name="bucket", category="nvl",
                     status="active")
    # Still 1 mapping, no duplicate
    assert _mappings() == [("DAUNOI", "019.X")]


# ── Reject / Un-reject ────────────────────────────────────────────────────


def test_reject_marks_candidate_rejected():
    from app.stores.catalog_candidates import reject_candidate
    cid = _seed_candidate("NOISE", "hq")
    reject_candidate(cid, actor=ACTOR, reason="test data, ignore")
    cstat = _candidate_status("NOISE", "hq")
    assert cstat[0] == "rejected"
    assert cstat[2] == ACTOR
    assert cstat[3] == "test data, ignore"


def test_reject_does_not_insert_material():
    from app.stores.catalog_candidates import reject_candidate
    cid = _seed_candidate("NOISE", "hq")
    reject_candidate(cid, actor=ACTOR, reason="noise")
    assert _materials() == []


def test_unreject_resets_to_pending():
    from app.stores.catalog_candidates import reject_candidate, unreject_candidate
    cid = _seed_candidate("MAYBE", "hq")
    reject_candidate(cid, actor=ACTOR, reason="not sure")
    unreject_candidate(cid, actor=ACTOR)
    cstat = _candidate_status("MAYBE", "hq")
    assert cstat[0] == "pending"
    assert cstat[1] is None  # decided_at cleared
    assert cstat[2] is None  # decided_by cleared
    assert cstat[3] is None  # decision_reason cleared
