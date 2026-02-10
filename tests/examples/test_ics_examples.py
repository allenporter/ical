"""Test that parses .ics files from known good repositories."""

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
    with filename.open(encoding="utf-8") as ics_file:
        calendar = IcsCalendarStream.calendar_from_ics(ics_file.read())

    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot


@pytest.mark.parametrize("filename", TEST_FILES, ids=TEST_IDS)
def test_iterate_events(filename: Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open(encoding="utf-8") as ics_file:
        calendar = IcsCalendarStream.calendar_from_ics(ics_file.read())

    assert list(islice(iter(calendar.timeline), 5)) == snapshot
