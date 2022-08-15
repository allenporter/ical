"""Tests for the tzif library."""

import datetime

import pytest

from ical.tzif import tz_rule


def test_standard() -> None:
    """Test standard time with no daylight savings time."""
    rule = tz_rule.parse_tz_rule("EST5")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst is None
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_standard_plus_offset() -> None:
    """Test standard time with an offset with an explicit plus."""
    rule = tz_rule.parse_tz_rule("EST+5")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst is None
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_hours_minutes_offset() -> None:
    """Test standard time offset with hours and minutes."""
    rule = tz_rule.parse_tz_rule("EX05:30")
    assert rule.std.name == "EX"
    assert rule.std.offset == datetime.timedelta(hours=-5, minutes=-30)
    assert rule.dst is None
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_hours_minutes_seconds_offset() -> None:
    """Test standard time offset with hours, minutes, and seconds."""
    rule = tz_rule.parse_tz_rule("EX05:30:20")
    assert rule.std.name == "EX"
    assert rule.std.offset == datetime.timedelta(hours=-5, minutes=-30, seconds=-20)
    assert rule.dst is None
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_standard_minus_offset() -> None:
    """Test standard time offset with a negative offset."""
    rule = tz_rule.parse_tz_rule("JST-9")
    assert rule.std.name == "JST"
    assert rule.std.offset == datetime.timedelta(hours=9)
    assert rule.dst is None
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_dst_implicit_offset() -> None:
    """Test daylight savings time with an implicit offset."""
    rule = tz_rule.parse_tz_rule("EST5EDT")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst
    assert rule.dst.name == "EDT"
    assert rule.dst.offset == datetime.timedelta(hours=-4)
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_standard_dst_implied_offset() -> None:
    """Test standard time with an offset with an explicit plus."""
    rule = tz_rule.parse_tz_rule("PST8PDT")
    assert rule.std.name == "PST"
    assert rule.std.offset == datetime.timedelta(hours=-8)
    assert rule.dst
    assert rule.dst.name == "PDT"
    assert rule.dst.offset == datetime.timedelta(hours=-7)
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_dst_explicit_offset() -> None:
    """Test standard time with no daylight savings time."""
    rule = tz_rule.parse_tz_rule("EST5EDT4")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst
    assert rule.dst.name == "EDT"
    assert rule.dst.offset == datetime.timedelta(hours=-4)
    assert rule.dst_start is None
    assert rule.dst_end is None


def test_dst_rules() -> None:
    """Test daylight savings start/end value."""
    rule = tz_rule.parse_tz_rule("EST+5EDT,M3.2.0/2,M11.1.0/2")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst
    assert rule.dst.name == "EDT"
    assert rule.dst.offset == datetime.timedelta(hours=-4)
    assert rule.dst_start
    assert rule.dst_start.month == 3
    assert rule.dst_start.week_of_month == 2
    assert rule.dst_start.day_of_week == 0
    assert rule.dst_start.time == datetime.timedelta(hours=2)
    assert rule.dst_end
    assert rule.dst_end.month == 11
    assert rule.dst_end.week_of_month == 1
    assert rule.dst_end.day_of_week == 0
    assert rule.dst_end.time == datetime.timedelta(hours=2)


def test_dst_implement_time_rules() -> None:
    """Test daylight savings values rules with no explicit time."""
    rule = tz_rule.parse_tz_rule("EST+5EDT,M3.2.0,M11.1.0")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst
    assert rule.dst.name == "EDT"
    assert rule.dst.offset == datetime.timedelta(hours=-4)
    assert rule.dst_start
    assert rule.dst_start.month == 3
    assert rule.dst_start.week_of_month == 2
    assert rule.dst_start.day_of_week == 0
    assert rule.dst_start.time == datetime.timedelta(hours=2)
    assert rule.dst_end
    assert rule.dst_end.month == 11
    assert rule.dst_end.week_of_month == 1
    assert rule.dst_end.day_of_week == 0
    assert rule.dst_end.time == datetime.timedelta(hours=2)


@pytest.mark.parametrize(
    "tz_string",
    [
        "",
        "1234",
        "EST+5EDT,M3.2.0/2",
        "EST+5EDT,M3.2.0/2,M11.1.0/2,M3",
        "EST+5EDT,3.2.0/2,M11.1.0/2",
        "EST+5EDT,M3.2/2,M11.1.0/2",
        "EST+5EDT,M3.2.0.4/2,M11.1.0/2",
    ],
)
def test_invalid(tz_string: str) -> None:
    """Test an invalid rule occurrence"""
    with pytest.raises(ValueError, match="Unable to parse TZ string"):
        tz_rule.parse_tz_rule(tz_string)


def test_tz_offset() -> None:
    """Test standard time offset with hours and minutes."""
    rule = tz_rule.parse_tz_rule("<-03>3<-02>,M3.5.0/-2,M10.5.0/-1")
    assert rule.std.name == "<-03>"
    assert rule.std.offset == datetime.timedelta(hours=-3)
    assert rule.dst
    assert rule.dst.name == "<-02>"
    assert rule.dst.offset == datetime.timedelta(hours=-2)
    assert rule.dst_start
    assert rule.dst_start.month == 3
    assert rule.dst_start.week_of_month == 5
    assert rule.dst_start.day_of_week == 0
    assert rule.dst_start.time == datetime.timedelta(hours=-2)
    assert rule.dst_end
    assert rule.dst_end.month == 10
    assert rule.dst_end.week_of_month == 5
    assert rule.dst_end.day_of_week == 0
    assert rule.dst_end.time == datetime.timedelta(hours=-1)


def test_iran_rule_offset() -> None:
    """Test a more complex timezone rule."""
    rule = tz_rule.parse_tz_rule("<+0330>-3:30<+0430>,J79/24,J263/24")
    assert rule.std.name == "<+0330>"
    assert rule.std.offset == datetime.timedelta(hours=3, minutes=30)
    assert rule.dst
    assert rule.dst.name == "<+0430>"
    assert rule.dst.offset == datetime.timedelta(hours=4, minutes=30)
    assert rule.dst_start
    assert rule.dst_start.day_of_year == 79
    assert rule.dst_start.time == datetime.timedelta(hours=24)
    assert rule.dst_end
    assert rule.dst_end.day_of_year == 263
    assert rule.dst_end.time == datetime.timedelta(hours=24)
