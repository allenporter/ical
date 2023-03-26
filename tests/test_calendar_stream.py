"""Tests for timeline related calendar events."""

from collections.abc import Generator
import json

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.calendar_stream import CalendarStream, IcsCalendarStream


def test_empty_ics(mock_prodid: Generator[None, None, None]) -> None:
    """Test serialization of an empty ics file."""
    calendar = IcsCalendarStream.calendar_from_ics("")
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert (
        ics
        == """BEGIN:VCALENDAR
PRODID:-//example//1.2.3
VERSION:2.0
END:VCALENDAR"""
    )

    calendar.prodid = "-//example//1.2.4"
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert (
        ics
        == """BEGIN:VCALENDAR
PRODID:-//example//1.2.4
VERSION:2.0
END:VCALENDAR"""
    )


@pytest.mark.golden_test("testdata/*.yaml")
def test_parse(golden: GoldenTestFixture, json_encoder: json.JSONEncoder) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(golden["input"])
    data = json.loads(
        cal.json(exclude_unset=True, exclude_none=True, encoder=json_encoder.default)
    )
    assert data == golden.out["output"]

    # Re-parse the data object to verify we get the original data values
    # back. This effectively confirms that all fields can be parsed from the
    # python native format in addition to rfc5545.
    cal_reparsed = CalendarStream.parse_obj(data)
    data_reparsed = json.loads(
        cal_reparsed.json(
            exclude_unset=True, exclude_none=True, encoder=json_encoder.default
        )
    )
    assert data_reparsed == data


@pytest.mark.golden_test("testdata/*.yaml")
def test_serialize(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = IcsCalendarStream.from_ics(golden["input"])
    assert cal.ics() == golden.get("encoded", golden["input"])
