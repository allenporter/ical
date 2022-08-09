"""Tests for timeline related calendar eents."""

import json

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.calendar_stream import CalendarStream, IcsCalendarStream


@pytest.mark.golden_test("testdata/*.yaml")
def test_parse(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(golden["input"])
    data = json.loads(cal.json(exclude_unset=True, exclude_none=True))
    assert data == golden["output"]

    # Re-parse the data object to verify we get the original data values
    # back. This effectively confirms that all fields can be parsed from the
    # python native format in addition to rfc5545.
    cal_reparsed = CalendarStream.parse_obj(data)
    data_reparsed = json.loads(cal_reparsed.json(exclude_unset=True, exclude_none=True))
    assert data_reparsed == data


@pytest.mark.golden_test("testdata/*.yaml")
def test_serialize(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = IcsCalendarStream.from_ics(golden["input"])
    assert cal.ics() == golden.get("encoded", golden["input"])
