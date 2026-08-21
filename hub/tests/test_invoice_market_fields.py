"""Provider tests for /v1/hub/bcct/invoice-matches additive fields +
market_hint derivation. Contract spec mirrored at
`.ai/features/2026-05-03-bcct-invoice-market-fields/brief.md`.

Auth fixtures borrow the disabled-bearer helper from test_read_api_auth
so test setup stays focused on the data-shape concerns.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from hub.app import markets
from hub.app.database import connect
from hub.app.main import app


@pytest.fixture(autouse=True)
def auth_disabled(monkeypatch):
    """Skip bearer plumbing — this contract is read-only and the auth
    layer has its own dedicated tests."""
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded_export():
    """Throwaway client + a handful of export BCCT rows mirroring the
    real Growatt invoice / unloading-location patterns from the brief."""
    cid = "imkt-" + secrets.token_hex(4)
    inv = "GUS28826A131-3F"
    rows = [
        # row 1 — US unloading
        ("308449399330", "133.0", "E42", "2026-04-18",
         "SD00.0010600", "SD00.0010600#&Pin Lithium-ion",
         inv, "USLAX - LOS ANGELES - CA",
         "03EES06", "CANG LACH HUYEN HP",
         "BASE POWER DEVELOPMENT, LLC", "FOB"),
        # row 2 — IN unloading (Chennai)
        ("308449399331", "1.0", "E42", "2026-04-19",
         "SD00.0010601", "SD00.0010601#&Pin Lithium-ion India batch",
         "GIN-29981A", "INMAA - CHENNAI (EX MADRAS)",
         "03EES06", "CANG LACH HUYEN HP",
         "INDIAN POWER LTD", "FOB"),
        # row 3 — IN unloading (Nhava Sheva) — same India invoice
        ("308449399331", "2.0", "E42", "2026-04-19",
         "SD00.0010602", "SD00.0010602#&Cell module",
         "GIN-29981A", "INNSA - NHAVA SHEVA",
         "03EES06", "CANG LACH HUYEN HP",
         "INDIAN POWER LTD", "FOB"),
        # row 4 — VN unloading (bonded domestic transfer)
        ("308449399332", "1.0", "E62", "2026-04-20",
         "SD00.0010700", "SD00.0010700#&Domestic transfer",
         "GVN-LOCAL", "VNZZZ - CONG TY TNHH ABC",
         "03EES06", "CANG NAM DINH VU",
         "ABC VIETNAM LTD", "DAP"),
        # row 5 — missing unloading
        ("308449399333", "1.0", "E42", "2026-04-21",
         "SD00.0010800", "SD00.0010800#&No-unloading-data row",
         "GUS-NOUL-001", None,
         "03EES06", "CANG LACH HUYEN HP",
         "TEST CONSIGNEE", "FOB"),
        # row 6 — non-LOCODE unloading (operator wrote free-text)
        ("308449399334", "1.0", "E42", "2026-04-22",
         "SD00.0010900", "SD00.0010900#&Free-text UL row",
         "GUS-BOGUS-001", "TBD - manual entry",
         "03EES06", "CANG LACH HUYEN HP",
         "TEST CONSIGNEE", "FOB"),
        # row 7 — IMPORT direction (must NOT be returned)
        ("308449399335", "1.0", "E11", "2026-04-23",
         "SD00.0010900", "Polyethylene resin",
         inv, "USLAX - LOS ANGELES - CA",
         "", "",
         "GROWATT VIET NAM", "CIF"),
    ]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into hub.clients
                   (client_id, name, code_resolution_mode, bom_proposal_mode)
                   values (%s, 'Invoice Market Test', 'identity', 'auto')""",
                (cid,),
            )
            for (decl, line, dtype, regdate, code, gname, invref, ul,
                 dest_code, dest_name, consignee, incoterms) in rows:
                direction = "import" if dtype == "E11" else "export"
                payload = {}
                if ul is not None:
                    payload["Địa điểm dỡ hàng"] = ul
                cur.execute(
                    """insert into hub.bcct_rows
                       (client_id, transaction_key, line_no, declaration_no,
                        declaration_type, direction, registration_date,
                        customs_code, goods_name,
                        invoice_ref, destination_code, destination_name,
                        consignee_name, exporter_name, incoterms,
                        invoice_date, departure_date, unloading_location,
                        payload)
                       values (%s, %s, %s, %s, %s, %s, %s,
                               %s, %s,
                               %s, %s, %s,
                               %s, %s, %s,
                               %s, %s, %s,
                               %s::jsonb)""",
                    (cid, f"{decl}-{line}", line, decl, dtype, direction,
                     regdate, code, gname,
                     invref, dest_code or None, dest_name or None,
                     consignee, "GROWATT VIET NAM", incoterms,
                     regdate, regdate, ul,
                     __import__("json").dumps(payload, ensure_ascii=False)),
                )
    yield {"client_id": cid, "invoice_no": inv, "india_invoice": "GIN-29981A"}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.bcct_rows where client_id = %s", (cid,))
            # The DELETE above fires trg_bcct_row_history capturing the
            # synthetic `.0` rows. Flush the history too so it doesn't
            # leak into live-DB integrity assertions in other test files.
            cur.execute(
                "delete from hub.bcct_row_history where client_id = %s",
                (cid,),
            )
            cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _client():
    return TestClient(app)


# ─── Provider tests ─────────────────────────────────────────────────────


def test_returns_extra_fields(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["invoice_no"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert len(items) == 1, items
    item = items[0]
    # New additive fields all present
    for key in (
        "invoice_date", "departure_date", "incoterms",
        "consignee_name", "exporter_name", "unloading_location",
        "destination_location_code", "destination_location_name",
        "market_hint",
    ):
        assert key in item, f"missing field: {key}"
    # Existing fields unchanged
    assert item["declaration_no"] == "308449399330"
    assert item["item_code"] == "SD00.0010600"
    assert item["transaction_key"] == "308449399330-133.0"


def test_uslax_high_confidence(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["invoice_no"],
        },
    )
    body = r.json()
    hint = body["items"][0]["market_hint"]
    assert hint["country_code"] == "US"
    assert hint["country_name"] == "United States"
    assert hint["source_field"] == "unloading_location"
    assert hint["source_value"] == "USLAX - LOS ANGELES - CA"
    assert hint["confidence"] == "high"


def test_india_unloading_high_confidence(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["india_invoice"],
        },
    )
    body = r.json()
    items = body["items"]
    assert len(items) == 2
    codes = {it["market_hint"]["country_code"] for it in items}
    confidences = {it["market_hint"]["confidence"] for it in items}
    assert codes == {"IN"}
    assert confidences == {"high"}


def test_destination_does_not_become_market(seeded_export):
    """`destination_location_*` carries Vietnam-side bonded info — the
    response surfaces it as raw evidence but it must never feed into
    market_hint."""
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": "GUS-NOUL-001",
        },
    )
    body = r.json()
    item = body["items"][0]
    assert item["destination_location_name"] == "CANG LACH HUYEN HP"
    assert item["market_hint"] is None


def test_vn_unloading_downgrades_to_medium(seeded_export):
    """`VNZZZ` unloading = bonded domestic transfer, not a real export
    market. We surface VN with medium confidence so CO operator confirms."""
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": "GVN-LOCAL",
        },
    )
    body = r.json()
    item = body["items"][0]
    hint = item["market_hint"]
    assert hint["country_code"] == "VN"
    assert hint["confidence"] == "medium"


def test_bogus_unloading_low_confidence(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": "GUS-BOGUS-001",
        },
    )
    item = r.json()["items"][0]
    hint = item["market_hint"]
    assert hint["country_code"] is None
    assert hint["country_name"] is None
    assert hint["confidence"] == "low"
    assert hint["source_value"] == "TBD - manual entry"


def test_include_market_hint_false_skips_hint(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["invoice_no"],
            "include_market_hint": "false",
        },
    )
    item = r.json()["items"][0]
    assert "market_hint" not in item
    # Raw evidence still present
    assert item["unloading_location"] == "USLAX - LOS ANGELES - CA"


def test_imports_excluded(seeded_export):
    """Direction-filtered: the seeded import row must never be returned
    even though its invoice_ref matches."""
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["invoice_no"],
        },
    )
    items = r.json()["items"]
    assert all(it["declaration_type"] != "E11" for it in items)


# ─── Negative tests ─────────────────────────────────────────────────────


def test_400_missing_invoice_no(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={"client_id": seeded_export["client_id"], "invoice_no": ""},
    )
    assert r.status_code == 400
    assert "missing_invoice_no" in r.text


def test_400_whitespace_invoice_no(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={"client_id": seeded_export["client_id"], "invoice_no": "   "},
    )
    assert r.status_code == 400


def test_404_unknown_client():
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={"client_id": "no-such-client-xx", "invoice_no": "ABC-1"},
    )
    assert r.status_code == 404
    assert "unknown_client" in r.text


def test_422_invalid_declaration_types(seeded_export):
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["invoice_no"],
            "declaration_types": "E42, <script>",
        },
    )
    assert r.status_code == 422
    assert "invalid_declaration_types" in r.text


def test_client_isolation_between_clients(seeded_export):
    """A second client owning rows with the same invoice_no must not
    leak into the first client's response."""
    other = "imkt-other-" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into hub.clients
                   (client_id, name, code_resolution_mode, bom_proposal_mode)
                   values (%s, 'Other Co', 'identity', 'auto')""",
                (other,),
            )
            cur.execute(
                """insert into hub.bcct_rows
                   (client_id, transaction_key, line_no, declaration_no,
                    declaration_type, direction, registration_date,
                    customs_code, goods_name, invoice_ref, payload)
                   values (%s, 'OTHER-1', '1.0', 'OTHER-DECL', 'E42',
                           'export', '2026-04-18', 'X', 'X',
                           %s, '{}'::jsonb)""",
                (other, seeded_export["invoice_no"]),
            )
    try:
        r = _client().get(
            "/v1/hub/bcct/invoice-matches",
            params={
                "client_id": seeded_export["client_id"],
                "invoice_no": seeded_export["invoice_no"],
            },
        )
        items = r.json()["items"]
        for it in items:
            # All returned rows must belong to the requested client.
            assert "OTHER" not in it["transaction_key"]
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.bcct_rows where client_id = %s", (other,))
                cur.execute(
                    "delete from hub.bcct_row_history where client_id = %s",
                    (other,),
                )
                cur.execute("delete from hub.clients where client_id = %s", (other,))


# ─── Pagination ─────────────────────────────────────────────────────────


def test_limit_and_cursor(seeded_export):
    r1 = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["india_invoice"],
            "limit": 1,
        },
    )
    body1 = r1.json()
    assert len(body1["items"]) == 1
    assert body1["next_cursor"] == "1"
    r2 = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["india_invoice"],
            "limit": 1, "cursor": body1["next_cursor"],
        },
    )
    body2 = r2.json()
    assert len(body2["items"]) == 1
    assert body2["next_cursor"] is None
    # Stable sort: declaration_no asc → line 1.0 then 2.0 within same date.
    assert body1["items"][0]["line_no"] == "1.0"
    assert body2["items"][0]["line_no"] == "2.0"


def test_limit_capped_at_500(seeded_export):
    """Spec: max 500. Sending 9999 must clamp."""
    r = _client().get(
        "/v1/hub/bcct/invoice-matches",
        params={
            "client_id": seeded_export["client_id"],
            "invoice_no": seeded_export["invoice_no"],
            "limit": 9999,
        },
    )
    assert r.status_code == 200


# ─── Pure helper ────────────────────────────────────────────────────────


def test_market_helper_uslax():
    h = markets.unloading_location_to_market_hint("USLAX - LOS ANGELES - CA")
    assert h is not None
    assert h.country_code == "US"
    assert h.confidence == "high"


def test_market_helper_inmaa():
    h = markets.unloading_location_to_market_hint("INMAA - CHENNAI (EX MADRAS)")
    assert h.country_code == "IN"


def test_market_helper_vn_medium():
    h = markets.unloading_location_to_market_hint("VNZZZ - CONG TY TNHH ABC")
    assert h.country_code == "VN"
    assert h.confidence == "medium"


def test_market_helper_returns_none_on_empty():
    assert markets.unloading_location_to_market_hint("") is None
    assert markets.unloading_location_to_market_hint(None) is None
    assert markets.unloading_location_to_market_hint("   ") is None


def test_market_helper_unknown_code_keeps_high():
    """A made-up but well-formed UN/LOCODE prefix → high confidence on
    the code, null country_name (consumer renders raw)."""
    h = markets.unloading_location_to_market_hint("XX123 - UNKNOWN PORT")
    assert h.country_code == "XX"
    assert h.country_name is None
    assert h.confidence == "high"
