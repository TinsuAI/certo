"""Invariant: when fixup_johnson_btp_sx_after_bom inserts a bom_observed
BTP material (BTP first appears in BOM, no BCCT yet), catalog uom is
captured from `hub.bom_edges.uom` WHERE the BTP appears as CHILD — its
Component unit, the unit it is consumed in by its parent. Per
`project_bom_component_unit_canonical`, Component unit is canonical;
Base UoM (which would come from rows where the BTP is parent = uom of
its inputs) is SAP stockkeeping internal and must NOT be used.

Mig 063 first wired UoM capture (was uom=NULL on 2,615 BTPs); 2026-05-25
correction switched parent_code → child_code after 440 Johnson BTPs
landed with uom=KG (Base UoM) instead of EA (Component unit).
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect


@pytest.fixture
def test_client():
    cid = "fixup-btp-uom-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode, "
            "bom_proposal_mode) values (%s, 'Fixup BTP Test', 'identity', 'auto')",
            (cid,),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (cid,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
        cur.execute("delete from hub.materials where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _seed_raw_artifact_with_edges(client_id: str, product_code: str,
                                  edges: list[tuple[str, str, float, str]]):
    """edges = [(parent_code, child_code, qty, uom), ...]"""
    artifact_id = "ba_fixup_" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.bom_artifacts
              (artifact_id, client_id, product_code, artifact_no, actor, intent,
               normalized_hash, source_bom_kind, flatten_status, flatten_strategy,
               source_channel, flatten_method, flatten_method_version)
            values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical',
                    %s, 'technical_raw', 'non_flattened', 'no_strategy',
                    'agency_upload', 'manual', '0.1')
            """,
            (artifact_id, client_id, product_code,
             "h_" + secrets.token_hex(8)),
        )
        # Need parent to exist as a material before child edges (FK is on
        # bom_artifacts.product_code → materials; bom_edges has no such FK,
        # so we can just seed the artifact + edges).
        for i, (parent, child, qty, uom) in enumerate(edges):
            cur.execute(
                "insert into hub.bom_edges (artifact_id, row_index, root_code, "
                "parent_code, child_code, qty_per_parent, uom) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                (artifact_id, i, product_code, parent, child, qty, uom),
            )
    return artifact_id


def _read_uom(client_id: str, material_code: str) -> str | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select uom from hub.materials "
            "where client_id=%s and material_code=%s",
            (client_id, material_code),
        )
        row = cur.fetchone()
    return row[0] if row else None


def test_fixup_btp_captures_uom_from_bom_edges_mode(test_client):
    """BTP-A appears as CHILD in 3 edges with mixed UoM (mode = EA, 2/3).
    Catalog uom must be the mode of Component unit (as-child rows), not
    Base UoM (which would come from rows where BTP-A is parent).
    """
    # Seed: BTP-A appears as child of 3 different parents — mode EA (2/3).
    # Also as parent of leaves (uom KG) — irrelevant for catalog uom.
    _seed_raw_artifact_with_edges(test_client, "TP-X", [
        ("TP-X",  "BTP-A", 1.0, "EA"),
        ("TP-Y",  "BTP-A", 2.0, "EA"),
        ("TP-Z",  "BTP-A", 0.5, "KG"),
        ("BTP-A", "NVL-1", 0.5, "KG"),
        ("BTP-A", "NVL-2", 0.3, "KG"),
    ])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials
              (client_id, material_code, name, category, status, source,
               code_kind, uom, provenance)
            select %s, code, code, 'btp_sx', 'active', 'bom_observed',
                   'unified',
                   (select e.uom
                      from hub.bom_edges e
                      join hub.bom_artifacts a
                           on a.artifact_id = e.artifact_id
                     where a.client_id = %s
                       and e.child_code = code
                       and a.tombstoned_at is null
                       and e.uom is not null and trim(e.uom) <> ''
                     group by e.uom
                     order by count(*) desc, e.uom
                     limit 1) as uom,
                   '{"seen_in_bom_only": true}'::jsonb
              from unnest(%s::text[]) as code
            on conflict (client_id, material_code) do update set
              uom = coalesce(hub.materials.uom, excluded.uom),
              updated_at = now()
            """,
            (test_client, test_client, ["BTP-A"]),
        )
    assert _read_uom(test_client, "BTP-A") == "EA"


def test_fixup_btp_uom_null_when_no_edges_match(test_client):
    """BTP-with-no-edges (defensive case): script still inserts but uom=NULL.
    Engine then surfaces drift; staff resolves via catalog edit form."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials
              (client_id, material_code, name, category, status, source,
               code_kind, uom, provenance)
            select %s, code, code, 'btp_sx', 'active', 'bom_observed',
                   'unified',
                   (select e.uom from hub.bom_edges e
                      join hub.bom_artifacts a
                           on a.artifact_id = e.artifact_id
                     where a.client_id = %s and e.child_code = code
                       and a.tombstoned_at is null and e.uom is not null
                     group by e.uom order by count(*) desc, e.uom limit 1),
                   '{"seen_in_bom_only": true}'::jsonb
              from unnest(%s::text[]) as code
            on conflict (client_id, material_code) do nothing
            """,
            (test_client, test_client, ["BTP-ORPHAN"]),
        )
    assert _read_uom(test_client, "BTP-ORPHAN") is None


def test_fixup_btp_uom_does_not_clobber_existing(test_client):
    """If material already exists with uom (staff-declared), fixup must
    not overwrite it. ON CONFLICT path preserves staff override."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, category, "
            "status, source, uom) values (%s, %s, 'btp_sx', 'active', "
            "'client_declared', 'pcs')",
            (test_client, "BTP-STAFF"),
        )
    _seed_raw_artifact_with_edges(test_client, "TP-Y", [
        ("TP-Y", "BTP-STAFF", 1.0, "KG"),
    ])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials
              (client_id, material_code, name, category, status, source,
               code_kind, uom, provenance)
            select %s, code, code, 'btp_sx', 'active', 'bom_observed',
                   'unified',
                   (select e.uom from hub.bom_edges e
                      join hub.bom_artifacts a
                           on a.artifact_id = e.artifact_id
                     where a.client_id = %s and e.child_code = code
                       and a.tombstoned_at is null and e.uom is not null
                     group by e.uom order by count(*) desc, e.uom limit 1),
                   '{"seen_in_bom_only": true}'::jsonb
              from unnest(%s::text[]) as code
            on conflict (client_id, material_code) do update set
              uom = coalesce(hub.materials.uom, excluded.uom),
              updated_at = now()
            """,
            (test_client, test_client, ["BTP-STAFF"]),
        )
    # Staff-declared 'pcs' wins over BOM-observed 'KG'.
    assert _read_uom(test_client, "BTP-STAFF") == "pcs"
