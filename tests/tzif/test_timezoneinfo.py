"""Tests for the tzif library."""

import datetime
from typing import Any
from unittest.mock import patch
import zoneinfo

import pytest


from ical.tzif import timezoneinfo, tz_rule


IGNORED_TIMEZONES = {
    "Asia/Hanoi",  # Not in tzdata
}


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
        (
            "Pacific/Auckland",
            [
                # NZST (standard time, April-September)
                datetime.datetime(2025, 7, 1, 9, 0, 0),
                datetime.datetime(2025, 4, 7, 9, 0, 0),
            ],
            "NZST",
            datetime.timedelta(hours=12),
        ),
        (
            "Pacific/Auckland",
            [
                # NZDT (daylight time, September-April)
                datetime.datetime(2025, 10, 8, 9, 0, 0),
                datetime.datetime(2025, 12, 8, 15, 0, 0),
                datetime.datetime(2026, 2, 1, 9, 0, 0),
            ],
            "NZDT",
            datetime.timedelta(hours=13),
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
    tz_info = timezoneinfo.read_tzinfo(key)
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
    if key.startswith("System") or key == "localtime" or key in IGNORED_TIMEZONES:
        return

    result = timezoneinfo.read(key)
    assert result.rule

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


def test_read_tzinfo_value_error() -> None:
    """Test TzInfo implementation for known date/times."""
    with (
        patch("ical.tzif.timezoneinfo._read_tzdata_timezones", return_value=["X/Y"]),
        patch("ical.tzif.timezoneinfo._find_tzfile"),
        patch(
            "ical.tzif.timezoneinfo.read_tzif",
            side_effect=ValueError("zoneinfo file did not contain magic header"),
        ),
        pytest.raises(
            timezoneinfo.TimezoneInfoError, match="Unable to load tzdata file: X/Y"
        ),
    ):
        timezoneinfo.read_tzinfo("X/Y")


def test_dst_caches_transitions_per_year() -> None:
    """TzInfo.dst() should compute year transitions at most once per year.

    Direct unit-level guard on the cache: with the as_rrule() helper
    spied on, calling dst() many times across only two distinct years
    must trigger at most two rrule constructions per transition rule
    (one for dst_start, one for dst_end), regardless of the number of
    dst() calls.
    """
    tz = timezoneinfo.read_tzinfo("America/Los_Angeles")

    original_as_rrule = tz_rule.RuleDate.as_rrule
    call_count = 0

    def counting_as_rrule(self, dtstart=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return original_as_rrule(self, dtstart)

    with patch.object(tz_rule.RuleDate, "as_rrule", counting_as_rrule):
        # Hammer dst() with many datetimes in only two distinct years.
        for _ in range(1000):
            tz.dst(datetime.datetime(2024, 3, 15, 12, 0, 0))
            tz.dst(datetime.datetime(2024, 11, 15, 12, 0, 0))
            tz.dst(datetime.datetime(2025, 3, 15, 12, 0, 0))
            tz.dst(datetime.datetime(2025, 11, 15, 12, 0, 0))

    # Two distinct years * two transition rules (dst_start + dst_end) = 4.
    assert call_count <= 4, (
        f"RuleDate.as_rrule called {call_count} times; expected <= 4 "
        "(once per (year, transition)). The per-year cache in "
        "TzInfo.dst() appears to be broken, which causes severe "
        "performance regressions for large calendars."
    )


@pytest.mark.benchmark(min_rounds=1, warmup=False)
def test_benchmark_dst_repeated_calls(benchmark: Any) -> None:
    """Benchmark TzInfo.dst() across repeated calls within the same year.

    With the per-year cache in place, ``dst()`` should be effectively
    O(1) after the first call for a given year. Without it, every call
    rebuilt two ``dateutil.rrule.rrule`` instances. This benchmark
    exercises the hot path and is intended to surface regressions in
    the cache.
    """
    tz = timezoneinfo.read_tzinfo("America/Los_Angeles")
    # Pre-generate a list of datetimes spanning two years so the cache
    # is exercised but year transitions are amortized.
    dts = [
        datetime.datetime(2024 + (i % 2), 1 + (i % 12), 1 + (i % 28), 12, 0, 0)
        for i in range(1000)
    ]

    def call_dst() -> int:
        count = 0
        for dt in dts:
            tz.dst(dt)
            count += 1
        return count

    result = benchmark(call_dst)
    assert result == len(dts)
