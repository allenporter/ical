"""Tests for Journal component."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import patch

import pytest

from ical.exceptions import CalendarParseError
from ical.journal import Journal, JournalStatus


def test_empty() -> None:
    """Test that in practice a Journal requires no fields."""
    journal = Journal()
    assert not journal.summary


def test_journal() -> None:
    """Test a valid Journal object."""
    journal = Journal(summary="Example")
    assert journal.summary == "Example"


def test_status() -> None:
    """Test Journal status."""
    journal = Journal.parse_obj({"status": "DRAFT"})
    assert journal.status == JournalStatus.DRAFT

    with pytest.raises(CalendarParseError):
        Journal.parse_obj({"status": "invalid-status"})


def test_start_datetime() -> None:
    """Test journal start date conversions."""

    journal = Journal(start=datetime.date(2022, 8, 7))
    assert journal.start

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        assert journal.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"
