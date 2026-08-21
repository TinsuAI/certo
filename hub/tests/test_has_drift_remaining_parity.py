"""Parity: SQL `hub.has_drift_remaining` ⇔ Python `classify_uom_relation`.

D.2 (scope A). The SQL staleness drift check must accept exactly the
pairs the classifier accepts: a UoM difference is only "drift remaining"
(staff must add a factor) when `classify_uom_relation` returns
`incompatible`. Before this feature the SQL only knew alias-align + a
single per-material exact override, so it over-flagged same-family
(g↔kg), tier-A (ea↔sets), reverse-direction overrides, and client-wide
overrides as drift.

`has_drift_remaining` is the drift guard's pinned side: this corpus asserts
it never diverges from the classifier again (brief R1). Cases with a
missing uom on either side are out of scope here — the SQL deliberately
returns false there (nothing to compare); see the dedicated tests in
test_bom_state_and_conditional_triggers.py.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.app.stores.uom import classify_uom_relation


CLIENT = "_drift_parity_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing",
            (CLIENT, "drift parity test"))
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_uom_overrides where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_material(cur, code, uom):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, 'nvl', 'active', %s) "
        "on conflict (client_id, material_code) do update set uom=excluded.uom",
        (CLIENT, code, code, uom))


def _seed_override(cur, material_code, from_uom, to_uom, factor):
    cur.execute(
        "insert into hub.client_uom_overrides "
        "(client_id, material_code, from_uom, to_uom, factor, source) "
        "values (%s, %s, %s, %s, %s, 'staff_form')",
        (CLIENT, material_code, from_uom, to_uom, factor))


# (id, cat_uom, bom_uom, override, expected_incompatible)
# override = None | (material_code_or_None, from_uom, to_uom, factor)
# expected_incompatible is the absolute pin (third oracle); the test also
# asserts SQL == classifier independently.
CORPUS = [
    ("identity",            "kg",   "kg",          None,                          False),
    ("alias",               "PIECES", "EA",        None,                          False),
    ("same_family_mass",    "kg",   "g",           None,                          False),
    ("same_family_length",  "m",    "cm",          None,                          False),
    ("tier_a_count_assembly", "EA", "SETS",        None,                          False),
    ("tier_a_count_packaging", "EA", "PAIR",       None,                          False),
    ("tier_b_mass_count",   "kg",   "EA",          None,                          True),
    ("tier_b_length_mass",  "m",    "kg",          None,                          True),
    ("override_forward",    "kg",   "EA",          ("M", "EA", "kg", 0.5),        False),
    ("override_reverse",    "kg",   "EA",          ("M", "kg", "EA", 2.0),        False),
    ("override_client_wide", "kg",  "EA",          (None, "EA", "kg", 0.5),       False),
    ("unknown_token",       "kg",   "ZZZUNKNOWN",  None,                          True),
]


@pytest.mark.parametrize("case_id, cat_uom, bom_uom, override, expected_incompatible",
                          CORPUS, ids=[c[0] for c in CORPUS])
def test_has_drift_remaining_matches_classifier(
        case_id, cat_uom, bom_uom, override, expected_incompatible):
    mc = f"M_{case_id}"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, mc, cat_uom)
        if override is not None:
            ov_mc, frm, to, factor = override
            _seed_override(cur, mc if ov_mc == "M" else None, frm, to, factor)

    # Oracle: the shipped, separately-tested classifier.
    rel = classify_uom_relation(bom_uom, cat_uom,
                                client_id=CLIENT, material_code=mc)
    classifier_incompatible = rel.relation == "incompatible"

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select hub.has_drift_remaining(%s, %s, %s)",
                     (CLIENT, mc, bom_uom))
        sql_drift = cur.fetchone()[0]

    # Absolute pin (catches the case where both happen to agree but wrong).
    assert classifier_incompatible is expected_incompatible, (
        f"{case_id}: classifier said relation={rel.relation!r}")
    # The parity guarantee (brief R1): SQL must mirror the classifier.
    assert sql_drift is expected_incompatible, (
        f"{case_id}: has_drift_remaining={sql_drift} but classifier "
        f"incompatible={expected_incompatible} (relation={rel.relation!r})")
