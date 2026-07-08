"""Tests for Journal component."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import patch

import pytest

from ical.exceptions import CalendarParseError
from ical.journal import Journal, JournalStatus
from ical.timespan import Timespan
from ical.types import Period, Uri, Image
from ical.recur_adapter import merge_and_expand_items
from ical.calendar_stream import IcsCalendarStream
from pathlib import Path


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
    journal = Journal.model_validate({"status": "DRAFT"})
    assert journal.status == JournalStatus.DRAFT

    with pytest.raises(
        CalendarParseError,
        match="^Failed to parse calendar JOURNAL component: Input should be 'DRAFT', 'FINAL' or 'CANCELLED'$",
    ):
        Journal.model_validate({"status": "invalid-status"})


def test_start_datetime() -> None:
    """Test journal start date conversions."""

    journal = Journal(start=datetime.date(2022, 8, 7))
    assert journal.start
    assert journal.start.isoformat() == "2022-08-07"

    with (
        patch(
            "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
        ),
        patch(
            "ical.journal.local_timezone",
            return_value=zoneinfo.ZoneInfo("America/Regina"),
        ),
    ):
        assert journal.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"
        assert not journal.recurring

        ts = journal.timespan
        assert ts
        assert ts.start.isoformat() == "2022-08-07T00:00:00-06:00"
        assert ts.end.isoformat() == "2022-08-08T00:00:00-06:00"


def test_computed_duration_date() -> None:
    """Test computed duration for a date."""

    journal = Journal(
        start=datetime.date(
            2022,
            8,
            7,
        )
    )
    assert journal.start
    assert journal.computed_duration == datetime.timedelta(days=1)


def test_computed_duration_datetime() -> None:
    """Test computed duration for a datetime."""

    journal = Journal(start=datetime.datetime(2022, 8, 7, 0, 0, 0))
    assert journal.start
    assert journal.computed_duration == datetime.timedelta(hours=1)


def test_journal_recurrence_expansion_period() -> None:
    """Test that journal recurrence expansion works with periods."""
    journal = Journal(
        summary="Test Journal",
        dtstart=datetime.datetime(2022, 8, 7, 9, 0, 0),
        rdate=[
            Period(
                start=datetime.datetime(2022, 8, 8, 10, 0, 0),
                end=datetime.datetime(2022, 8, 8, 12, 0, 0),
            )
        ],
    )

    journals = [
        item.item for item in merge_and_expand_items([journal], datetime.timezone.utc)
    ]
    assert len(journals) == 1

    assert journals[0].dtstart == datetime.datetime(2022, 8, 8, 10, 0, 0)


def test_rfc7986_journal_properties() -> None:
    """Test parsing and serialization of journal-level RFC 7986 properties."""
    ics_path = (
        Path(__file__).parent / "parsing/testdata/valid/params_rfc7986_component.ics"
    )
    calendar = IcsCalendarStream.calendar_from_ics(ics_path.read_text())

    assert len(calendar.journal) == 1
    journal = calendar.journal[0]
    assert journal.color == "green"
    assert len(journal.image) == 1
    assert journal.image[0].uri == Uri("http://example.com/journal.jpg")
    assert journal.image[0].display == "BADGE"

    # Verify serialization
    output_ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert "COLOR:green" in output_ics
    assert "IMAGE;DISPLAY=BADGE:http://example.com/journal.jpg" in output_ics
