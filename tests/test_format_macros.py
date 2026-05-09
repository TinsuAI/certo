"""Tests for shared formatting macros in app/templates/_format.html.

Macros render numbers, money, and dates with optional locale support.
We render the macros directly via Jinja2 Environment to avoid pulling
in the full FastAPI stack."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


@pytest.fixture
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
        keep_trailing_newline=False,
    )


def _render(env, expr: str, **ctx) -> str:
    tpl = env.from_string(
        '{% from "_format.html" import format_number, format_money, format_date, format_int %}'
        + expr,
    )
    return tpl.render(**ctx).strip()


def test_format_number_en_locale(env):
    assert _render(env, "{{ format_number(1234567.89, decimals=2, lang='en') }}") \
        == "1,234,567.89"


def test_format_number_vi_locale(env):
    assert _render(env, "{{ format_number(1234567.89, decimals=2, lang='vi') }}") \
        == "1.234.567,89"


def test_format_number_zero_decimals(env):
    assert _render(env, "{{ format_number(12480972000, decimals=0, lang='vi') }}") \
        == "12.480.972.000"


def test_format_number_handles_none(env):
    assert _render(env, "[{{ format_number(None) }}]") == "[]"


def test_format_number_handles_empty_string(env):
    assert _render(env, "[{{ format_number('') }}]") == "[]"


def test_format_money_renders_amount_and_currency(env):
    out = _render(
        env,
        "{{ format_money(478800, 'USD', decimals=2, lang='vi') }}",
    )
    assert "478.800,00" in out
    assert "USD" in out


def test_format_money_renders_vnd_no_decimals(env):
    out = _render(
        env,
        "{{ format_money(12480972000, 'VND', decimals=0, lang='vi') }}",
    )
    assert "12.480.972.000" in out
    assert "VND" in out


def test_format_money_handles_none(env):
    out = _render(env, "[{{ format_money(None, 'USD') }}]")
    assert out == "[]"


def test_format_money_no_currency_renders_just_number(env):
    out = _render(
        env,
        "{{ format_money(100, None, decimals=0, lang='en') }}",
    )
    # Should render the number but no currency span
    assert "100" in out
    assert "USD" not in out and "VND" not in out


def test_format_date_iso(env):
    out = _render(env, "{{ format_date(d) }}", d=date(2026, 5, 8))
    assert out == "2026-05-08"


def test_format_date_handles_none(env):
    out = _render(env, "[{{ format_date(None) }}]")
    assert out == "[]"


def test_format_int_alias(env):
    out = _render(env, "{{ format_int(1234567, lang='vi') }}")
    assert out == "1.234.567"
