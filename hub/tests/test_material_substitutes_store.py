"""Tests for app.stores.material_substitutes (Feature 4 MVP)."""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.app.routes.clients import upsert_client
from hub.app.stores.material_substitutes import (
    insert_candidate,
    list_for_material,
    refresh_candidates,
    reject_pair,
    unreject_pair,
)


@pytest.fixture
def client_id():
    cid = "test-subs"
    upsert_client(
        client_id=cid, name="Test Subs",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _add_material(client_id, code, hs="12345678", category="nvl"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials
              (client_id, material_code, name, category, status,
               hs_code, source, code_kind)
            values (%s, %s, %s, %s, 'active', %s,
                    'client_declared', 'unified')
            on conflict (client_id, material_code) do nothing
            """,
            (client_id, code, f"Material {code}", category, hs),
        )
        conn.commit()


# ── insert / reject ────────────────────────────────────────────────


def test_insert_basic(client_id):
    _add_material(client_id, "A1")
    _add_material(client_id, "A2")
    fid, created = insert_candidate(
        client_id=client_id, material_a_code="A1", material_b_code="A2",
        source="manual_user", confirmed_by="u1",
    )
    assert created is True
    assert fid > 0


def test_insert_idempotent_same_source(client_id):
    _add_material(client_id, "A1")
    _add_material(client_id, "A2")
    f1, c1 = insert_candidate(
        client_id=client_id, material_a_code="A1", material_b_code="A2",
        source="trigram", score=0.5,
    )
    f2, c2 = insert_candidate(
        client_id=client_id, material_a_code="A1", material_b_code="A2",
        source="trigram", score=0.6,
    )
    assert c1 is True
    assert c2 is False
    assert f1 == f2


def test_self_loop_rejected(client_id):
    _add_material(client_id, "A1")
    with pytest.raises(Exception):
        insert_candidate(
            client_id=client_id, material_a_code="A1", material_b_code="A1",
            source="manual_user",
        )


def test_reject_and_unreject(client_id):
    _add_material(client_id, "A1")
    _add_material(client_id, "A2")
    insert_candidate(
        client_id=client_id, material_a_code="A1", material_b_code="A2",
        source="trigram", score=0.5,
    )
    insert_candidate(
        client_id=client_id, material_a_code="A1", material_b_code="A2",
        source="same_hs",
    )
    n = reject_pair(client_id=client_id, material_a_code="A1",
                    material_b_code="A2", rejected_by="u1")
    assert n == 2
    cands = list_for_material(client_id=client_id, material_code="A1")
    assert cands == []
    cands_inc = list_for_material(client_id=client_id, material_code="A1",
                                   include_rejected=True)
    assert len(cands_inc) == 1
    n = unreject_pair(client_id=client_id, material_a_code="A1",
                      material_b_code="A2")
    assert n == 2
    cands = list_for_material(client_id=client_id, material_code="A1")
    assert len(cands) == 1


# ── ranked listing + scoring ───────────────────────────────────────


def test_list_combines_sources_picks_max(client_id):
    _add_material(client_id, "A1")
    _add_material(client_id, "A2")
    insert_candidate(client_id=client_id, material_a_code="A1",
                      material_b_code="A2", source="trigram", score=0.5)
    insert_candidate(client_id=client_id, material_a_code="A1",
                      material_b_code="A2", source="same_hs")
    cands = list_for_material(client_id=client_id, material_code="A1")
    assert len(cands) == 1
    c = cands[0]
    assert set(c.sources) == {"trigram", "same_hs"}
    # same_hs scored 0.85 > trigram 0.20 + 0.50*0.5 = 0.45
    assert abs(c.combined_score - 0.85) < 0.001


def test_list_orders_by_combined_score_desc(client_id):
    _add_material(client_id, "A1")
    _add_material(client_id, "A2")
    _add_material(client_id, "A3")
    insert_candidate(client_id=client_id, material_a_code="A1",
                      material_b_code="A2", source="trigram", score=0.5)
    insert_candidate(client_id=client_id, material_a_code="A1",
                      material_b_code="A3", source="client_confirmed",
                      confirmed_by="u1")
    cands = list_for_material(client_id=client_id, material_code="A1")
    assert [c.material_b_code for c in cands] == ["A3", "A2"]


def test_list_filters_min_score(client_id):
    _add_material(client_id, "A1")
    _add_material(client_id, "A2")
    insert_candidate(client_id=client_id, material_a_code="A1",
                      material_b_code="A2", source="trigram", score=0.4)
    cands = list_for_material(client_id=client_id, material_code="A1",
                               min_score=0.5)
    assert cands == []
    cands = list_for_material(client_id=client_id, material_code="A1",
                               min_score=0.3)
    assert len(cands) == 1


# ── refresh job ────────────────────────────────────────────────────


def test_refresh_same_hs(client_id):
    # 3 materials with same HS, 1 with different.
    _add_material(client_id, "A1", hs="11111111")
    _add_material(client_id, "A2", hs="11111111")
    _add_material(client_id, "A3", hs="11111111")
    _add_material(client_id, "B1", hs="22222222")
    stats = refresh_candidates(client_id=client_id)
    # Same-HS: 3 codes share HS → 3*2 = 6 directed edges (a≠b within HS).
    assert stats.same_hs_inserted == 6
    cands = list_for_material(client_id=client_id, material_code="A1")
    sources = {s for c in cands for s in c.sources}
    assert "same_hs" in sources
    assert "B1" not in {c.material_b_code for c in cands}


def test_refresh_trigram(client_id):
    # Force off same_hs to isolate trigram path.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.clients set substitute_rules = "
            "substitute_rules || '{\"p4_same_hs\": false}'::jsonb "
            "where client_id=%s", (client_id,),
        )
        conn.commit()
    _add_material(client_id, "PROD-001", hs="11111111")
    _add_material(client_id, "PROD-002", hs="22222222")
    _add_material(client_id, "TOTALLY-DIFFERENT", hs="33333333")
    stats = refresh_candidates(client_id=client_id, trigram_threshold=0.3)
    assert "p4_same_hs" in stats.rules_skipped
    assert stats.trigram_inserted >= 2  # PROD-001↔PROD-002 mutual


def test_refresh_idempotent(client_id):
    _add_material(client_id, "A1", hs="11111111")
    _add_material(client_id, "A2", hs="11111111")
    s1 = refresh_candidates(client_id=client_id)
    s2 = refresh_candidates(client_id=client_id)
    assert s1.same_hs_inserted >= 2
    assert s2.same_hs_inserted == 0  # already inserted


def test_refresh_respects_client_toggle(client_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.clients set substitute_rules = "
            "'{\"p4_same_hs\": false, \"p5_trigram\": false}'::jsonb "
            "where client_id=%s", (client_id,),
        )
        conn.commit()
    _add_material(client_id, "A1", hs="11111111")
    _add_material(client_id, "A2", hs="11111111")
    stats = refresh_candidates(client_id=client_id)
    assert stats.same_hs_inserted == 0
    assert stats.trigram_inserted == 0
    assert "p4_same_hs" in stats.rules_skipped
    assert "p5_trigram" in stats.rules_skipped
