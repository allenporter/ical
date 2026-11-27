"""Tests for matching edited instances against a recurrence expansion."""

from __future__ import annotations

import datetime

import pytest

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.store import EventStore
from ical.timeline import generic_timeline
from ical.types.recur import Recur

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
            # The override moves the instance to the afternoon.
            _UTC,
            "RECURRENCE-ID:20261003T090000Z\n"
            "DTSTART:20261003T150000Z\nDTEND:20261003T153000Z",
            "2026-10-03T15:00:00+00:00",
        ),
        (
            # The timeline only replaces the instance itself for a range; that
            # is unchanged here, but the instance must still be matched.
            _UTC,
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20261003T090000Z\n"
            "DTSTART:20261003T090000Z\nDTEND:20261003T093000Z",
            "2026-10-03T09:00:00+00:00",
        ),
        (
            # A floating series has no instant to compare, so a zoned
            # RECURRENCE-ID is matched by the wall time it was written in.
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
            # A floating RECURRENCE-ID is read in the zone of the series.
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
            # Comparing the wall time with the Z dropped would match it.
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
            # A date never names an instance of a timed series.
            _ALL_DAY,
            "RECURRENCE-ID:20261003T000000\n"
            "DTSTART:20261003T000000\nDTEND:20261003T010000",
        ),
    ],
    ids=["tzid-series-other-instant", "utc-other-instant", "all-day-datetime"],
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
