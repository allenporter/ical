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
    with filename.open() as ics_file:
        ics = ics_file.read()
        with enable_compat_mode(ics) as compat_ics:
            # Only check timezone compatibility for Exchange Server files
            if "office_3" in filename.stem:
                assert timezone_compat.is_allow_invalid_timezones_enabled()
                assert timezone_compat.is_extended_timezones_enabled()
            calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    new_ics = IcsCalendarStream.calendar_to_ics(calendar)
    
    # Normalize DTSTAMP for calendar_labs files since it's auto-generated
    if "calendar_labs" in filename.stem:
        import re
        new_ics = re.sub(r'DTSTAMP:\d{8}T\d{6}Z', 'DTSTAMP:20260103T212907Z', new_ics)
    
    assert new_ics == snapshot

    # The output content can be parsed back correctly
    IcsCalendarStream.calendar_from_ics(new_ics)


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse_failure(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they fail parsing without compat mode."""
    with filename.open() as ics_file:
        ics = ics_file.read()
        # Calendar Labs same-day DTEND files should now parse successfully
        # since we enabled same-day DTEND compat globally
        if "calendar_labs" in filename.stem:
            # This should now parse successfully
            calendar = IcsCalendarStream.calendar_from_ics(ics)
            assert calendar is not None
        else:
            # Other files should still fail without compat mode
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
