"""Tests for all compatibility modules."""

import pathlib
import re
from collections.abc import Generator
from unittest.mock import patch

import pytest
from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarParseError
from ical.calendar_stream import CalendarStream, IcsCalendarStream
from ical.store import TodoStore
from ical.compat import enable_compat_mode, timezone_compat

TESTDATA_PATH = pathlib.Path("tests/compat/testdata/")

# Separate test files by type
OFFICE_FILES = list(sorted(TESTDATA_PATH.glob("office_*.ics")))
OFFICE_IDS = [x.stem for x in OFFICE_FILES]

CALENDAR_LABS_FILES = list(sorted(TESTDATA_PATH.glob("calendar_labs_*.ics")))
CALENDAR_LABS_IDS = [x.stem for x in CALENDAR_LABS_FILES]


@pytest.fixture(name="frozen_time", autouse=True)
def mock_frozen_time() -> Generator[FrozenDateTimeFactory, None, None]:
    """Fixture to freeze time to a specific point."""
    with freeze_time("2026-01-03T21:29:07") as freeze:
        with patch("ical.event.dtstamp_factory", new=freeze):
            yield freeze


@pytest.mark.parametrize("filename", OFFICE_FILES, ids=OFFICE_IDS)
def test_make_compat_office(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Test Microsoft Office/Exchange Server compatibility."""
    with filename.open() as ics_file:
        ics = ics_file.read()
        with enable_compat_mode(ics) as compat_ics:
            assert timezone_compat.is_allow_invalid_timezones_enabled()
            assert timezone_compat.is_extended_timezones_enabled()
            calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    new_ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert new_ics == snapshot

    # The output content can be parsed back correctly
    IcsCalendarStream.calendar_from_ics(new_ics)


@pytest.mark.parametrize("filename", CALENDAR_LABS_FILES, ids=CALENDAR_LABS_IDS)
def test_make_compat_calendar_labs(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Test Calendar Labs same-day DTEND compatibility."""
    with filename.open() as ics_file:
        ics = ics_file.read()
        with enable_compat_mode(ics) as compat_ics:
            calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    new_ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert new_ics == snapshot

    # The output content can be parsed back correctly
    IcsCalendarStream.calendar_from_ics(new_ics)


@pytest.mark.parametrize("filename", OFFICE_FILES, ids=OFFICE_IDS)
def test_parse_failure_office(filename: pathlib.Path) -> None:
    """Test that Office files fail parsing without compat mode."""
    with filename.open() as ics_file:
        ics = ics_file.read()
        with pytest.raises(CalendarParseError):
            IcsCalendarStream.calendar_from_ics(ics)


@pytest.mark.parametrize("filename", CALENDAR_LABS_FILES, ids=CALENDAR_LABS_IDS)
def test_parse_success_calendar_labs(filename: pathlib.Path) -> None:
    """Test that Calendar Labs files parse successfully without compat mode.
    
    Calendar Labs same-day DTEND files should parse successfully even without
    compat mode, but will have incorrect DTEND (same as DTSTART).
    """
    with filename.open() as ics_file:
        ics = ics_file.read()
        calendar = IcsCalendarStream.calendar_from_ics(ics)
        assert calendar is not None


@pytest.mark.parametrize(
    "ics",
    [
        "invalid",
        "PRODID:not-exchange",
        "BEGIN:VCALENDAR\nPRODID:not-exchange\nVERSION:2.0\nEND:VCALENDAR",
    ],
)
def test_make_compat_not_enabled(ics: str) -> None:
    """Test to read golden files and verify they are parsed."""
    with enable_compat_mode(ics) as compat_ics:
        assert compat_ics == ics
        assert not timezone_compat.is_allow_invalid_timezones_enabled()
        assert not timezone_compat.is_extended_timezones_enabled()
