"""Tests for all compatibility modules."""

import pathlib

import pytest
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarParseError
from ical.calendar_stream import CalendarStream, IcsCalendarStream
from ical.store import TodoStore
from ical.compat import enable_compat_mode, timezone_compat

TESTDATA_PATH = pathlib.Path("tests/compat/testdata/")
TESTDATA_FILES = list(sorted(TESTDATA_PATH.glob("*.ics")))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_make_compat(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open(encoding="utf-8") as ics_file:
        ics = ics_file.read()
        with enable_compat_mode(ics) as compat_ics:
            assert timezone_compat.is_allow_invalid_timezones_enabled()
            assert timezone_compat.is_extended_timezones_enabled()
            calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    new_ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert new_ics == snapshot

    # The output content can be parsed back correctly
    IcsCalendarStream.calendar_from_ics(new_ics)


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse_failure(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open() as ics_file:
        ics = ics_file.read()
        with pytest.raises(CalendarParseError):
            IcsCalendarStream.calendar_from_ics(ics)


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
