"""Regression and benchmark tests for performance of TzInfo.dst().

TzInfo.dst() previously rebuilt two dateutil.rrule.rrule instances on
every call to compute the year's DST start/end transitions. Because
utcoffset() also calls dst(), every datetime comparison during timeline
iteration (heap sort, Timespan ordering, recurrence expansion) triggered
this work. For large calendars that use posix-rule TzInfo instances --
e.g. Office 365 ICS feeds whose VTIMEZONEs ("Pacific Standard Time" etc.)
get mapped to posix rules by the compat layer -- this dominated runtime.

The cache regression test below is always run; the ``benchmark`` tests
follow the existing ``pytest-benchmark`` pattern (see ``test_iter.py`` and
``test_tz_rule.py``) and are skipped by default via the ``--benchmark-skip``
option in ``pytest.ini``. Run them explicitly with ``--benchmark-only``.

See:
- home-assistant/core#148315
- allenporter/ical#481 (same class of bug, different code path)
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import patch

import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import enable_compat_mode
from ical.tzif import timezoneinfo, tz_rule


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


def _build_office_style_ics(num_events: int) -> str:
    """Build a synthetic ICS using an Office 365-style 'Pacific Standard Time'
    VTIMEZONE plus ``num_events`` non-overlapping VEVENTs spanning several
    years. The TZID is mapped by ical's compat layer to a posix-rule
    TzInfo, which is the code path that exhibited the regression.
    """
    # Office 365 VTIMEZONE block as Microsoft emits it. The TZID
    # "Pacific Standard Time" is non-IANA; the ical compat layer maps it
    # to America/Los_Angeles (posix-rule TzInfo).
    vtimezone = """BEGIN:VTIMEZONE
TZID:Pacific Standard Time
BEGIN:STANDARD
DTSTART:16010101T020000
TZOFFSETFROM:-0700
TZOFFSETTO:-0800
RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:-0800
TZOFFSETTO:-0700
RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
"""

    lines = [
        "BEGIN:VCALENDAR",
        "METHOD:PUBLISH",
        "PRODID:Microsoft Exchange Server 2010",
        "VERSION:2.0",
        vtimezone.rstrip(),
    ]

    # Spread events across several years so timeline iteration crosses
    # multiple year boundaries (which mirrors a real Office 365 calendar).
    base = datetime.datetime(2020, 1, 1, 9, 0, 0)
    for i in range(num_events):
        start = base + datetime.timedelta(hours=i)
        end = start + datetime.timedelta(minutes=30)
        lines += [
            "BEGIN:VEVENT",
            f"UID:perf-regression-{i}@example.invalid",
            f"SUMMARY:Event {i}",
            f"DTSTART;TZID=Pacific Standard Time:{start:%Y%m%dT%H%M%S}",
            f"DTEND;TZID=Pacific Standard Time:{end:%Y%m%dT%H%M%S}",
            f"DTSTAMP:{start:%Y%m%dT%H%M%S}Z",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


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


@pytest.mark.parametrize("num_events", [500, 2000])
@pytest.mark.benchmark(min_rounds=1, warmup=False)
def test_benchmark_office365_extended_timezone_timeline(
    num_events: int, benchmark: Any
) -> None:
    """Benchmark ``timeline.active_after()`` on an Office 365-style ICS.

    Builds a synthetic ICS using the non-IANA ``Pacific Standard Time``
    TZID (which the ical compat layer maps to a posix-rule TzInfo) and
    measures how long it takes to fetch the next active event. This is
    the user-facing scenario that motivated the per-year DST transition
    cache (Home Assistant polls this repeatedly for Office 365
    calendars).
    """
    ics = _build_office_style_ics(num_events=num_events)
    with enable_compat_mode(ics) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert len(calendar.events) == num_events

    now = datetime.datetime.now(datetime.timezone.utc)

    def lookup_next() -> None:
        # ``timeline`` rebuilds the iterator each time (mirrors HA
        # polling pattern), so re-access it inside the benchmark loop.
        next(calendar.timeline.active_after(now), None)

    benchmark(lookup_next)
