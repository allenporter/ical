"""Tests for recurrence adapter and override filtering."""

from __future__ import annotations

import datetime
import textwrap
import zoneinfo

import pytest

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event, EventStatus
from ical.recur_adapter import FilteredRecurrenceIterable, RecurAdapter
from ical.todo import Todo
from ical.types.period import Period
from ical.types.recur import Frequency, Recur, RecurrenceId


ICS_OVERRIDE_TEMPLATE = textwrap.dedent(
    """\
    BEGIN:VCALENDAR
    VERSION:2.0
    PRODID:-//Test//Test//EN
    BEGIN:VEVENT
    UID:series
    DTSTAMP:20260901T000000Z
    SUMMARY:Daily
    {master}
    RRULE:FREQ=DAILY;COUNT=5
    END:VEVENT
    BEGIN:VEVENT
    UID:series
    DTSTAMP:20260901T000000Z
    SUMMARY:Daily
    STATUS:CANCELLED
    {override}
    END:VEVENT
    END:VCALENDAR
    """
)


@pytest.mark.parametrize(
    ("master", "override"),
    [
        pytest.param(
            "DTSTART:20261001T090000\nDTEND:20261001T093000",
            "RECURRENCE-ID:20261003T090000\nDTSTART:20261003T090000\nDTEND:20261003T093000",
            id="floating",
        ),
        pytest.param(
            "DTSTART;TZID=Europe/Berlin:20261001T090000\nDTEND;TZID=Europe/Berlin:20261001T093000",
            "RECURRENCE-ID;TZID=Europe/Berlin:20261003T090000\n"
            "DTSTART;TZID=Europe/Berlin:20261003T090000\nDTEND;TZID=Europe/Berlin:20261003T093000",
            id="tzid",
        ),
        pytest.param(
            "DTSTART:20261001T090000Z\nDTEND:20261001T093000Z",
            "RECURRENCE-ID:20261003T090000Z\nDTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
            id="utc",
        ),
        pytest.param(
            "DTSTART;TZID=Europe/Berlin:20261001T090000\nDTEND;TZID=Europe/Berlin:20261001T093000",
            "RECURRENCE-ID:20261003T070000Z\nDTSTART:20261003T070000Z\nDTEND:20261003T073000Z",
            id="tzid-override-in-utc",
        ),
        pytest.param(
            "DTSTART;TZID=Europe/Berlin:20261001T150000\nDTEND;TZID=Europe/Berlin:20261001T153000",
            "RECURRENCE-ID;TZID=America/New_York:20261003T090000\n"
            "DTSTART;TZID=America/New_York:20261003T090000\nDTEND;TZID=America/New_York:20261003T093000",
            id="tzid-override-in-different-tzid",
        ),
    ],
)
def test_recurrence_id_override_excludes_master_occurrence(
    master: str, override: str
) -> None:
    """Test that RECURRENCE-ID overrides replace the master occurrence across timezones (#690)."""
    calendar = IcsCalendarStream.calendar_from_ics(
        ICS_OVERRIDE_TEMPLATE.format(master=master, override=override)
    )
    events = list(calendar.timeline)
    assert len(events) == 5
    oct_3_events = [e for e in events if e.start.day == 3]
    assert len(oct_3_events) == 1
    assert oct_3_events[0].status == EventStatus.CANCELLED


def test_filtered_recurrence_iterable_edge_cases() -> None:
    """Test FilteredRecurrenceIterable with naive master and aware exclude_id, and unparsable id."""
    dates: list[datetime.datetime | datetime.date] = [
        datetime.datetime(2026, 10, 1, 9, 0),
        datetime.datetime(2026, 10, 2, 9, 0),
        datetime.datetime(2026, 10, 3, 9, 0),
    ]
    exclude_ids = frozenset(
        [
            RecurrenceId("20261002T090000Z", tzinfo=datetime.timezone.utc),
            RecurrenceId("invalid-id"),
        ]
    )
    filtered = list(FilteredRecurrenceIterable(dates, exclude_ids))
    assert filtered == [
        datetime.datetime(2026, 10, 1, 9, 0),
        datetime.datetime(2026, 10, 3, 9, 0),
    ]


def test_recur_adapter_period_clears_duration_on_event_and_todo() -> None:
    """Test that an RDATE Period overrides a master Event/Todo's duration."""
    event = Event(
        uid="ev-1",
        summary="Duration event with RDATE period",
        dtstart=datetime.datetime(2026, 5, 1, 9, 0),
        duration=datetime.timedelta(hours=1),
        rdate=[
            Period(
                start=datetime.datetime(2026, 5, 2, 10, 0),
                end=datetime.datetime(2026, 5, 2, 13, 0),
            )
        ],
    )
    cal = Calendar(events=[event])
    expanded = list(cal.timeline)
    assert len(expanded) == 1
    assert expanded[0].dtstart == datetime.datetime(2026, 5, 2, 10, 0)
    assert expanded[0].dtend == datetime.datetime(2026, 5, 2, 13, 0)
    assert expanded[0].duration is None
    assert expanded[0].end == datetime.datetime(2026, 5, 2, 13, 0)
    assert expanded[0].computed_duration == datetime.timedelta(hours=3)

    todo = Todo(
        uid="td-1",
        summary="Duration todo with RDATE period",
        dtstart=datetime.datetime(2026, 5, 1, 9, 0),
        duration=datetime.timedelta(hours=1),
        rdate=[
            Period(
                start=datetime.datetime(2026, 5, 2, 10, 0),
                duration=datetime.timedelta(hours=4),
            )
        ],
    )
    adapter = RecurAdapter(todo, tzinfo=datetime.timezone.utc)
    item = adapter.get(datetime.datetime(2026, 5, 2, 10, 0)).item
    assert item.due == datetime.datetime(2026, 5, 2, 14, 0)
    assert item.duration is None
    assert item.end == datetime.datetime(2026, 5, 2, 14, 0)
    assert item.computed_duration == datetime.timedelta(hours=4)


def test_recur_adapter_period_timezone_alignment() -> None:
    """Test RecurAdapter aligns Period end_value timezone awareness with dtstart."""
    tz_ny = zoneinfo.ZoneInfo("America/New_York")

    # Floating dtstart with aware Period in rdate
    event_floating = Event(
        uid="ev-float",
        summary="Floating with aware period",
        dtstart=datetime.datetime(2026, 5, 1, 9, 0),
        dtend=datetime.datetime(2026, 5, 1, 10, 0),
        rdate=[
            Period(
                start=datetime.datetime(2026, 5, 2, 10, 0, tzinfo=tz_ny),
                end=datetime.datetime(2026, 5, 2, 12, 0, tzinfo=tz_ny),
            )
        ],
    )
    cal_float = Calendar(events=[event_floating])
    events_float = list(cal_float.timeline)
    assert len(events_float) == 1
    assert events_float[0].dtstart == datetime.datetime(2026, 5, 2, 10, 0)
    assert events_float[0].dtend == datetime.datetime(2026, 5, 2, 12, 0)

    # Aware dtstart with naive Period in rdate
    event_aware = Event(
        uid="ev-aware",
        summary="Aware with naive period",
        dtstart=datetime.datetime(2026, 5, 1, 9, 0, tzinfo=tz_ny),
        dtend=datetime.datetime(2026, 5, 1, 10, 0, tzinfo=tz_ny),
        rdate=[
            Period(
                start=datetime.datetime(2026, 5, 2, 10, 0),
                end=datetime.datetime(2026, 5, 2, 12, 0),
            )
        ],
    )
    adapter_aware = RecurAdapter(event_aware, tzinfo=tz_ny)
    expanded_aware = adapter_aware.get(
        datetime.datetime(2026, 5, 2, 10, 0, tzinfo=tz_ny)
    ).item
    assert expanded_aware.dtstart == datetime.datetime(2026, 5, 2, 10, 0, tzinfo=tz_ny)
    assert expanded_aware.dtend == datetime.datetime(2026, 5, 2, 12, 0, tzinfo=tz_ny)

    # Aware dtstart in NY matching aware Period in UTC for the same instant
    event_cross_tz = Event(
        uid="ev-cross",
        summary="Cross-tz period",
        dtstart=datetime.datetime(2026, 5, 1, 9, 0, tzinfo=tz_ny),
        dtend=datetime.datetime(2026, 5, 1, 10, 0, tzinfo=tz_ny),
        rdate=[
            Period(
                start=datetime.datetime(
                    2026, 5, 2, 13, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(2026, 5, 2, 16, 0, tzinfo=datetime.timezone.utc),
            )
        ],
    )
    adapter = RecurAdapter(event_cross_tz, tzinfo=tz_ny)
    expanded_may_2 = adapter.get(datetime.datetime(2026, 5, 2, 9, 0, tzinfo=tz_ny)).item
    assert expanded_may_2.computed_duration == datetime.timedelta(hours=3)
