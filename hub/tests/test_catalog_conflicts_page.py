"""Provider-level tests for the catalog conflicts review queue.

Feature brief: .ai/features/2026-05-15-catalog-conflicts-page/brief.md
BACKLOG entry: A.2.

Surfaces two existing conflict signals in a dedicated page:
- `declared_observed_conflict` (column on hub.v_material_roles)
- sourcing-confirmation conflict (Python/SQL-derived: staff
  btp_sourcing ≠ observed dual-source pattern).

Each test seeds a throwaway client with a controlled mix of conflict
rows + clean rows, then drives the page via the FastAPI TestClient
to assert filter chips, counts, row presence, and the nav banner on
the catalog list page.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


# ── Seeding helpers (mirror tests/test_v_material_roles.py pattern) ────


def _seed_material(cur, *, client_id: str, code: str, kind: str = "nvl",
                   btp_sourcing: str | None = None) -> None:
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, btp_sourcing) values (%s, %s, %s, %s, %s)",
        (client_id, code, code, kind, btp_sourcing),
    )


def _seed_bcct_export(cur, *, client_id: str, code: str) -> None:
    cur.execute(
        "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
        "declaration_no, declaration_type, direction, registration_date, "
        "customs_code, goods_name, payload) "
        "values (%s, %s, '1', %s, 'E42', 'export', '2026-01-15', %s, %s, "
        "'{}'::jsonb)",
        (client_id, f"TX-{code}", f"TX-{code}", code, f"{code} test"),
    )


def _seed_bcct_import(cur, *, client_id: str, code: str,
                      declaration_type: str = "E11") -> None:
    cur.execute(
        "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
        "declaration_no, declaration_type, direction, registration_date, "
        "customs_code, goods_name, payload) "
        "values (%s, %s, '1', %s, %s, 'import', '2026-01-15', %s, %s, "
        "'{}'::jsonb)",
        (client_id, f"TXI-{code}", f"TXI-{code}", declaration_type,
         code, f"{code} test"),
    )


def _seed_bom_artifact(cur, *, client_id: str, product_code: str,
                       artifact_id: str) -> None:
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version, status, published_at) "
        "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', %s, "
        "'technical_flattened', 'flattened', 'technical_exploded', "
        "'agency_upload', 'manual', '0.1', 'published', now())",
        (artifact_id, client_id, product_code, f"hash_{artifact_id}"),
    )


def _seed_bom_edge(cur, *, artifact_id: str, parent_code: str,
                   child_code: str) -> None:
    cur.execute(
        "insert into hub.bom_edges (artifact_id, row_index, root_code, "
        "parent_code, child_code, qty_per_parent, uom, level) "
        "values (%s, 1, %s, %s, %s, 1.0, 'PCS', 1)",
        (artifact_id, parent_code, parent_code, child_code),
    )


# ── Throwaway client fixture ───────────────────────────────────────────


@pytest.fixture
def seeded_client():
    """A client with 3 materials:
      - DECL-CONF:  declared nvl but has_exports (observed 'tp')
                    → declared_observed_conflict
      - SRC-CONF:   declared btp_sx, has BOM + is consumed,
                    btp_sourcing='self_produced_only' but also has
                    imports → observed includes btp_nm
                    → sourcing_confirmation_conflict
      - CLEAN-TP:   declared tp, has_exports → no conflict
    """
    cid = "conf-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "conflicts test"),
        )
        # DECL-CONF: nvl declared, observed tp (via has_exports)
        _seed_material(cur, client_id=cid, code="DECL-CONF", kind="nvl")
        _seed_bcct_export(cur, client_id=cid, code="DECL-CONF")

        # SRC-CONF: btp_sx, has own BOM + consumed (observed btp_sx) +
        # has imports (so btp_nm fires too) → observed_roles=[btp_sx,
        # btp_nm]; staff confirm self_produced_only → conflict.
        _seed_material(cur, client_id=cid, code="SRC-CONF", kind="btp_sx",
                       btp_sourcing="self_produced_only")
        _seed_bcct_import(cur, client_id=cid, code="SRC-CONF")
        # Make has_own_bom: own artifact owning SRC-CONF
        own_aid = "own-" + secrets.token_hex(4)
        _seed_bom_artifact(cur, client_id=cid, product_code="SRC-CONF",
                           artifact_id=own_aid)
        _seed_bom_edge(cur, artifact_id=own_aid, parent_code="SRC-CONF",
                       child_code="DECL-CONF")
        # Make is_consumed_in_bom: another artifact consumes SRC-CONF
        parent_aid = "par-" + secrets.token_hex(4)
        _seed_bom_artifact(cur, client_id=cid, product_code="CLEAN-TP",
                           artifact_id=parent_aid)
        _seed_bom_edge(cur, artifact_id=parent_aid, parent_code="CLEAN-TP",
                       child_code="SRC-CONF")

        # CLEAN-TP: declared tp + has_exports → observed_roles=[tp] →
        # no conflict.
        _seed_material(cur, client_id=cid, code="CLEAN-TP", kind="tp")
        _seed_bcct_export(cur, client_id=cid, code="CLEAN-TP")

    yield cid

    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute(
            "delete from hub.bcct_row_history where client_id=%s", (cid,),
        )
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (cid,),
        )
        cur.execute(
            "delete from hub.bom_artifacts where client_id=%s", (cid,),
        )
        cur.execute("delete from hub.materials where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


@pytest.fixture(scope="module")
def authed_client():
    with TestClient(app) as c:
        r = c.post(
            "/login",
            data={"email": "admin@data-hub.local", "password": "admin123",
                  "next": "/clients"},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303), r.text
        yield c


# ── Tests ──────────────────────────────────────────────────────────────


def test_conflicts_page_lists_both_conflict_rows(authed_client, seeded_client):
    """Default `type=all` shows both DECL-CONF and SRC-CONF, omits
    CLEAN-TP."""
    r = authed_client.get(f"/clients/{seeded_client}/catalog/conflicts")
    assert r.status_code == 200, r.text
    body = r.text
    assert "DECL-CONF" in body
    assert "SRC-CONF" in body
    assert "CLEAN-TP" not in body
    # Count header should read total=2 with 1 declared + 1 sourcing.
    assert "2 dòng conflict" in body
    assert "1 khai báo ≠ quan sát" in body
    assert "1 nguồn cung ≠ quan sát" in body


def test_conflicts_filter_type_declared(authed_client, seeded_client):
    r = authed_client.get(
        f"/clients/{seeded_client}/catalog/conflicts?type=declared",
    )
    assert r.status_code == 200
    body = r.text
    assert "DECL-CONF" in body
    assert "SRC-CONF" not in body
    assert "CLEAN-TP" not in body


def test_conflicts_filter_type_sourcing(authed_client, seeded_client):
    r = authed_client.get(
        f"/clients/{seeded_client}/catalog/conflicts?type=sourcing",
    )
    assert r.status_code == 200
    body = r.text
    assert "SRC-CONF" in body
    assert "DECL-CONF" not in body
    assert "CLEAN-TP" not in body


def test_conflicts_filter_invalid_type_falls_back_to_all(
    authed_client, seeded_client,
):
    """An unrecognized `type=` value silently falls back to `all` —
    avoids an ugly 422 when staff hand-edit the URL."""
    r = authed_client.get(
        f"/clients/{seeded_client}/catalog/conflicts?type=banana",
    )
    assert r.status_code == 200
    body = r.text
    # Both conflict rows still present.
    assert "DECL-CONF" in body
    assert "SRC-CONF" in body


def test_catalog_list_shows_nav_banner_when_conflicts_exist(
    authed_client, seeded_client,
):
    r = authed_client.get(f"/clients/{seeded_client}/catalog")
    assert r.status_code == 200
    body = r.text
    assert "2</strong> dòng cần review" in body
    assert "/catalog/conflicts" in body


def test_catalog_list_omits_nav_banner_when_no_conflicts(authed_client):
    """Spin a separate client with no conflicts; banner should be hidden."""
    cid = "noconf-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "no conflicts test"),
        )
        _seed_material(cur, client_id=cid, code="CLEAN-NVL", kind="nvl")
    try:
        r = authed_client.get(f"/clients/{cid}/catalog")
        assert r.status_code == 200
        body = r.text
        assert "dòng cần review" not in body
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from hub.materials where client_id=%s", (cid,),
            )
            cur.execute(
                "delete from hub.clients where client_id=%s", (cid,),
            )


def test_btp_sourcing_post_honors_return_to(authed_client, seeded_client):
    """Conflict page posts btp_sourcing with `return_to` pointing back
    at the conflicts queue. After the update, the conflict resolves
    (staff now confirms dual_source, which matches observed)."""
    return_to = f"/clients/{seeded_client}/catalog/conflicts?type=sourcing"
    r = authed_client.post(
        f"/clients/{seeded_client}/catalog/SRC-CONF/btp_sourcing",
        data={"btp_sourcing": "dual_source", "return_to": return_to},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == return_to

    # The conflict no longer exists; sourcing-filtered page should be
    # empty (modulo seed cleanup).
    r2 = authed_client.get(
        f"/clients/{seeded_client}/catalog/conflicts?type=sourcing",
    )
    assert r2.status_code == 200
    assert "SRC-CONF" not in r2.text


def test_btp_sourcing_post_rejects_cross_client_return_to(
    authed_client, seeded_client,
):
    """A return_to URL pointing at a different client (or a non-/clients
    path) is ignored; the default redirect is used."""
    r = authed_client.post(
        f"/clients/{seeded_client}/catalog/SRC-CONF/btp_sourcing",
        data={"btp_sourcing": "self_produced_only",
              "return_to": "/clients/some-other-client/catalog"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == (
        f"/clients/{seeded_client}/catalog?category=btp_sx"
    )
