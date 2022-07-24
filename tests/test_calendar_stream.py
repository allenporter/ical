"""Tests for timeline related calendar eents."""

import json

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.calendar_stream import CalendarStream, IcsCalendarStream


@pytest.mark.golden_test("testdata/calendar_stream/*.yaml")
def test_parse(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(golden["input"])
    data = json.loads(cal.json(exclude_unset=True))
    assert data == golden["output"]


@pytest.mark.golden_test("testdata/calendar_stream/*.yaml")
def test_serialize(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = IcsCalendarStream.from_ics(golden["input"])
    assert cal.ics() == golden.get("encoded", golden["input"])
