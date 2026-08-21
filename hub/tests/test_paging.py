"""Pagination param parsing + sort whitelist + link builder.

The shared module `_paging` accepts raw query-string values, returns a
`PageParams` value with normalized integers + a sanitized SQL sort
clause keyed off a per-view whitelist. This is the only place where
sort fragments touch column names — every list view must declare its
whitelist explicitly.
"""
from __future__ import annotations

import pytest

from app.routes._paging import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PAGE_SIZE_CHOICES,
    PageParams,
    SortSpec,
    build_link,
    parse_page_params,
)


class TestParsePageParams:

    def test_defaults_when_all_missing(self):
        p = parse_page_params(query_params={})
        assert p.page == 1
        assert p.page_size == DEFAULT_PAGE_SIZE == 50
        assert p.offset == 0

    def test_page_clamped_to_min_1(self):
        p = parse_page_params(query_params={"page": "0"})
        assert p.page == 1
        p = parse_page_params(query_params={"page": "-5"})
        assert p.page == 1
        p = parse_page_params(query_params={"page": "abc"})
        assert p.page == 1

    def test_page_size_clamped_to_max(self):
        p = parse_page_params(query_params={"page_size": "9999"})
        assert p.page_size == MAX_PAGE_SIZE == 200

    def test_page_size_must_be_positive(self):
        p = parse_page_params(query_params={"page_size": "0"})
        assert p.page_size == DEFAULT_PAGE_SIZE
        p = parse_page_params(query_params={"page_size": "-10"})
        assert p.page_size == DEFAULT_PAGE_SIZE

    def test_offset_computed_from_page(self):
        p = parse_page_params(query_params={"page": "3", "page_size": "25"})
        assert p.offset == 50

    def test_page_size_choices_exposed(self):
        assert 50 in PAGE_SIZE_CHOICES
        assert PAGE_SIZE_CHOICES == (25, 50, 100, 200)


class TestSortSpec:

    WL = {
        "registration_date": "b.registration_date",
        "declaration_no": "b.declaration_no",
        "customs_code": "b.customs_code",
    }
    DEFAULT = ("registration_date", "desc")

    def test_default_when_no_param(self):
        s = SortSpec.from_params(
            query_params={}, whitelist=self.WL, default=self.DEFAULT,
        )
        assert s.column == "registration_date"
        assert s.direction == "desc"
        assert s.sql_clause(tiebreakers=("b.declaration_no", "b.line_no")) == \
            "b.registration_date desc nulls last, b.declaration_no, b.line_no"

    def test_unknown_column_falls_back_to_default(self):
        s = SortSpec.from_params(
            query_params={"sort": "ssn", "dir": "asc"},
            whitelist=self.WL, default=self.DEFAULT,
        )
        assert s.column == "registration_date"
        assert s.direction == "desc"

    def test_unknown_dir_falls_back_to_asc(self):
        s = SortSpec.from_params(
            query_params={"sort": "customs_code", "dir": "sideways"},
            whitelist=self.WL, default=self.DEFAULT,
        )
        assert s.column == "customs_code"
        assert s.direction == "asc"

    def test_asc_sql_no_nulls_last(self):
        s = SortSpec.from_params(
            query_params={"sort": "customs_code", "dir": "asc"},
            whitelist=self.WL, default=self.DEFAULT,
        )
        assert s.sql_clause() == "b.customs_code asc"

    def test_desc_sql_includes_nulls_last(self):
        s = SortSpec.from_params(
            query_params={"sort": "customs_code", "dir": "desc"},
            whitelist=self.WL, default=self.DEFAULT,
        )
        assert s.sql_clause() == "b.customs_code desc nulls last"


class TestBuildLink:

    def test_preserves_other_params(self):
        url = build_link(
            base_path="/clients/g/bcct",
            current={"q": "abc", "direction": "import", "page": "1"},
            override={"page": "2"},
        )
        assert "page=2" in url
        assert "q=abc" in url
        assert "direction=import" in url

    def test_drops_param_set_to_none(self):
        url = build_link(
            base_path="/clients/g/bcct",
            current={"q": "abc", "direction": "import"},
            override={"direction": None},
        )
        assert "direction" not in url
        assert "q=abc" in url

    def test_no_query_string_when_empty(self):
        url = build_link(
            base_path="/clients/g/bcct", current={}, override={},
        )
        assert url == "/clients/g/bcct"

    def test_url_encoded_search_value(self):
        url = build_link(
            base_path="/clients/g/bcct",
            current={"q": "a b&c"},
            override={},
        )
        assert "q=a+b%26c" in url or "q=a%20b%26c" in url


class TestPageParamsTotalPages:

    def test_zero_total(self):
        p = PageParams(page=1, page_size=50)
        assert p.total_pages(0) == 0

    def test_exact_page_size(self):
        p = PageParams(page=1, page_size=50)
        assert p.total_pages(100) == 2

    def test_remainder(self):
        p = PageParams(page=1, page_size=50)
        assert p.total_pages(101) == 3

    def test_first_last_helpers(self):
        p = PageParams(page=3, page_size=25)
        assert p.has_prev() is True
        assert p.has_next(total=200) is True
        assert p.has_next(total=75) is False  # 75/25 = 3 pages, on page 3
