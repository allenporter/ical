"""Tests for non-conforming duration string compatibility layer."""

import datetime
import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import duration_compat, enable_compat_mode
from ical.exceptions import CalendarParseError
from ical.parsing.property import ParsedProperty
from ical.types.duration import DurationEncoder

INVALID_DURATION_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//EN
VERSION:2.0
BEGIN:VEVENT
UID:test-duration-p1h
DTSTART:20260805T100000Z
DURATION:P1H
SUMMARY:Event with non-standard duration
END:VEVENT
END:VCALENDAR"""


def test_duration_missing_t_parsing_fail() -> None:
    """Test that parsing fails in strict mode for DURATION missing T separator."""
    with pytest.raises(
        CalendarParseError,
        match=r"Expected value to match DURATION pattern: P1H",
    ):
        IcsCalendarStream.calendar_from_ics(INVALID_DURATION_ICS)


def test_duration_missing_t_parsing_compat_mode() -> None:
    """Test that parsing succeeds in compat mode for DURATION missing T separator."""
    with enable_compat_mode(INVALID_DURATION_ICS) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.duration == datetime.timedelta(hours=1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("P1H", datetime.timedelta(hours=1)),
        ("P30M", datetime.timedelta(minutes=30)),
        ("P45S", datetime.timedelta(seconds=45)),
        ("P1H30M", datetime.timedelta(hours=1, minutes=30)),
        ("P1D2H30M", datetime.timedelta(days=1, hours=2, minutes=30)),
        ("-P15M", datetime.timedelta(minutes=-15)),
    ],
)
def test_duration_direct_compat(value: str, expected: datetime.timedelta) -> None:
    """Test that parsing non-conforming durations directly succeeds when duration_compat is enabled."""
    # Fails in strict mode
    with pytest.raises(ValueError, match="Expected value to match DURATION pattern"):
        DurationEncoder.__parse_property_value__(
            ParsedProperty(name="DURATION", value=value)
        )

    # Succeeds with compat manager
    with duration_compat.enable_duration_compat():
        result = DurationEncoder.__parse_property_value__(
            ParsedProperty(name="DURATION", value=value)
        )
        assert result == expected
