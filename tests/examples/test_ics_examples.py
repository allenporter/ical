"""Test that parses .ics files from known good repositories."""

from pathlib import Path

import pytest
from syrupy import SnapshotAssertion

from ical.calendar_stream import IcsCalendarStream

TEST_DIR = Path("tests/examples")


@pytest.mark.parametrize("filename", list(TEST_DIR.glob("testdata/*.ics")))
def test_parse(filename: Path, snapshot: SnapshotAssertion) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open() as ics_file:
        calendar = IcsCalendarStream.calendar_from_ics(ics_file.read())

    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot
