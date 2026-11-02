"""Tests for the timeline library."""

from concurrent.futures import ThreadPoolExecutor
import datetime
import random
import threading
import zoneinfo
from typing import Any
from unittest.mock import patch

import pytest

import ical.iter as iter_mod
from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.compat import enable_compat_mode
from ical.event import Event
from ical.journal import Journal
from ical.types.recur import Recur
from ical.tzif import timezoneinfo
from ical.timeline import generic_timeline, materialize_timeline, calendar_timeline

TZ = zoneinfo.ZoneInfo("America/Regina")


@pytest.fixture(name="calendar")
def fake_calendar(num_events: int, num_instances: int) -> Calendar:
    """Fixture for creating a fake calendar of items."""
    cal = Calendar()
    for i in range(num_events):
        delta = datetime.timedelta(days=int(365 * random.random()))
        cal.events.append(
            Event(
                summary=f"Event {i}",
                start=datetime.date(2022, 2, 1) + delta,
                end=datetime.date(2000, 2, 2) + delta,
                rrule=Recur.from_rrule(f"FREQ=DAILY;COUNT={num_instances}"),
            )
        )
    return cal


@pytest.mark.parametrize(
    "num_events,num_instances",
    [
        (10, 10),
        (10, 100),
        (10, 1000),
        (100, 10),
        (100, 100),
    ],
)
@pytest.mark.benchmark(min_rounds=1, cprofile=True, warmup=False)
def test_benchmark_merged_iter(
    calendar: Calendar, num_events: int, num_instances: int, benchmark: Any
) -> None:
    """Add a benchmark for the merged iterator."""

    def exhaust() -> int:
        nonlocal calendar
        return sum(1 for _ in calendar.timeline_tz(TZ))

    result = benchmark(exhaust)
    assert result == num_events * num_instances


def test_journal_timeline() -> None:
    """Test journal entries on a timeline."""

    journal = Journal(
        summary="Example",
        start=datetime.date(2022, 8, 7),
        rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
    )
    assert journal.recurring

    with (
        patch(
            "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
        ),
        patch(
            "ical.journal.local_timezone",
            return_value=zoneinfo.ZoneInfo("America/Regina"),
        ),
    ):
        timeline = generic_timeline([journal], TZ)
        assert list(timeline) == [
            Journal.model_copy(journal, update={"recurrence_id": "20220807"}),
            Journal.model_copy(
                journal,
                update={
                    "dtstart": datetime.date(2022, 8, 8),
                    "recurrence_id": "20220808",
                },
            ),
            Journal.model_copy(
                journal,
                update={
                    "dtstart": datetime.date(2022, 8, 9),
                    "recurrence_id": "20220809",
                },
            ),
        ]
        assert list(
            timeline.overlapping(datetime.date(2022, 8, 7), datetime.date(2022, 8, 9))
        ) == [
            Journal.model_copy(journal, update={"recurrence_id": "20220807"}),
            Journal.model_copy(
                journal,
                update={
                    "dtstart": datetime.date(2022, 8, 8),
                    "recurrence_id": "20220808",
                },
            ),
        ]


def test_materialize_timeline_empty() -> None:
    """Test materializing an empty timeline."""
    cal = Calendar()
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 2, tzinfo=datetime.timezone.utc),
    )
    assert list(materialized) == []


def test_materialize_timeline_events() -> None:
    """Test materializing a timeline with events."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.datetime(2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    cal.events.append(
        Event(
            summary="Event 2",
            start=datetime.datetime(2022, 1, 2, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 2, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    cal.events.append(
        Event(
            summary="Event 3",
            start=datetime.datetime(2022, 1, 3, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 3, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 3, tzinfo=datetime.timezone.utc),
    )
    events = list(materialized)
    assert len(events) == 2
    assert events[0].summary == "Event 1"
    assert events[1].summary == "Event 2"

    # Verify that the events are the same object when iterating multiple times
    assert list(materialized) == events
    assert list(materialized)[0] is events[0]
    assert list(materialized)[1] is events[1]


def test_materialize_recurring_timeline() -> None:
    """Test materializing a timeline with recurring events."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.datetime(2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
        )
    )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 3, tzinfo=datetime.timezone.utc),
    )
    events = list(materialized)
    assert len(events) == 2
    assert events[0].summary == "Event 1"
    assert events[0].start == datetime.datetime(
        2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc
    )
    assert events[1].summary == "Event 1"
    assert events[1].start == datetime.datetime(
        2022, 1, 2, 8, 0, tzinfo=datetime.timezone.utc
    )


def test_benchmark_materialize_timeline() -> None:
    """Benchmark materializing a timeline."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.date(2022, 1, 1),
            end=datetime.date(2022, 1, 2),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=1000"),
        )
    )
    timeline = calendar_timeline(cal.events, zoneinfo.ZoneInfo("UTC"))

    materialize_timeline(
        timeline,
        datetime.date(2022, 1, 1),
        datetime.date(2022, 4, 1),
    )


def test_materialize_timeline_max_events() -> None:
    """Test materializing a timeline with a maximum number of events."""
    cal = Calendar()
    for i in range(10):
        cal.events.append(
            Event(
                summary=f"Event {i}",
                start=datetime.datetime(
                    2022, 1, 1, 8 + i, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(
                    2022, 1, 1, 9 + i, 0, tzinfo=datetime.timezone.utc
                ),
            )
        )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)

    # Test with limit of 5
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 2, tzinfo=datetime.timezone.utc),
        max_number_of_events=5,
    )
    events = list(materialized)
    assert len(events) == 5
    assert [e.summary for e in events] == [f"Event {i}" for i in range(5)]

    # Test with limit of 15 (more than available)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 2, tzinfo=datetime.timezone.utc),
        max_number_of_events=15,
    )
    events = list(materialized)
    assert len(events) == 10


def test_materialize_timeline_no_stop() -> None:
    """Test materializing a timeline without a stop time."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.datetime(2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    cal.events.append(
        Event(
            summary="Event 2",
            start=datetime.datetime(2022, 1, 2, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 2, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)

    # No stop specified should return all events active after start
    # (max_number_of_events is required when stop is None)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
        max_number_of_events=1,
    )
    events = list(materialized)
    assert len(events) == 1
    assert events[0].summary == "Event 2"


def test_materialize_timeline_no_exit_condition() -> None:
    """Test that materialize_timeline raises ValueError without an exit condition."""
    cal = Calendar()
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    with pytest.raises(
        ValueError, match="Either stop or max_number_of_events must be specified"
    ):
        materialize_timeline(
            timeline,
            datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        )


def test_materialize_timeline_no_stop_max_events() -> None:
    """Test materializing a timeline without a stop time and a limit."""
    cal = Calendar()
    for i in range(10):
        cal.events.append(
            Event(
                summary=f"Event {i}",
                start=datetime.datetime(
                    2022, 1, 1 + i, 8, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(
                    2022, 1, 1 + i, 9, 0, tzinfo=datetime.timezone.utc
                ),
            )
        )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)

    # No stop specified, limit 3
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        max_number_of_events=3,
    )
    events = list(materialized)
    assert len(events) == 3
    assert [e.summary for e in events] == ["Event 0", "Event 1", "Event 2"]


def _build_office_style_ics(num_events: int) -> str:
    """Build a synthetic ICS using an Office 365-style 'Pacific Standard Time'

    VTIMEZONE plus ``num_events`` non-overlapping VEVENTs spanning several
    years. The TZID is mapped by ical's compat layer to a posix-rule
    TzInfo, which is the code path that exhibited the regression.
    """
    # Office 365 VTIMEZONE block as Microsoft emits it. The TZID
    # "Pacific Standard Time" is non-IANA; the ical compat layer maps it
    # to America/Los_Angeles (posix-rule TzInfo).
    lines = [
        "BEGIN:VCALENDAR",
        "METHOD:PUBLISH",
        "PRODID:Microsoft Exchange Server 2010",
        "VERSION:2.0",
        "BEGIN:VTIMEZONE",
        "TZID:Pacific Standard Time",
        "BEGIN:STANDARD",
        "DTSTART:16010101T020000",
        "TZOFFSETFROM:-0700",
        "TZOFFSETTO:-0800",
        "RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11",
        "END:STANDARD",
        "BEGIN:DAYLIGHT",
        "DTSTART:16010101T020000",
        "TZOFFSETFROM:-0800",
        "TZOFFSETTO:-0700",
        "RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3",
        "END:DAYLIGHT",
        "END:VTIMEZONE",
    ]

    # Spread events across several years so timeline iteration crosses
    # multiple year boundaries (which mirrors a real Office 365 calendar).
    base = datetime.datetime(2020, 1, 1, 9, 0, 0)
    for i in range(num_events):
        start = base + datetime.timedelta(hours=i)
        end = start + datetime.timedelta(minutes=30)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:perf-regression-{i}@example.invalid",
                f"SUMMARY:Event {i}",
                f"DTSTART;TZID=Pacific Standard Time:{start:%Y%m%dT%H%M%S}",
                f"DTEND;TZID=Pacific Standard Time:{end:%Y%m%dT%H%M%S}",
                f"DTSTAMP:{start:%Y%m%dT%H%M%S}Z",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


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


def _build_past_recurring_calendar(num_events: int) -> Calendar:
    """Build a synthetic calendar with recurring events starting in the distant past."""
    cal = Calendar()
    base_year = 1920
    for i in range(num_events):
        year = base_year + (i % 60)
        month = (i % 12) + 1
        day = (i % 28) + 1
        cal.events.append(
            Event(
                summary=f"Recurring Event {i}",
                start=datetime.date(year, month, day),
                end=datetime.date(year, month, day) + datetime.timedelta(days=1),
                rrule=Recur.from_rrule("FREQ=YEARLY"),
            )
        )
    return cal


@pytest.mark.parametrize("num_events", [50, 100])
@pytest.mark.benchmark(min_rounds=3, warmup=False)
def test_benchmark_recurring_timeline_overlapping(
    num_events: int, benchmark: Any
) -> None:
    """Benchmark timeline.overlapping() for recurring events with distant past DTSTART.

    Tests the Home Assistant calendar entity polling pattern (issue #688),
    where a calendar contains many recurring events whose DTSTART dates
    are decades in the past, queried for a 1-day window in the present.
    """
    cal = _build_past_recurring_calendar(num_events)
    tz = zoneinfo.ZoneInfo("America/Regina")
    today = datetime.date(2026, 9, 27)
    start = datetime.datetime.combine(today, datetime.time.min, tz)
    end = datetime.datetime.combine(
        today + datetime.timedelta(days=1), datetime.time.min, tz
    )

    def lookup_overlapping() -> list[Event]:
        # Access timeline each time to mirror Home Assistant polling
        return list(cal.timeline_tz(tz).overlapping(start, end))

    benchmark(lookup_overlapping)


@pytest.mark.parametrize("num_events", [50, 100])
@pytest.mark.benchmark(min_rounds=3, warmup=False)
def test_benchmark_recurring_timeline_active_after(
    num_events: int, benchmark: Any
) -> None:
    """Benchmark timeline.active_after() for recurring events with distant past DTSTART.

    Tests the Home Assistant calendar entity state update pattern (issue #688),
    where the entity queries the next upcoming event from a calendar with
    unbounded recurring events starting decades in the past.
    """
    cal = _build_past_recurring_calendar(num_events)
    now = datetime.datetime(2026, 9, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def lookup_next() -> Event | None:
        return next(cal.timeline.active_after(now), None)

    benchmark(lookup_next)


def test_timeline_included_does_not_break_early_on_long_event() -> None:
    """Test that included() does not prematurely break when an event overflows the end."""
    ev_long = Event(
        summary="Long",
        dtstart=datetime.datetime(2025, 5, 2, 9, 0, tzinfo=datetime.timezone.utc),
        dtend=datetime.datetime(2025, 5, 12, 9, 0, tzinfo=datetime.timezone.utc),
    )
    ev_inside = Event(
        summary="Inside",
        dtstart=datetime.datetime(2025, 5, 3, 9, 0, tzinfo=datetime.timezone.utc),
        dtend=datetime.datetime(2025, 5, 3, 10, 0, tzinfo=datetime.timezone.utc),
    )
    ev_after = Event(
        summary="After",
        dtstart=datetime.datetime(2025, 5, 11, 9, 0, tzinfo=datetime.timezone.utc),
        dtend=datetime.datetime(2025, 5, 11, 10, 0, tzinfo=datetime.timezone.utc),
    )
    tl = calendar_timeline([ev_long, ev_inside, ev_after], datetime.timezone.utc)
    result = list(
        tl.included(
            datetime.datetime(2025, 5, 1, 0, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2025, 5, 10, 0, 0, tzinfo=datetime.timezone.utc),
        )
    )
    assert [e.summary for e in result] == ["Inside"]


def test_timeline_included_all_day_exact_bounds() -> None:
    """Test that an all-day event is included in its exact date range."""
    ev_all_day = Event(
        summary="All Day",
        dtstart=datetime.date(2025, 5, 1),
        dtend=datetime.date(2025, 5, 2),
    )
    tl = calendar_timeline([ev_all_day], datetime.timezone.utc)
    result = list(tl.included(datetime.date(2025, 5, 1), datetime.date(2025, 5, 2)))
    assert [e.summary for e in result] == ["All Day"]


def test_timeline_at_instant_zero_duration_event() -> None:
    """Test that at_instant() returns zero-duration events at that exact instant."""
    ev_zero = Event(
        summary="Zero Duration",
        dtstart=datetime.datetime(2025, 5, 1, 9, 0, tzinfo=datetime.timezone.utc),
    )
    ev_normal = Event(
        summary="Normal",
        dtstart=datetime.datetime(2025, 5, 1, 8, 0, tzinfo=datetime.timezone.utc),
        dtend=datetime.datetime(2025, 5, 1, 9, 0, tzinfo=datetime.timezone.utc),
    )
    tl = calendar_timeline([ev_zero, ev_normal], datetime.timezone.utc)
    # At 09:00, ev_normal has just ended (exclusive) and ev_zero is active
    result = list(
        tl.at_instant(datetime.datetime(2025, 5, 1, 9, 0, tzinfo=datetime.timezone.utc))
    )
    assert [e.summary for e in result] == ["Zero Duration"]


def test_timeline_preserves_tzinfo_across_queries() -> None:
    """Test that timeline queries and materialize_timeline use the timeline's tzinfo."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    ev_all_day = Event(
        summary="NY All Day",
        dtstart=datetime.date(2025, 5, 1),
        dtend=datetime.date(2025, 5, 2),
    )
    ev_timed = Event(
        summary="NY Timed",
        dtstart=datetime.datetime(2025, 5, 1, 10, 0, tzinfo=tz),
        dtend=datetime.datetime(2025, 5, 1, 11, 0, tzinfo=tz),
    )

    with patch(
        "ical.util.local_timezone", side_effect=AssertionError("local_timezone called")
    ):
        tl = calendar_timeline([ev_all_day, ev_timed], tz)

        assert [
            e.summary
            for e in tl.included(datetime.date(2025, 5, 1), datetime.date(2025, 5, 2))
        ] == ["NY All Day", "NY Timed"]

        assert [
            e.summary
            for e in tl.overlapping(
                datetime.date(2025, 5, 1), datetime.date(2025, 5, 2)
            )
        ] == ["NY All Day", "NY Timed"]

        assert [e.summary for e in tl.on_date(datetime.date(2025, 5, 1))] == [
            "NY All Day",
            "NY Timed",
        ]

        assert [
            e.summary for e in tl.start_after(datetime.datetime(2025, 5, 1, 9, 0))
        ] == ["NY Timed"]

        assert [
            e.summary for e in tl.active_after(datetime.datetime(2025, 5, 1, 10, 30))
        ] == ["NY All Day", "NY Timed"]

        assert [
            e.summary for e in tl.at_instant(datetime.datetime(2025, 5, 1, 10, 30))
        ] == ["NY All Day", "NY Timed"]

        materialized = materialize_timeline(
            tl,
            datetime.date(2025, 5, 1),
            datetime.date(2025, 5, 2),
        )
        assert [e.summary for e in materialized.on_date(datetime.date(2025, 5, 1))] == [
            "NY All Day",
            "NY Timed",
        ]


def test_materialize_timeline_concurrent_threads() -> None:
    """Test concurrent materialize_timeline calls across threads (issue #734)."""
    iter_mod._RECURRENCE_CACHE.clear()
    num_threads = 8
    calendars = [_build_past_recurring_calendar(20) for _ in range(num_threads)]
    start = datetime.datetime(2026, 9, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)
    barrier = threading.Barrier(num_threads)

    def worker(cal: Calendar) -> list[str | None]:
        barrier.wait()
        mat = materialize_timeline(cal.timeline, start, max_number_of_events=50)
        return [e.summary for e in mat]

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, cal) for cal in calendars]
        results = [f.result() for f in futures]

    expected = [
        e.summary
        for e in materialize_timeline(
            calendars[0].timeline, start, max_number_of_events=50
        )
    ]
    assert len(expected) == 50
    for res in results:
        assert res == expected


@pytest.mark.benchmark(min_rounds=3, warmup=False)
def test_benchmark_recurring_with_recurrence_id_overrides(benchmark: Any) -> None:
    """Benchmark timeline queries on recurring series with RECURRENCE-ID overrides."""
    cal = Calendar()
    for i in range(50):
        uid = f"recurring-override-{i}@example.invalid"
        base_date = datetime.date(2020, 1, 1) + datetime.timedelta(days=i % 28)
        cal.events.append(
            Event(
                uid=uid,
                summary=f"Weekly Sync {i}",
                start=base_date,
                end=base_date + datetime.timedelta(days=1),
                rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=300"),
            )
        )
        override_date = base_date + datetime.timedelta(weeks=10)
        cal.events.append(
            Event(
                uid=uid,
                summary=f"Weekly Sync {i} (Rescheduled)",
                start=override_date + datetime.timedelta(days=1),
                end=override_date + datetime.timedelta(days=2),
                recurrence_id=override_date.strftime("%Y%m%d"),
            )
        )

    now = datetime.datetime(2025, 6, 1, 0, 0, tzinfo=datetime.timezone.utc)

    def lookup_next() -> Event | None:
        return next(cal.timeline.active_after(now), None)

    benchmark(lookup_next)


def test_timeline_dst_fallback_ordering_and_queries() -> None:
    """Test timeline ordering and range/instant queries across DST fall-back (issue #761)."""
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    cal = Calendar()
    cal.events.append(
        Event(
            summary="All Day",
            start=datetime.date(2023, 11, 5),
            end=datetime.date(2023, 11, 6),
        )
    )
    cal.events.append(
        Event(
            summary="First (01:45 PDT)",
            start=datetime.datetime(2023, 11, 5, 1, 45, tzinfo=tz, fold=0),
            end=datetime.datetime(2023, 11, 5, 1, 55, tzinfo=tz, fold=0),
        )
    )
    cal.events.append(
        Event(
            summary="Second (01:15 PST)",
            start=datetime.datetime(2023, 11, 5, 1, 15, tzinfo=tz, fold=1),
            end=datetime.datetime(2023, 11, 5, 1, 30, tzinfo=tz, fold=1),
        )
    )
    cal.events.append(
        Event(
            summary="Hourly (PDT/PST)",
            start=datetime.datetime(2023, 11, 5, 0, 35, tzinfo=tz),
            end=datetime.datetime(2023, 11, 5, 0, 45, tzinfo=tz),
            rrule=Recur.from_rrule("FREQ=HOURLY;COUNT=3"),
        )
    )

    timeline = cal.timeline_tz(tz)

    # 1. Chronological order on DST fall-back day
    assert [
        (e.summary, getattr(e.start, "fold", None))
        for e in timeline.on_date(datetime.date(2023, 11, 5))
    ] == [
        ("All Day", None),
        ("Hourly (PDT/PST)", 0),
        ("Hourly (PDT/PST)", 0),
        ("First (01:45 PDT)", 0),
        ("Second (01:15 PST)", 1),
        ("Hourly (PDT/PST)", 0),
    ]

    # 2. active_after / start_after at 01:50 PDT (fold=0) includes Second (01:15 PST, fold=1)
    t_0150_pdt = datetime.datetime(2023, 11, 5, 1, 50, tzinfo=tz, fold=0)
    assert [e.summary for e in timeline.active_after(t_0150_pdt)] == [
        "All Day",
        "First (01:45 PDT)",
        "Second (01:15 PST)",
        "Hourly (PDT/PST)",
    ]
    assert [e.summary for e in timeline.start_after(t_0150_pdt)] == [
        "Second (01:15 PST)",
        "Hourly (PDT/PST)",
    ]

    # Querying after 01:20 PST (fold=1) must NOT re-include 01:45 PDT (fold=0)
    t_0120_pst = datetime.datetime(2023, 11, 5, 1, 20, tzinfo=tz, fold=1)
    assert [e.summary for e in timeline.active_after(t_0120_pst)] == [
        "All Day",
        "Second (01:15 PST)",
        "Hourly (PDT/PST)",
    ]
    assert [e.summary for e in timeline.start_after(t_0120_pst)] == [
        "Hourly (PDT/PST)",
    ]

    # 3. overlapping and included across window straddling 02:00 PDT -> 01:00 PST
    t_0155_pdt = datetime.datetime(2023, 11, 5, 1, 55, tzinfo=tz, fold=0)
    assert [e.summary for e in timeline.overlapping(t_0155_pdt, t_0120_pst)] == [
        "All Day",
        "Second (01:15 PST)",
    ]
    t_0135_pst = datetime.datetime(2023, 11, 5, 1, 35, tzinfo=tz, fold=1)
    assert [e.summary for e in timeline.included(t_0155_pdt, t_0135_pst)] == [
        "Second (01:15 PST)",
    ]

    # 4. at_instant distinguishes fold=0 vs fold=1
    assert [
        e.summary
        for e in timeline.at_instant(
            datetime.datetime(2023, 11, 5, 1, 20, tzinfo=tz, fold=0)
        )
    ] == ["All Day"]
    assert [e.summary for e in timeline.at_instant(t_0120_pst)] == [
        "All Day",
        "Second (01:15 PST)",
    ]

    # 5. materialize_timeline preserves fold-aware filtering with max_number_of_events and stop
    mat_max = materialize_timeline(timeline, t_0150_pdt, max_number_of_events=10)
    assert [e.summary for e in mat_max] == [
        "All Day",
        "First (01:45 PDT)",
        "Second (01:15 PST)",
        "Hourly (PDT/PST)",
    ]
    mat_stop = materialize_timeline(timeline, t_0155_pdt, stop=t_0120_pst)
    assert [e.summary for e in mat_stop] == [
        "All Day",
        "Second (01:15 PST)",
    ]


def test_timeline_issue_761_reproduction() -> None:
    """Direct reproduction from GitHub issue #761."""
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    cal = Calendar()
    cal.events.append(
        Event(
            summary="First (01:45 PDT)",
            start=datetime.datetime(2023, 11, 5, 1, 45, tzinfo=tz, fold=0),
            end=datetime.datetime(2023, 11, 5, 1, 55, tzinfo=tz, fold=0),
        )
    )
    cal.events.append(
        Event(
            summary="Second (01:15 PST)",
            start=datetime.datetime(2023, 11, 5, 1, 15, tzinfo=tz, fold=1),
            end=datetime.datetime(2023, 11, 5, 1, 30, tzinfo=tz, fold=1),
        )
    )

    timeline = cal.timeline_tz(tz)

    assert [e.summary for e in timeline.on_date(datetime.date(2023, 11, 5))] == [
        "First (01:45 PDT)",
        "Second (01:15 PST)",
    ]
    assert [
        e.summary
        for e in timeline.active_after(
            datetime.datetime(2023, 11, 5, 1, 50, tzinfo=tz, fold=0)
        )
    ] == [
        "First (01:45 PDT)",
        "Second (01:15 PST)",
    ]
    assert [
        e.summary
        for e in timeline.overlapping(
            datetime.datetime(2023, 11, 5, 1, 55, tzinfo=tz, fold=0),
            datetime.datetime(2023, 11, 5, 1, 20, tzinfo=tz, fold=1),
        )
    ] == ["Second (01:15 PST)"]


def test_timeline_dst_fallback_scheduler_sweep() -> None:
    """Simulate a scheduler polling active_after, at_instant, and 15m windows across fall-back."""
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    cal = Calendar()
    cal.events.extend(
        [
            Event(
                summary="Before Fold (00:30 PDT)",
                start=datetime.datetime(2023, 11, 5, 0, 30, tzinfo=tz, fold=0),
                end=datetime.datetime(2023, 11, 5, 0, 50, tzinfo=tz, fold=0),
            ),
            Event(
                summary="Pass 1 (01:10 PDT)",
                start=datetime.datetime(2023, 11, 5, 1, 10, tzinfo=tz, fold=0),
                end=datetime.datetime(2023, 11, 5, 1, 25, tzinfo=tz, fold=0),
            ),
            Event(
                summary="Straddling Fold (01:45 PDT -> 01:15 PST)",
                start=datetime.datetime(2023, 11, 5, 1, 45, tzinfo=tz, fold=0),
                end=datetime.datetime(2023, 11, 5, 1, 15, tzinfo=tz, fold=1),
            ),
            Event(
                summary="Pass 2 (01:10 PST)",
                start=datetime.datetime(2023, 11, 5, 1, 10, tzinfo=tz, fold=1),
                end=datetime.datetime(2023, 11, 5, 1, 25, tzinfo=tz, fold=1),
            ),
            Event(
                summary="After Fold (02:05 PST)",
                start=datetime.datetime(2023, 11, 5, 2, 5, tzinfo=tz, fold=0),
                end=datetime.datetime(2023, 11, 5, 2, 20, tzinfo=tz, fold=0),
            ),
        ]
    )
    timeline = cal.timeline_tz(tz)

    expected_order = [
        "Before Fold (00:30 PDT)",
        "Pass 1 (01:10 PDT)",
        "Straddling Fold (01:45 PDT -> 01:15 PST)",
        "Pass 2 (01:10 PST)",
        "After Fold (02:05 PST)",
    ]
    assert [e.summary for e in timeline] == expected_order

    # Step through physical time in UTC and convert each probe to local tz (preserving fold)
    probes = [
        (
            datetime.datetime(2023, 11, 5, 7, 45, tzinfo=datetime.UTC).astimezone(tz),
            "Before Fold (00:30 PDT)",
            ["Before Fold (00:30 PDT)"],
        ),
        (
            datetime.datetime(2023, 11, 5, 8, 15, tzinfo=datetime.UTC).astimezone(tz),
            "Pass 1 (01:10 PDT)",
            ["Pass 1 (01:10 PDT)"],
        ),
        (
            datetime.datetime(2023, 11, 5, 8, 50, tzinfo=datetime.UTC).astimezone(tz),
            "Straddling Fold (01:45 PDT -> 01:15 PST)",
            ["Straddling Fold (01:45 PDT -> 01:15 PST)"],
        ),
        (
            # 09:12Z == 01:12 PST (fold=1): both the straddling event and Pass 2 are active
            datetime.datetime(2023, 11, 5, 9, 12, tzinfo=datetime.UTC).astimezone(tz),
            "Straddling Fold (01:45 PDT -> 01:15 PST)",
            ["Straddling Fold (01:45 PDT -> 01:15 PST)", "Pass 2 (01:10 PST)"],
        ),
        (
            # 09:20Z == 01:20 PST (fold=1): Pass 1 (01:10-01:25 PDT) must NOT re-trigger
            datetime.datetime(2023, 11, 5, 9, 20, tzinfo=datetime.UTC).astimezone(tz),
            "Pass 2 (01:10 PST)",
            ["Pass 2 (01:10 PST)"],
        ),
        (
            # 09:45Z == 01:45 PST (fold=1): Straddling Fold (01:45 PDT) must NOT re-trigger
            datetime.datetime(2023, 11, 5, 9, 45, tzinfo=datetime.UTC).astimezone(tz),
            "After Fold (02:05 PST)",
            [],
        ),
    ]
    for local_now, expected_next, expected_active_now in probes:
        nxt = next(timeline.active_after(local_now), None)
        assert nxt is not None and nxt.summary == expected_next
        assert [e.summary for e in timeline.at_instant(local_now)] == (
            expected_active_now
        )


def test_timeline_dst_fallback_mixed_ics_utc_and_local_zones() -> None:
    """Test ICS calendar mixing UTC ('Z'), TZID, floating, and zero-duration events across fall-back."""
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Test//Test//EN",
            # Floating local time: 01:20 in viewer tz -> 01:20 PDT (fold=0, 08:20Z)
            "BEGIN:VEVENT",
            "UID:floating@example.com",
            "SUMMARY:Floating 01:20",
            "DTSTART:20231105T012000",
            "DTEND:20231105T012500",
            "DTSTAMP:20231101T000000Z",
            "END:VEVENT",
            # TZID=America/Los_Angeles: RFC 5545 §3.3.5 first occurrence -> 01:30 PDT (fold=0, 08:30Z)
            "BEGIN:VEVENT",
            "UID:la-tzid-zero@example.com",
            "SUMMARY:LA Zero-Duration 01:30 PDT",
            "DTSTART;TZID=America/Los_Angeles:20231105T013000",
            "DTSTAMP:20231101T000000Z",
            "END:VEVENT",
            # Unambiguous UTC event during LA's repeated hour: 09:15Z == 01:15 PST (fold=1)
            "BEGIN:VEVENT",
            "UID:utc-fold1@example.com",
            "SUMMARY:UTC Event at 01:15 PST (09:15Z)",
            "DTSTART:20231105T091500Z",
            "DTEND:20231105T093000Z",
            "DTSTAMP:20231101T000000Z",
            "END:VEVENT",
            # America/New_York event at 04:45 EST (already past NY's own fallback) == 09:45Z (01:45 PST fold=1)
            "BEGIN:VEVENT",
            "UID:ny-post-fold@example.com",
            "SUMMARY:NY 04:45 EST (01:45 PST)",
            "DTSTART;TZID=America/New_York:20231105T044500",
            "DTEND;TZID=America/New_York:20231105T050000",
            "DTSTAMP:20231101T000000Z",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    cal = IcsCalendarStream.calendar_from_ics(ics)
    la_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    timeline = cal.timeline_tz(la_tz)

    assert [e.summary for e in timeline.on_date(datetime.date(2023, 11, 5))] == [
        "Floating 01:20",
        "LA Zero-Duration 01:30 PDT",
        "UTC Event at 01:15 PST (09:15Z)",
        "NY 04:45 EST (01:45 PST)",
    ]

    # Cross-zone zero-duration lookup at 08:30Z matches 01:30 PDT (fold=0), not 01:30 PST (fold=1)
    assert [
        e.summary
        for e in timeline.at_instant(
            datetime.datetime(2023, 11, 5, 8, 30, tzinfo=datetime.UTC)
        )
    ] == ["LA Zero-Duration 01:30 PDT"]
    assert [
        e.summary
        for e in timeline.at_instant(
            datetime.datetime(2023, 11, 5, 1, 30, tzinfo=la_tz, fold=1)
        )
    ] == []


def test_timeline_included_across_dst_fallback_does_not_break_early() -> None:
    """Test that included() does not break early when an overflowing event starts in fold=0."""
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    # Overflowing event starts at 01:40 PDT (fold=0, 08:40Z) and ends at 01:50 PST (fold=1, 09:50Z).
    # Query ends at 01:35 PST (fold=1, 09:35Z). In wall time, 01:40 > 01:35 would falsely break
    # before reaching the included event at 01:10-01:30 PST (fold=1, 09:10Z-09:30Z).
    ev_overflow = Event(
        summary="Overflow Across Fold",
        start=datetime.datetime(2023, 11, 5, 1, 40, tzinfo=tz, fold=0),
        end=datetime.datetime(2023, 11, 5, 1, 50, tzinfo=tz, fold=1),
    )
    ev_inside_fold1 = Event(
        summary="Inside Fold 1",
        start=datetime.datetime(2023, 11, 5, 1, 10, tzinfo=tz, fold=1),
        end=datetime.datetime(2023, 11, 5, 1, 30, tzinfo=tz, fold=1),
    )
    tl = calendar_timeline([ev_overflow, ev_inside_fold1], tz)
    result = list(
        tl.included(
            datetime.datetime(2023, 11, 5, 0, 30, tzinfo=tz, fold=0),
            datetime.datetime(2023, 11, 5, 1, 35, tzinfo=tz, fold=1),
        )
    )
    assert [e.summary for e in result] == ["Inside Fold 1"]


def test_timeline_dst_fallback_southern_hemisphere() -> None:
    """Test DST fall-back ordering and queries in Southern Hemisphere (Australia/Sydney)."""
    # 2024-04-07 in Australia/Sydney: 03:00 AEDT (+11:00) falls back to 02:00 AEST (+10:00)
    sydney = zoneinfo.ZoneInfo("Australia/Sydney")
    cal = Calendar()
    cal.events.append(
        Event(
            summary="AEDT (02:45+11)",
            start=datetime.datetime(2024, 4, 7, 2, 45, tzinfo=sydney, fold=0),
            end=datetime.datetime(2024, 4, 7, 2, 55, tzinfo=sydney, fold=0),
        )
    )
    cal.events.append(
        Event(
            summary="AEST (02:15+10)",
            start=datetime.datetime(2024, 4, 7, 2, 15, tzinfo=sydney, fold=1),
            end=datetime.datetime(2024, 4, 7, 2, 30, tzinfo=sydney, fold=1),
        )
    )
    tl = cal.timeline_tz(sydney)

    assert [e.summary for e in tl.on_date(datetime.date(2024, 4, 7))] == [
        "AEDT (02:45+11)",
        "AEST (02:15+10)",
    ]
    assert [
        e.summary
        for e in tl.overlapping(
            datetime.datetime(2024, 4, 7, 2, 55, tzinfo=sydney, fold=0),
            datetime.datetime(2024, 4, 7, 2, 20, tzinfo=sydney, fold=1),
        )
    ] == ["AEST (02:15+10)"]


def test_timeline_tie_breaking_and_boundary_extremes() -> None:
    """Test deterministic stream tie-breaking, custom tzinfo cutoff, and date.min bounds."""
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    # 4 recurring streams colliding at 08:30Z (01:30 PDT fold=0) after earlier pops:
    # exercises SortableItem.__eq__ / Timespan.__eq__ tuple tie-breaking in MergedIterator.
    events = [
        Event(
            uid="s0",
            summary="Series 0",
            start=datetime.datetime(2023, 11, 5, 1, 0, tzinfo=tz, fold=0),
            end=datetime.datetime(2023, 11, 5, 1, 15, tzinfo=tz, fold=0),
            rrule=Recur.from_rrule("FREQ=MINUTELY;INTERVAL=30;COUNT=2"),
        ),
        Event(
            uid="s1",
            summary="Series 1",
            start=datetime.datetime(2023, 11, 5, 1, 10, tzinfo=tz, fold=0),
            end=datetime.datetime(2023, 11, 5, 1, 20, tzinfo=tz, fold=0),
            rrule=Recur.from_rrule("FREQ=HOURLY;COUNT=1"),
        ),
        Event(
            uid="s2",
            summary="Series 2",
            start=datetime.datetime(2023, 11, 5, 2, 0, tzinfo=tz, fold=0),
            end=datetime.datetime(2023, 11, 5, 2, 15, tzinfo=tz, fold=0),
            rrule=Recur.from_rrule("FREQ=HOURLY;COUNT=1"),
        ),
        Event(
            uid="s3",
            summary="Series 3",
            start=datetime.datetime(2023, 11, 5, 8, 30, tzinfo=datetime.UTC),
            end=datetime.datetime(2023, 11, 5, 8, 45, tzinfo=datetime.UTC),
            rrule=Recur.from_rrule("FREQ=HOURLY;COUNT=1"),
        ),
    ]
    tl = calendar_timeline(events, tz)
    assert [e.summary for e in tl] == [
        "Series 0",
        "Series 1",
        "Series 0",
        "Series 3",
        "Series 2",
    ]

    # RecurIterable._start_cutoff keeps aware cutoffs in UTC without round-tripping through custom tzinfo.fromutc()
    seen_cutoffs: list[datetime.datetime] = []

    class _RecordingSeekable(iter_mod.SeekableIterable[datetime.datetime]):
        def __iter__(self) -> Any:
            return iter(())

        def iter_after(self, cutoff: datetime.datetime) -> Any:
            seen_cutoffs.append(cutoff)
            return iter(())

    custom_la = timezoneinfo.read_tzinfo("America/Los_Angeles")
    recur_it = iter_mod.RecurIterable(
        lambda dt: dt,
        _RecordingSeekable(),
        duration=datetime.timedelta(minutes=30),
    )
    # 02:00 PST (10:00Z) minus 30m == 09:30Z (in fold=1); must stay 09:30Z rather than shifting to 10:30Z
    list(recur_it.iter_after(datetime.datetime(2023, 11, 5, 2, 0, tzinfo=custom_la)))
    assert seen_cutoffs == [datetime.datetime(2023, 11, 5, 9, 30, tzinfo=datetime.UTC)]

    # Queries near datetime.date.min must not raise OverflowError when subtracting lookback buffers
    utc_tl = calendar_timeline(events, datetime.UTC)
    assert list(utc_tl.at_instant(datetime.date(1, 1, 1))) == []
    assert (
        list(utc_tl.overlapping(datetime.date(1, 1, 1), datetime.date(1, 1, 2))) == []
    )
