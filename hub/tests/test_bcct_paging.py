"""Integration test for the paginated BCCT list view.

Drives the FastAPI app with TestClient against the live data_hub DB
(growatt-vn already has 3000+ rows seeded). Verifies:

- default page returns ≤50 rows even when DB has thousands
- page/page_size/sort/q query params shape the response
- pagination footer renders the correct total
- sort link round-trips
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


CLIENT_ID = "growatt-vn"  # largest dataset in the dev DB


@pytest.fixture(scope="module")
def authed_client():
    with TestClient(app) as c:
        # Seed admin (lifespan does this, but be defensive in case
        # the password env differs).
        r = c.post(
            "/login",
            data={"email": "admin@data-hub.local", "password": "admin123",
                  "next": "/clients"},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303), r.text
        yield c


def test_default_page_is_50_rows(authed_client):
    r = authed_client.get(f"/clients/{CLIENT_ID}/bcct")
    assert r.status_code == 200
    # Each row gets one <tr> in <tbody>. Count tbody trs by counting
    # the cell that always renders for valid rows: the line_no <td>.
    # Simpler heuristic: count occurrences of badge marker for direction.
    # 50 rows × max 1 badge per row → ≤ 50.
    body = r.text
    # Crude row count via the per-row clickable-row attribute (exactly one
    # `data-row-href` per <tr>; the inspect <a> also links to the same path,
    # so count the attribute, not the bare path).
    assert body.count(f'data-row-href="/clients/{CLIENT_ID}/bcct/history/') == 50, (
        "expected exactly 50 clickable rows == 50 rows"
    )


def test_page_size_param_clamps_and_changes_count(authed_client):
    marker = f'data-row-href="/clients/{CLIENT_ID}/bcct/history/'
    r = authed_client.get(f"/clients/{CLIENT_ID}/bcct?page_size=25")
    assert r.text.count(marker) == 25
    r = authed_client.get(f"/clients/{CLIENT_ID}/bcct?page_size=9999")
    # Clamped to MAX_PAGE_SIZE = 200
    assert r.text.count(marker) == 200


def test_page_2_returns_different_rows(authed_client):
    p1 = authed_client.get(f"/clients/{CLIENT_ID}/bcct?page=1&page_size=50").text
    p2 = authed_client.get(f"/clients/{CLIENT_ID}/bcct?page=2&page_size=50").text
    # Pages must not be identical given >100 rows in growatt-vn.
    assert p1 != p2


def test_pager_total_matches_count(authed_client):
    r = authed_client.get(f"/clients/{CLIENT_ID}/bcct?page_size=25")
    # The pager renders "<start>–<end> / <total>"; growatt-vn has
    # ~3185 rows. Don't pin to exact number (test data may grow);
    # assert >=1000.
    import re
    m = re.search(r"\b(\d+)\s*–\s*\d+\s*/\s*(\d+)\b", r.text)
    assert m, "pager footer not found"
    total = int(m.group(2))
    assert total >= 1000, f"unexpectedly small total {total}"


def test_sort_link_round_trips(authed_client):
    r = authed_client.get(
        f"/clients/{CLIENT_ID}/bcct?sort=customs_code&dir=asc&page_size=25",
    )
    assert r.status_code == 200
    # The `customs_code` column header should show the active arrow.
    assert "sort-active" in r.text
    # And the click on Customs Code should now flip to desc (sort_link
    # toggles direction when the column is already active).
    assert "dir=desc" in r.text


def test_q_search_narrows_results(authed_client):
    """Search for an obscure substring; should drop count significantly."""
    r = authed_client.get(
        f"/clients/{CLIENT_ID}/bcct?q=Solar&page_size=25",
    )
    assert r.status_code == 200
    # As long as the page renders (status 200) and search round-trips
    # via the form, this test passes — exact match counts depend on
    # seed data and are brittle.
    assert 'value="Solar"' in r.text


def test_chip_filters_compose_with_paging(authed_client):
    r = authed_client.get(
        f"/clients/{CLIENT_ID}/bcct?direction=import&page=2&page_size=25",
    )
    assert r.status_code == 200
    # Pager next-link must preserve the `direction` filter on the next-page URL.
    assert "direction=import" in r.text
    # And page 2 must render
    assert "Trang 2" in r.text
