"""Test that parses .ics files from known good repositories."""

import datetime
import zoneinfo
from pathlib import Path
from itertools import islice

import pytest
from syrupy import SnapshotAssertion

from ical.calendar_stream import IcsCalendarStream

TEST_DIR = Path("tests/examples")
TEST_FILES = sorted(list(TEST_DIR.glob("testdata/*.ics")))
TEST_IDS = [x.stem for x in TEST_FILES]


@pytest.mark.parametrize("filename", TEST_FILES, ids=TEST_IDS)
def test_parse(filename: Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open() as ics_file:
        calendar = IcsCalendarStream.calendar_from_ics(ics_file.read())

    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot


@pytest.mark.parametrize("filename", TEST_FILES, ids=TEST_IDS)
def test_iterate_events(filename: Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open() as ics_file:
        calendar = IcsCalendarStream.calendar_from_ics(ics_file.read())

    assert list(islice(iter(calendar.timeline), 5)) == snapshot


def test_recurring_with_single_change() -> None:
    """Test recurring event where one instance has been edited via RECURRENCE-ID."""
    filename = Path("tests/examples/testdata/recurring_with_single_change.ics")
    calendar = IcsCalendarStream.calendar_from_ics(filename.read_text())

    tz = zoneinfo.ZoneInfo("America/New_York")
    timeline = calendar.timeline
    events = list(islice(iter(timeline), 3))

    # Feb 1 - original title
    assert events[0].summary == "Initial Title"
    assert events[0].dtstart == datetime.datetime(2026, 2, 1, 10, 0, tzinfo=tz)

    # Feb 2 - edited instance with RECURRENCE-ID
    assert events[1].summary == "Edited Title"
    assert events[1].recurrence_id == "20260202T100000"
    assert events[1].dtstart == datetime.datetime(2026, 2, 2, 10, 0, tzinfo=tz)

    # Feb 3 - original title
    assert events[2].summary == "Initial Title"
    assert events[2].dtstart == datetime.datetime(2026, 2, 3, 10, 0, tzinfo=tz)
