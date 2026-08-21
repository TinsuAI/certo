"""Filter chips tell the truth and compose (#54).

The page's contract is "the filter IS the rule" (#35): the bulk button approves
exactly what the filter selects. That holds only if the controls agree with
each other. Before #54 they did not:

  - every facet chip's count was computed with only the machinery filter
    applied, while its href preserved the active filters — so `?q=X` rendered
    "NB (93)" on a link that delivers 2 rows;
  - chips and the search form each re-declared *some* of the other filters as
    hidden inputs, so clicking a chip to narrow silently dropped `leaf` /
    `min_observed` / `show_machinery` and returned a WIDER set.

The invariant both defects violate: a chip's number is the number of rows you
get by clicking it.
"""
from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app


CLIENT = "_test_filter_state"
USER_ID = "u_filter_state_test"
USER_EMAIL = "filter_state@test.local"
BASE = f"/clients/{CLIENT}/catalog/candidates"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'filter') "
            "on conflict do nothing",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash,"
            " role, status) values (%s, %s, 'F Test', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-pw")),
        )
        cur.execute("delete from hub.catalog_rejections where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        for i, (code, sample) in enumerate([
            ("FS001", "Widget one"),
            ("FS002", "Widget two"),
            ("FS003", "Gadget three"),
        ]):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', 'import', '2026-04-01',
                        %s, %s, '{}'::jsonb)
                """,
                (CLIENT, f"FSTX_{i}", f"FSD{i}", code, sample),
            )
    sess = create_session(USER_ID)
    yield {"session": sess}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.catalog_rejections where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _c(session):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session)
    return c


_CHIP_RE = re.compile(
    r'<a class="chip[^"]*"\s+href="([^"]+)"\s*>\s*(.+?)\s*\((\d+)\)\s*</a>',
    re.S,
)


def _chips(body: str) -> list[tuple[str, str, int]]:
    """(href, label, claimed_count) for every filter chip on the page.

    Hrefs are HTML-unescaped (`&amp;` -> `&`) because that is what a browser
    requests. Skipping this silently drops every param after the first — the
    test then passes by coincidence whenever the counts happen to agree.
    """
    return [(html.unescape(h), lbl.strip(), int(n))
            for h, lbl, n in _CHIP_RE.findall(body)]


def _row_count(body: str) -> int:
    # One selection checkbox per pending row — an unambiguous row marker
    # (the <tr> and the accept button both also carry data-code).
    return body.count('class="row-check"')


def test_every_chip_count_equals_what_clicking_it_delivers(setup):
    """The invariant. A chip advertising N must land on a page showing N rows.

    Checked under an active search, which is what broke it: the counts were
    computed without `q` while the hrefs kept it.
    """
    c = _c(setup["session"])
    body = c.get(f"{BASE}?q=Widget").text
    chips = _chips(body)
    assert chips, "expected filter chips to render"

    for href, label, claimed in chips:
        delivered = _row_count(c.get(href).text)
        assert delivered == claimed, (
            f"chip {label!r} advertises {claimed} but delivers {delivered} "
            f"({href})"
        )


def test_chip_counts_honour_the_rule_bar_too(setup):
    """Same invariant under a rule-bar filter rather than a search."""
    c = _c(setup["session"])
    body = c.get(f"{BASE}?min_observed=99").text          # matches nothing
    for href, label, claimed in _chips(body):
        delivered = _row_count(c.get(href).text)
        assert delivered == claimed, (
            f"chip {label!r} advertises {claimed} but delivers {delivered}"
        )


def test_kind_chip_preserves_the_other_filters(setup):
    """Clicking a chip means 'narrow by kind', not 'discard my other filters'."""
    c = _c(setup["session"])
    body = c.get(f"{BASE}?min_observed=1&show_machinery=1").text
    kind_links = [h for h, _, _ in _chips(body) if "kind=" in h]
    assert kind_links, "expected kind chips to render"
    for href in kind_links:
        assert "min_observed=1" in href, f"chip dropped min_observed: {href}"
        assert "show_machinery=1" in href, f"chip dropped show_machinery: {href}"


def test_search_form_preserves_the_rule_bar_filters(setup):
    """Searching must not silently widen the set by dropping the rule bar."""
    c = _c(setup["session"])
    body = c.get(f"{BASE}?leaf=1&min_observed=2").text
    form = body[body.index('<form method="get" class="search-bar"'):]
    form = form[:form.index("</form>")]
    assert 'name="leaf"' in form, "search form drops leaf"
    assert 'name="min_observed"' in form, "search form drops min_observed"


def test_tat_ca_chip_drops_only_the_kind_facet(setup):
    """«Tất cả» sits in the kind row: it clears kind, not the whole page."""
    c = _c(setup["session"])
    body = c.get(f"{BASE}?kind=unified&leaf=1&q=Widget").text
    tat_ca = [h for h, lbl, _ in _chips(body) if "kind=" not in h]
    assert tat_ca, "expected a «Tất cả» link carrying no kind"
    assert all("leaf=1" in h and "q=Widget" in h for h in tat_ca), (
        "«Tất cả» discarded filters outside the kind facet"
    )


def test_no_chip_click_widens_the_result(setup):
    """The defect end to end: with a filter that matches nothing, every chip
    reachable from the page must still deliver nothing. Before #54 the chips
    dropped `min_observed`, so clicking one to narrow returned all 3 rows.

    Only «Tất cả (0)» renders here — the kind chips correctly stop advertising
    rows that do not exist, which is itself part of the fix.
    """
    c = _c(setup["session"])
    filtered = c.get(f"{BASE}?min_observed=99")           # matches nothing
    assert _row_count(filtered.text) == 0

    chips = _chips(filtered.text)
    assert chips, "expected at least the «Tất cả» chip to render"
    for href, label, _ in chips:
        assert _row_count(c.get(href).text) == 0, (
            f"clicking {label!r} widened the set — min_observed was dropped"
        )
