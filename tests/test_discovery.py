"""Unit tests for discovery.py — date parsing and notebook filtering."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from notebooklm_automation.discovery import filter_todays_notebooks, parse_creation_date
from notebooklm_automation.models import Notebook


# --- parse_creation_date ---


class TestParseCreationDate:
    """Tests for parse_creation_date covering all known NotebookLM formats."""

    def test_today(self):
        assert parse_creation_date("Today") == date.today()

    def test_today_case_insensitive(self):
        assert parse_creation_date("today") == date.today()
        assert parse_creation_date("TODAY") == date.today()

    def test_yesterday(self):
        assert parse_creation_date("Yesterday") == date.today() - timedelta(days=1)

    def test_yesterday_case_insensitive(self):
        assert parse_creation_date("yesterday") == date.today() - timedelta(days=1)

    def test_abbreviated_month(self):
        assert parse_creation_date("Jun 28, 2025") == date(2025, 6, 28)

    def test_full_month_name(self):
        assert parse_creation_date("June 28, 2025") == date(2025, 6, 28)

    def test_january_abbreviated(self):
        assert parse_creation_date("Jan 1, 2025") == date(2025, 1, 1)

    def test_december_full(self):
        assert parse_creation_date("December 31, 2024") == date(2024, 12, 31)

    def test_whitespace_stripped(self):
        assert parse_creation_date("  Jun 28, 2025  ") == date(2025, 6, 28)
        assert parse_creation_date("  Today  ") == date.today()

    def test_empty_string_returns_none(self):
        assert parse_creation_date("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_creation_date("   ") is None

    def test_garbage_returns_none(self):
        assert parse_creation_date("not a date") is None

    def test_numeric_format_returns_none(self):
        assert parse_creation_date("2025-06-28") is None

    def test_partial_date_returns_none(self):
        assert parse_creation_date("Jun 2025") is None

    def test_unparseable_logs_warning(self, caplog):
        with caplog.at_level("WARNING"):
            result = parse_creation_date("bogus date")
        assert result is None
        assert "Could not parse creation date" in caplog.text


# --- filter_todays_notebooks ---


def _make_notebook(title: str, creation_date: date) -> Notebook:
    return Notebook(title=title, creation_date=creation_date, element_locator=f"#{title}")


class TestFilterTodaysNotebooks:
    """Tests for filter_todays_notebooks."""

    def test_returns_only_todays(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        notebooks = [
            _make_notebook("A", today),
            _make_notebook("B", yesterday),
            _make_notebook("C", today),
        ]
        result = filter_todays_notebooks(notebooks)
        assert len(result) == 2
        assert all(nb.creation_date == today for nb in result)
        assert {nb.title for nb in result} == {"A", "C"}

    def test_empty_list(self):
        assert filter_todays_notebooks([]) == []

    def test_none_match(self):
        old = date(2020, 1, 1)
        notebooks = [_make_notebook("X", old)]
        assert filter_todays_notebooks(notebooks) == []

    def test_all_match(self):
        today = date.today()
        notebooks = [_make_notebook("A", today), _make_notebook("B", today)]
        result = filter_todays_notebooks(notebooks)
        assert len(result) == 2

    def test_preserves_order(self):
        today = date.today()
        notebooks = [
            _make_notebook("First", today),
            _make_notebook("Second", date(2020, 1, 1)),
            _make_notebook("Third", today),
        ]
        result = filter_todays_notebooks(notebooks)
        assert [nb.title for nb in result] == ["First", "Third"]
