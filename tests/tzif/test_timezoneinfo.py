"""Tests for the tzif library."""

import datetime
import zoneinfo

import pytest

from ical.tzif import timezoneinfo, tz_rule


def test_invalid_zoneinfo() -> None:
    """Verify exception handling for an invalid timezone."""

    with pytest.raises(timezoneinfo.TimezoneInfoError, match="Unable to find timezone"):
        timezoneinfo.read("invalid")


@pytest.mark.parametrize(
    "key,dtstarts,expected_tzname,expected_offset",
    [
        (
            "America/Los_Angeles",
            [
                datetime.datetime(2021, 3, 14, 1, 59, 0),
                datetime.datetime(2021, 11, 7, 2, 0, 0),
                datetime.datetime(2022, 3, 13, 1, 59, 0),
                datetime.datetime(2022, 11, 6, 2, 0, 0),
                datetime.datetime(2023, 3, 12, 1, 59, 0),
                datetime.datetime(2023, 11, 5, 2, 0, 0),
            ],
            "PST",
            datetime.timedelta(hours=-8),
        ),
        (
            "America/Los_Angeles",
            [
                datetime.datetime(2021, 3, 14, 2, 0, 0),
                datetime.datetime(2021, 11, 7, 1, 59, 0),
                datetime.datetime(2022, 3, 13, 2, 0, 0),
                datetime.datetime(2022, 11, 6, 1, 59, 0),
                datetime.datetime(2023, 3, 12, 2, 0, 0),
                datetime.datetime(2023, 11, 5, 1, 59, 0),
            ],
            "PDT",
            datetime.timedelta(hours=-7),
        ),
        (
            "Europe/Warsaw",
            [
                datetime.datetime(2021, 3, 28, 1, 59, 0),
                datetime.datetime(2021, 10, 31, 3, 0, 0),
                datetime.datetime(2022, 3, 27, 1, 59, 0),
                datetime.datetime(2022, 10, 30, 3, 0, 0),
                datetime.datetime(2023, 3, 26, 1, 59, 0),
                datetime.datetime(2023, 10, 29, 3, 0, 0),
                datetime.datetime(2024, 3, 31, 1, 59, 0),
                datetime.datetime(2024, 10, 27, 3, 0, 0),
            ],
            "CET",
            datetime.timedelta(hours=1),
        ),
        (
            "Europe/Warsaw",
            [
                datetime.datetime(2021, 3, 28, 2, 0, 0),
                datetime.datetime(2021, 10, 31, 2, 59, 0),
                datetime.datetime(2022, 3, 27, 2, 0, 0),
                datetime.datetime(2022, 10, 30, 2, 59, 0),
                datetime.datetime(2023, 3, 26, 2, 0, 0),
                datetime.datetime(2023, 10, 29, 2, 59, 0),
                datetime.datetime(2024, 3, 31, 2, 0, 0),
                datetime.datetime(2024, 10, 27, 2, 59, 0),
            ],
            "CEST",
            datetime.timedelta(hours=2),
        ),
        (
            "Asia/Tokyo",
            [
                # Fixed offset anytime of year
                datetime.datetime(2021, 1, 1, 0, 0, 0),
                datetime.datetime(2022, 3, 1, 0, 0, 0),
                datetime.datetime(2022, 6, 1, 0, 0, 0),
                datetime.datetime(2023, 7, 1, 0, 0, 0),
                datetime.datetime(2023, 12, 1, 0, 0, 0),
            ],
            "JST",
            datetime.timedelta(hours=9),
        ),
        (
            "America/St_Thomas",
            [
                # Fixed offset anytime of year
                datetime.datetime(2021, 1, 1, 0, 0, 0),
                datetime.datetime(2022, 3, 1, 0, 0, 0),
                datetime.datetime(2022, 6, 1, 0, 0, 0),
                datetime.datetime(2023, 7, 1, 0, 0, 0),
                datetime.datetime(2023, 12, 1, 0, 0, 0),
            ],
            "AST",
            datetime.timedelta(hours=-4),
        ),
    ],
)
def test_tzinfo(
    key: str,
    dtstarts: list[datetime.datetime],
    expected_tzname: str,
    expected_offset: datetime.timedelta,
) -> None:
    """Test TzInfo implementation for known date/times."""
    result = timezoneinfo.read(key)
    tz_info = timezoneinfo.TzInfo.from_timezoneinfo(result)
    for dtstart in dtstarts:
        value = dtstart.replace(tzinfo=tz_info)
        assert tz_info.tzname(value) == expected_tzname, f"For {dtstart}"
        assert tz_info.utcoffset(value) == expected_offset, f"For {dtstart}"

    assert not tz_info.utcoffset(None)
    assert not tz_info.tzname(None)
    assert not tz_info.dst(None)


def test_rrule_str() -> None:
    """Test rule implementations for std and dst."""
    result = timezoneinfo.read("America/New_York")
    assert result.rule
    assert result.rule.dst_start
    assert isinstance(result.rule.dst_start, tz_rule.RuleDate)
    assert result.rule.dst_start.rrule_str == "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU"
    assert result.rule.dst_end
    assert isinstance(result.rule.dst_end, tz_rule.RuleDate)
    assert result.rule.dst_end.rrule_str == "FREQ=YEARLY;BYMONTH=11;BYDAY=1SU"


@pytest.mark.parametrize("key", zoneinfo.available_timezones())
def test_all_zoneinfo(key: str) -> None:
    """Verify that all available timezones in the system have valid tzdata."""
    if key.startswith("System") or key == "localtime":
        return

    result = timezoneinfo.read(key)
    assert result.rule

    # Iran uses julian dates, not yet supported. Iran TZ rules have changed
    # such that it no longer observes DST anyway
    if key in ("Asia/Tehran", "Iran"):
        assert isinstance(result.rule.dst_start, tz_rule.RuleDay)
        assert isinstance(result.rule.dst_end, tz_rule.RuleDay)
        return

    if result.rule.dst_start:
        assert result.rule.dst_end
        assert isinstance(result.rule.dst_start, tz_rule.RuleDate)
        assert isinstance(result.rule.dst_end, tz_rule.RuleDate)
        # Verify a rule can be constructed
        assert next(iter(result.rule.dst_start.as_rrule()))
        assert next(iter(result.rule.dst_end.as_rrule()))
    else:
        # Fixed offset
        assert result.rule
        assert result.rule.std
        assert result.rule.std.name
        assert not result.rule.dst

    # Verify there is a paresable tz rule
    timezoneinfo.TzInfo.from_timezoneinfo(result)
