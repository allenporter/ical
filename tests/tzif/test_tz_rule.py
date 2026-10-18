"""Tests for the tzif library."""

import datetime
from typing import cast, Any

import pytest

from ical.tzif import tz_rule

TEST_DATETIME = datetime.datetime(2022, 1, 1)


def expand_rule(test_rule: tz_rule.RuleDate) -> datetime.datetime:
    """Test method to expand a rule to a single value."""
    return next(iter(test_rule.as_rrule(TEST_DATETIME)))


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
    assert isinstance(rule.dst_start, tz_rule.RuleDate)
    assert rule.dst_start.month == 3
    assert rule.dst_start.week_of_month == 2
    assert rule.dst_start.day_of_week == 0
    assert rule.dst_start.time == datetime.timedelta(hours=2)
    assert rule.dst_end
    assert isinstance(rule.dst_end, tz_rule.RuleDate)
    assert rule.dst_end.month == 11
    assert rule.dst_end.week_of_month == 1
    assert rule.dst_end.day_of_week == 0
    assert rule.dst_end.time == datetime.timedelta(hours=2)

    assert next(
        iter(rule.dst_start.as_rrule(datetime.datetime(2022, 1, 1)))
    ) == datetime.datetime(2022, 3, 13, 2, 0, 0)
    assert next(
        iter(rule.dst_end.as_rrule(datetime.datetime(2022, 1, 1)))
    ) == datetime.datetime(2022, 11, 6, 2, 0, 0)

    assert rule.dst_start.rrule_str == "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU"
    assert rule.dst_end.rrule_str == "FREQ=YEARLY;BYMONTH=11;BYDAY=1SU"


def test_dst_implement_time_rules() -> None:
    """Test daylight savings values rules with no explicit time."""
    rule = tz_rule.parse_tz_rule("EST+5EDT,M3.2.0,M11.1.0")
    assert rule.std.name == "EST"
    assert rule.std.offset == datetime.timedelta(hours=-5)
    assert rule.dst
    assert rule.dst.name == "EDT"
    assert rule.dst.offset == datetime.timedelta(hours=-4)
    assert rule.dst_start
    assert isinstance(rule.dst_start, tz_rule.RuleDate)
    assert rule.dst_start.month == 3
    assert rule.dst_start.week_of_month == 2
    assert rule.dst_start.day_of_week == 0
    assert rule.dst_start.time == datetime.timedelta(hours=2)
    assert rule.dst_end
    assert isinstance(rule.dst_end, tz_rule.RuleDate)
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
    assert isinstance(rule.dst_start, tz_rule.RuleDate)
    assert rule.dst_start.month == 3
    assert rule.dst_start.week_of_month == 5
    assert rule.dst_start.day_of_week == 0
    assert rule.dst_start.time == datetime.timedelta(hours=-2)
    assert rule.dst_end
    assert isinstance(rule.dst_end, tz_rule.RuleDate)
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
    assert isinstance(rule.dst_start, tz_rule.RuleDay)
    assert rule.dst_start.day_of_year == 79
    assert rule.dst_start.time == datetime.timedelta(hours=24)
    assert rule.dst_end
    assert isinstance(rule.dst_end, tz_rule.RuleDay)
    assert rule.dst_end.day_of_year == 263
    assert rule.dst_end.time == datetime.timedelta(hours=24)


def test_parse_tz_rule_benchmark(benchmark: Any) -> None:
    """Benchmark to measure the speed of parsing."""

    def parse() -> None:
        tz_rule.parse_tz_rule("EST5")
        tz_rule.parse_tz_rule("EST+5EDT,M3.2.0,M11.1.0")
        tz_rule.parse_tz_rule("<-03>3<-02>,M3.5.0/-2,M10.5.0/-1")

    benchmark(parse)


def test_explicit_zero_dst_offset_dublin() -> None:
    """Test explicit 0 DST offset (Europe/Dublin) is not overwritten."""
    rule = tz_rule.parse_tz_rule("IST-1GMT0,M10.5.0,M3.5.0/1")
    assert rule.std.name == "I" + "ST"
    assert rule.std.offset == datetime.timedelta(hours=1)
    assert rule.dst is not None
    assert rule.dst.name == "GMT"
    assert rule.dst.offset == datetime.timedelta(hours=0)


def test_zero_transition_time_azores() -> None:
    """Test /0 transition time and implicit 0 DST offset (Atlantic/Azores)."""
    rule = tz_rule.parse_tz_rule("<-01>1<+00>,M3.5.0/0,M10.5.0/1")
    assert rule.std.offset == datetime.timedelta(hours=-1)
    assert rule.dst is not None
    assert rule.dst.offset == datetime.timedelta(hours=0)
    assert isinstance(rule.dst_start, tz_rule.RuleDate)
    assert rule.dst_start.time == datetime.timedelta(hours=0)
    assert isinstance(rule.dst_end, tz_rule.RuleDate)
    assert rule.dst_end.time == datetime.timedelta(hours=1)


def test_rule_date_time_outside_0_to_24h() -> None:
    """Test RuleDate.as_rrule, rrule_dtstart, and rrule_str when time is < 0 or >= 24h."""
    # Asia/Jerusalem: M3.4.4/26 (Friday 02:00 after 4th Thursday of March)
    jerusalem = tz_rule.parse_tz_rule("IST-2IDT,M3.4.4/26,M10.5.0")
    assert isinstance(jerusalem.dst_start, tz_rule.RuleDate)
    # In 2022, 4th Thursday of March is March 24 -> +26h is Friday March 25 02:00
    assert jerusalem.dst_start.rrule_dtstart(
        datetime.datetime(2022, 1, 1)
    ) == datetime.datetime(2022, 3, 25, 2, 0)
    # In 2024, March 1 is Friday, 4th Thursday is March 28 -> +26h is Friday March 29 02:00
    assert jerusalem.dst_start.rrule_dtstart(
        datetime.datetime(2024, 1, 1)
    ) == datetime.datetime(2024, 3, 29, 2, 0)
    assert (
        jerusalem.dst_start.rrule_str
        == "FREQ=YEARLY;BYMONTH=3;BYDAY=FR;BYMONTHDAY=23,24,25,26,27,28,29"
    )

    # America/Nuuk: M3.5.0/-2 (Saturday 22:00 before last Sunday of March)
    nuuk = tz_rule.parse_tz_rule("<-03>3<-02>,M3.5.0/-2,M10.5.0/-1")
    assert isinstance(nuuk.dst_start, tz_rule.RuleDate)
    # In 2022, last Sunday of March is March 27 -> -2h is Saturday March 26 22:00
    assert nuuk.dst_start.rrule_dtstart(
        datetime.datetime(2022, 1, 1)
    ) == datetime.datetime(2022, 3, 26, 22, 0)
    assert (
        nuuk.dst_start.rrule_str
        == "FREQ=YEARLY;BYMONTH=3;BYDAY=SA;BYMONTHDAY=-8,-7,-6,-5,-4,-3,-2"
    )
