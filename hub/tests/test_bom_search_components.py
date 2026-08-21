"""BOM product search matches component (NVL) codes inside BOMs.

The product list search box (`q`) historically only matched the
finished-product code (`bom_artifacts.product_code`). These tests pin
the extended behavior: `q` also matches any component code living in
`bom_artifact_rows.material_code` (manual_flat / flattened) or
`bom_edges.child_code` (technical_raw graph). A product is returned
when its code OR any component in any of its alive artifacts matches.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect


CLIENT = "bom_search_test"
PROD = "TP_SEARCH_PARENT"
NVL_ROW = "NVL_ONLY_IN_ROWS"
NVL_EDGE = "NVL_ONLY_IN_EDGES"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "bom search test"),
        )
        conn.commit()
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        conn.commit()


def _insert_artifact(artifact_id: str, product_code: str = PROD,
                     artifact_no: int = 1):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "parent_artifact_id, context, normalized_hash, row_count, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) "
            "values (%s, %s, %s, %s, 'published', 'agency_staff', "
            "'asserted_technical', null, '{}', %s, 0, "
            "'technical_flattened', 'flattened', 'manual_flat_as_provided', "
            "'staff_form', 'default', '{}', 'as_provided', 'v1', now())",
            (artifact_id, CLIENT, product_code, artifact_no,
             f"h_{artifact_id}"),
        )
        conn.commit()


def _insert_row(artifact_id: str, material_code: str, row_index: int = 0):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifact_rows (artifact_id, row_index, "
            "material_code, qty_per_unit, uom) values (%s, %s, %s, 1, 'PCS')",
            (artifact_id, row_index, material_code),
        )
        conn.commit()


def _insert_edge(artifact_id: str, child_code: str, row_index: int = 0):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) "
            "values (%s, %s, %s, %s, %s, 1, 'PCS')",
            (artifact_id, row_index, PROD, PROD, child_code),
        )
        conn.commit()


def _codes(rows):
    return {r["product_code"] for r in rows}


# ── search by product code still works ──────────────────────────────


def test_search_by_product_code_still_matches():
    from hub.app.stores.bom import list_products_with_bom
    _insert_artifact("ba_s_pc")
    rows = list_products_with_bom(CLIENT, q="SEARCH_PARENT", limit=10)
    assert PROD in _codes(rows)


# ── search by component code in flat rows ───────────────────────────


def test_search_by_nvl_in_rows_returns_parent_product():
    from hub.app.stores.bom import list_products_with_bom
    aid = "ba_s_rows"
    _insert_artifact(aid)
    _insert_row(aid, NVL_ROW)
    rows = list_products_with_bom(CLIENT, q="ONLY_IN_ROWS", limit=10)
    assert PROD in _codes(rows), (
        "product whose flat BOM contains the NVL should match"
    )


# ── search by component code in raw graph edges ─────────────────────


def test_search_by_nvl_in_edges_returns_parent_product():
    from hub.app.stores.bom import list_products_with_bom
    aid = "ba_s_edges"
    _insert_artifact(aid)
    _insert_edge(aid, NVL_EDGE)
    rows = list_products_with_bom(CLIENT, q="ONLY_IN_EDGES", limit=10)
    assert PROD in _codes(rows), (
        "product whose graph BOM contains the NVL should match"
    )


# ── non-matching component is excluded ──────────────────────────────


def test_search_unrelated_code_excludes_product():
    from hub.app.stores.bom import list_products_with_bom
    aid = "ba_s_none"
    _insert_artifact(aid)
    _insert_row(aid, NVL_ROW)
    rows = list_products_with_bom(CLIENT, q="NONEXISTENT_XYZ", limit=10)
    assert PROD not in _codes(rows)


# ── no duplicate row when both product code and NVL match ───────────


def test_product_appears_once_when_code_and_component_both_match():
    """A `q` that matches both product_code and a component must not
    duplicate the product in the result set."""
    from hub.app.stores.bom import list_products_with_bom
    aid = "ba_s_dup"
    # product_code = TP_SEARCH_PARENT, component code shares "PARENT".
    _insert_artifact(aid)
    _insert_row(aid, "NVL_PARENT_SHARED")
    rows = list_products_with_bom(CLIENT, q="PARENT", limit=10)
    matches = [r for r in rows if r["product_code"] == PROD]
    assert len(matches) == 1, f"expected one row, got {len(matches)}"


# ── count mirrors list ──────────────────────────────────────────────


def test_count_matches_list_for_component_search():
    from hub.app.stores.bom import (
        list_products_with_bom,
        count_products_with_bom,
    )
    aid = "ba_s_count"
    _insert_artifact(aid)
    _insert_edge(aid, NVL_EDGE)
    rows = list_products_with_bom(CLIENT, q="ONLY_IN_EDGES", limit=50)
    n = count_products_with_bom(CLIENT, q="ONLY_IN_EDGES")
    assert n == len(rows) == 1


# ── API: /v1/hub/products forwards q to the component-aware search ──


def test_api_products_endpoint_filters_by_component_code():
    from fastapi.testclient import TestClient
    from hub.app import jwt_issuer, settings_store
    from hub.app.main import app

    settings_store.set_many({"api_auth_strict": "false"})
    aid = "ba_s_api"
    _insert_artifact(aid)
    _insert_row(aid, NVL_ROW)
    token = jwt_issuer.make_token(
        user_id="u_bom_search",
        email="bom-search@test.local",
        role="admin",
        display_name="BOM Search",
    )["access_token"]
    client = TestClient(app)
    hit = client.get(
        f"/v1/hub/products?client_id={CLIENT}&q=ONLY_IN_ROWS",
        headers={"authorization": f"Bearer {token}"},
    )
    miss = client.get(
        f"/v1/hub/products?client_id={CLIENT}&q=NONEXISTENT_XYZ",
        headers={"authorization": f"Bearer {token}"},
    )
    assert PROD in {r["product_code"] for r in hit.json()["items"]}
    assert PROD not in {r["product_code"] for r in miss.json()["items"]}
