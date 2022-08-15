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


def test_daylight_savings() -> None:
    """Test daylight savings value."""
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
    assert rule.dst_start.time == datetime.time(2, 0, 0)
    assert rule.dst_end
    assert rule.dst_end.month == 11
    assert rule.dst_end.week_of_month == 1
    assert rule.dst_end.day_of_week == 0
    assert rule.dst_end.time == datetime.time(2, 0, 0)


def test_invalid() -> None:
    """Test an invalid rule occurrence"""
    with pytest.raises(ValueError):
        tz_rule.parse_tz_rule("1234")
