"""Test that parses .ics files from known good repositories."""

from pathlib import Path

import pytest

from ical.calendar_stream import CalendarStream

TEST_DIR = Path("tests")


@pytest.mark.parametrize("filename", list(TEST_DIR.glob("testdata/ics_examples/*.ics")))
def test_parse(filename: Path) -> None:
    """Test to read golden files and verify they are parsed."""
    with filename.open() as ics_file:
        CalendarStream.from_ics(ics_file.read())
