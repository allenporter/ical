"""Tests for matching edited instances against a recurrence expansion."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.recur_adapter import FilteredRecurrenceIterable
from ical.store import EventStore
from ical.timeline import generic_timeline
from ical.types.recur import Recur, RecurrenceId

_ICS = """BEGIN:VCALENDAR
PRODID:-//example//example//EN
VERSION:2.0
BEGIN:{component}
UID:series
DTSTAMP:20260901T000000Z
SUMMARY:Daily
{master}
RRULE:FREQ=DAILY;COUNT={count}
END:{component}
BEGIN:{component}
UID:series
DTSTAMP:20260901T000000Z
SUMMARY:Edited
STATUS:CANCELLED
{override}
END:{component}
END:VCALENDAR
"""

_FLOATING = "DTSTART:20261001T090000\nDTEND:20261001T093000"
_BERLIN = (
    "DTSTART;TZID=Europe/Berlin:20261001T090000\n"
    "DTEND;TZID=Europe/Berlin:20261001T093000"
)
_UTC = "DTSTART:20261001T090000Z\nDTEND:20261001T093000Z"
_ALL_DAY = "DTSTART;VALUE=DATE:20261001\nDTEND;VALUE=DATE:20261002"


def _timeline(master: str, override: str, count: int = 5) -> list[tuple[str, str]]:
    """Return (start, summary) for every instance on the calendar's timeline."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _ICS.format(component="VEVENT", master=master, override=override, count=count)
    )
    return [
        (event.start.isoformat(), event.summary or "")
        for event in calendar.timeline_tz(datetime.timezone.utc)
    ]


@pytest.mark.parametrize(
    ("master", "override", "edited_start"),
    [
        (
            _FLOATING,
            "RECURRENCE-ID:20261003T090000\n"
            "DTSTART:20261003T090000\nDTEND:20261003T093000",
            "2026-10-03T09:00:00",
        ),
        (
            _BERLIN,
            "RECURRENCE-ID;TZID=Europe/Berlin:20261003T090000\n"
            "DTSTART;TZID=Europe/Berlin:20261003T090000\n"
            "DTEND;TZID=Europe/Berlin:20261003T093000",
            "2026-10-03T09:00:00+02:00",
        ),
        (
            _ALL_DAY,
            "RECURRENCE-ID;VALUE=DATE:20261003\n"
            "DTSTART;VALUE=DATE:20261003\nDTEND;VALUE=DATE:20261004",
            "2026-10-03",
        ),
        (
            _UTC,
            "RECURRENCE-ID:20261003T090000Z\n"
            "DTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
            "2026-10-03T09:00:00+00:00",
        ),
        (
            _BERLIN,
            "RECURRENCE-ID:20261003T070000Z\n"
            "DTSTART:20261003T070000Z\nDTEND:20261003T073000Z",
            "2026-10-03T07:00:00+00:00",
        ),
        (
            _BERLIN,
            "RECURRENCE-ID;TZID=Europe/London:20261003T080000\n"
            "DTSTART;TZID=Europe/London:20261003T080000\n"
            "DTEND;TZID=Europe/London:20261003T083000",
            "2026-10-03T08:00:00+01:00",
        ),
        (
            _UTC,
            "RECURRENCE-ID;TZID=Europe/Berlin:20261003T110000\n"
            "DTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
            "2026-10-03T09:00:00+00:00",
        ),
        (
            _UTC,
            "RECURRENCE-ID:20261003T090000Z\n"
            "DTSTART:20261003T150000Z\nDTEND:20261003T153000Z",
            "2026-10-03T15:00:00+00:00",
        ),
        (
            _UTC,
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20261003T090000Z\n"
            "DTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
            "2026-10-03T09:00:00+00:00",
        ),
        (
            _FLOATING,
            "RECURRENCE-ID;TZID=Europe/Berlin:20261003T090000\n"
            "DTSTART;TZID=Europe/Berlin:20261003T090000\n"
            "DTEND;TZID=Europe/Berlin:20261003T093000",
            "2026-10-03T09:00:00+02:00",
        ),
        (
            _FLOATING,
            "RECURRENCE-ID:20261003T090000Z\n"
            "DTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
            "2026-10-03T09:00:00+00:00",
        ),
        (
            _BERLIN,
            "RECURRENCE-ID:20261003T090000\n"
            "DTSTART;TZID=Europe/Berlin:20261003T090000\n"
            "DTEND;TZID=Europe/Berlin:20261003T093000",
            "2026-10-03T09:00:00+02:00",
        ),
    ],
    ids=[
        "floating",
        "tzid",
        "all-day",
        "utc",
        "tzid-series-utc-override",
        "tzid-series-other-tzid-override",
        "utc-series-tzid-override",
        "utc-moved",
        "utc-this-and-future",
        "floating-series-tzid-override",
        "floating-series-utc-override",
        "tzid-series-floating-override",
    ],
)
def test_override_replaces_its_instance(
    master: str, override: str, edited_start: str
) -> None:
    """An edited instance replaces the occurrence it names, whatever its form."""
    timeline = _timeline(master, override)

    assert len(timeline) == 5
    assert [summary for _, summary in timeline].count("Edited") == 1
    assert (edited_start, "Edited") in timeline
    assert not [
        start for start, summary in timeline if summary == "Daily" and "-10-03" in start
    ]


@pytest.mark.parametrize(
    ("master", "override"),
    [
        (
            # 09:00Z is 11:00 in Berlin: not an instance of a 09:00 series.
            _BERLIN,
            "RECURRENCE-ID:20261003T090000Z\n"
            "DTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
        ),
        (
            _UTC,
            "RECURRENCE-ID:20261003T080000Z\n"
            "DTSTART:20261003T080000Z\nDTEND:20261003T083000Z",
        ),
        (
            # A datetime never names an instance of an all-day series.
            _ALL_DAY,
            "RECURRENCE-ID:20261003T000000\n"
            "DTSTART:20261003T000000\nDTEND:20261003T010000",
        ),
        (
            # A DATE never names an instance of a timed series.
            _UTC,
            "RECURRENCE-ID;VALUE=DATE:20261003\n"
            "DTSTART;VALUE=DATE:20261003\nDTEND;VALUE=DATE:20261004",
        ),
    ],
    ids=[
        "tzid-series-other-instant",
        "utc-other-instant",
        "all-day-datetime",
        "timed-series-date",
    ],
)
def test_override_for_another_instant_does_not_replace(
    master: str, override: str
) -> None:
    """An override that names no instance of the series leaves it intact."""
    timeline = _timeline(master, override)

    assert len(timeline) == 6
    assert [summary for _, summary in timeline].count("Daily") == 5


@pytest.mark.parametrize(
    ("recurrence_id", "replaced"),
    [
        # After 2026-10-25 Berlin is on CET (+01:00): 09:00 is 08:00Z.
        ("20261027T080000Z", True),
        # 07:00Z would be 09:00 with the summer offset of DTSTART.
        ("20261027T070000Z", False),
    ],
)
def test_utc_override_across_dst(recurrence_id: str, replaced: bool) -> None:
    """The instant is resolved in the zone of each instance, not of DTSTART."""
    timeline = _timeline(
        _BERLIN,
        f"RECURRENCE-ID:{recurrence_id}\n"
        f"DTSTART:{recurrence_id}\nDTEND:20261027T083000Z",
        count=30,
    )

    assert len(timeline) == (30 if replaced else 31)
    assert (("2026-10-27T09:00:00+01:00", "Daily") in timeline) is not replaced


def test_dst_fallback_fold_disambiguation() -> None:
    """Overriding fold=1 via UTC RECURRENCE-ID leaves fold=0 intact."""
    ny = zoneinfo.ZoneInfo("America/New_York")
    # 2026-11-01 01:30 EDT (fold=0, 05:30Z) and 01:30 EST (fold=1, 06:30Z)
    fold0 = datetime.datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=0)
    fold1 = datetime.datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=1)

    filtered = list(
        FilteredRecurrenceIterable(
            [fold0, fold1],
            frozenset({RecurrenceId("20261101T063000Z", tzinfo=datetime.timezone.utc)}),
            tzinfo=ny,
        )
    )
    assert len(filtered) == 1
    assert filtered[0].fold == 0
    assert filtered[0].astimezone(datetime.timezone.utc) == datetime.datetime(
        2026, 11, 1, 5, 30, tzinfo=datetime.timezone.utc
    )


def test_iter_after_fast_forward_excludes_utc_override() -> None:
    """Range queries using iter_after still suppress overridden instances."""
    ics = _ICS.format(
        component="VEVENT",
        master=_BERLIN,
        override=(
            "RECURRENCE-ID:20261003T070000Z\n"
            "DTSTART:20261003T070000Z\nDTEND:20261003T073000Z"
        ),
        count=5,
    )
    calendar = IcsCalendarStream.calendar_from_ics(ics)
    tl = calendar.timeline_tz(datetime.timezone.utc)

    start = datetime.datetime(2026, 10, 3, 0, 0, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 10, 5, 0, 0, tzinfo=datetime.timezone.utc)
    overlapping = [
        (ev.start.isoformat(), ev.summary) for ev in tl.overlapping(start, end)
    ]
    assert overlapping == [
        ("2026-10-03T07:00:00+00:00", "Edited"),
        ("2026-10-04T09:00:00+02:00", "Daily"),
    ]
    included = [(ev.start.isoformat(), ev.summary) for ev in tl.included(start, end)]
    assert included == overlapping

    after = [
        (ev.start.isoformat(), ev.summary)
        for ev in tl.start_after(
            datetime.datetime(2026, 10, 2, 12, 0, tzinfo=datetime.timezone.utc)
        )
    ]
    assert len(after) == 3
    assert [s for _, s in after] == ["Edited", "Daily", "Daily"]


def test_multi_override_same_wall_time_different_tzid() -> None:
    """Overrides sharing a wall time in different TZIDs exclude their distinct instants."""
    ics = """BEGIN:VCALENDAR
PRODID:-//example//example//EN
VERSION:2.0
BEGIN:VEVENT
UID:hourly-series
DTSTAMP:20260901T000000Z
SUMMARY:Hourly
DTSTART:20261003T060000Z
DTEND:20261003T063000Z
RRULE:FREQ=HOURLY;COUNT=10
END:VEVENT
BEGIN:VEVENT
UID:hourly-series
DTSTAMP:20260901T000000Z
SUMMARY:Berlin 09:00 (07:00Z)
RECURRENCE-ID;TZID=Europe/Berlin:20261003T090000
DTSTART:20261003T070000Z
DTEND:20261003T073000Z
END:VEVENT
BEGIN:VEVENT
UID:hourly-series
DTSTAMP:20260901T000000Z
SUMMARY:NY 09:00 (13:00Z)
RECURRENCE-ID;TZID=America/New_York:20261003T090000
DTSTART:20261003T130000Z
DTEND:20261003T133000Z
END:VEVENT
END:VCALENDAR
"""
    calendar = IcsCalendarStream.calendar_from_ics(ics)
    events = list(calendar.timeline_tz(datetime.timezone.utc))
    assert len(events) == 10
    by_start = {ev.start: ev.summary for ev in events}
    assert (
        by_start[datetime.datetime(2026, 10, 3, 7, 0, tzinfo=datetime.timezone.utc)]
        == "Berlin 09:00 (07:00Z)"
    )
    assert (
        by_start[datetime.datetime(2026, 10, 3, 13, 0, tzinfo=datetime.timezone.utc)]
        == "NY 09:00 (13:00Z)"
    )


def test_overflow_and_null_utcoffset_in_comparable_key() -> None:
    """Boundary datetimes and custom tzinfo with utcoffset()=None do not crash."""

    class _NullOffsetTz(datetime.tzinfo):
        def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
            return None

        def dst(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
            return None

        def tzname(self, dt: datetime.datetime | None) -> str | None:
            return "NULL"

    boundary = RecurrenceId(
        "00010101T000000",
        tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
    )
    # Must not raise OverflowError
    key = RecurrenceId.comparable_key(boundary)
    assert isinstance(key, datetime.datetime)

    null_tz_rid = RecurrenceId("20261003T090000", tzinfo=_NullOffsetTz())
    null_key = RecurrenceId.comparable_key(null_tz_rid)
    assert null_key == datetime.datetime(2026, 10, 3, 9, 0)


def test_utc_override_on_todo() -> None:
    """To-dos share the expansion with events."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _ICS.format(
            component="VTODO",
            master="DTSTART:20261001T090000Z\nDUE:20261001T093000Z",
            override="RECURRENCE-ID:20261003T090000Z\n"
            "DTSTART:20261003T090000Z\nDUE:20261003T093000Z",
            count=5,
        )
    )

    todos = list(generic_timeline(calendar.todos, datetime.timezone.utc))

    assert len(todos) == 5
    assert [todo.summary for todo in todos].count("Edited") == 1


def test_store_edit_of_utc_series() -> None:
    """Editing one instance through the store keeps a single copy of it."""
    calendar = Calendar()
    store = EventStore(calendar)
    store.add(
        Event(
            summary="Daily",
            start=datetime.datetime(2026, 10, 1, 9, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2026, 10, 1, 9, 30, tzinfo=datetime.timezone.utc),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=5"),
        )
    )
    uid = calendar.events[0].uid
    assert uid

    store.edit(uid, Event(summary="Edited"), recurrence_id="20261003T090000Z")

    events = list(calendar.timeline_tz(datetime.timezone.utc))
    assert len(events) == 5
    assert [event.summary for event in events].count("Edited") == 1


def test_unparsable_override_is_ignored() -> None:
    """A RECURRENCE-ID that is not a date or time names no instance."""
    timeline = _timeline(
        _UTC,
        "RECURRENCE-ID:not-a-date\nDTSTART:20261003T150000Z\nDTEND:20261003T153000Z",
    )
    assert len(timeline) == 6

    timeline_eq = _timeline(
        _UTC,
        "RECURRENCE-ID:foo=bar\nDTSTART:20261003T150000Z\nDTEND:20261003T153000Z",
    )
    assert len(timeline_eq) == 6
