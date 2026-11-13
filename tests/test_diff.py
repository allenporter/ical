"""Tests for comparing two versions of the same calendar (#677)."""

import datetime

from ical.calendar_stream import IcsCalendarStream
from ical.diff import EventChange, diff_events
from ical.event import Event

_UTC = datetime.timezone.utc


def _event(**kwargs) -> Event:
    kwargs.setdefault("summary", "Race")
    kwargs.setdefault("start", datetime.datetime(2025, 10, 26, 20, 0, tzinfo=_UTC))
    return Event(**kwargs)


def test_an_added_event_has_no_prior_occurrence() -> None:
    new_event = _event(uid="race-2")

    result = diff_events([], [new_event])

    assert result.added == [new_event]
    assert result.removed == []
    assert result.changed == []


def test_a_removed_event_has_no_later_occurrence() -> None:
    old_event = _event(uid="race-1")

    result = diff_events([old_event], [])

    assert result.added == []
    assert result.removed == [old_event]
    assert result.changed == []


def test_an_unchanged_event_is_neither_added_removed_nor_changed() -> None:
    old_event = _event(uid="race-1")
    new_event = _event(uid="race-1")

    result = diff_events([old_event], [new_event])

    assert result.added == []
    assert result.removed == []
    assert result.changed == []


def test_a_changed_field_is_reported_with_old_and_new_values() -> None:
    """The motivating case from the issue: the same race, a new start time."""
    old_event = _event(uid="race-1", sequence=0)
    new_event = _event(
        uid="race-1",
        start=datetime.datetime(2025, 10, 26, 20, 30, tzinfo=_UTC),
        sequence=1,
    )

    result = diff_events([old_event], [new_event])

    assert result.added == []
    assert result.removed == []
    assert result.changed == [EventChange(old=old_event, new=new_event)]


def test_regenerated_dtstamp_alone_is_not_a_change() -> None:
    """Some producers restamp DTSTAMP on every export of an unchanged event.

    Comparing it would report every such event as changed on every fetch,
    which defeats the point of a diff.
    """
    old_event = _event(uid="race-1", dtstamp=datetime.datetime(2025, 1, 1, tzinfo=_UTC))
    new_event = _event(uid="race-1", dtstamp=datetime.datetime(2025, 1, 2, tzinfo=_UTC))

    result = diff_events([old_event], [new_event])

    assert result.changed == []


def test_a_modified_recurrence_instance_is_matched_by_recurrence_id_not_uid_alone() -> (
    None
):
    """The bug a naive `uid`-only diff has: a series and its own modified
    instance share a `uid`, and are not the same occurrence."""
    series = _event(uid="standup")
    modified_instance = _event(
        uid="standup",
        recurrence_id="20251027T140000Z",
        summary="Standup (moved)",
    )

    result = diff_events([series], [series, modified_instance])

    assert result.added == [modified_instance]
    assert result.removed == []
    assert result.changed == []


def test_a_change_to_a_modified_instance_is_reported_against_itself_not_the_series() -> (
    None
):
    old_instance = _event(
        uid="standup", recurrence_id="20251027T140000Z", summary="Standup (moved)"
    )
    new_instance = _event(
        uid="standup",
        recurrence_id="20251027T140000Z",
        summary="Standup (moved again)",
    )

    result = diff_events([old_instance], [new_instance])

    assert result.changed == [EventChange(old=old_instance, new=new_instance)]


def test_a_duplicate_identity_within_one_list_keeps_the_last_occurrence() -> None:
    """Documented, tested behaviour for a malformed-but-not-impossible input,
    rather than leaving it as unspecified dict-overwrite behaviour."""
    first = _event(uid="race-1", summary="Race (first copy)")
    second = _event(uid="race-1", summary="Race (second copy)")

    result = diff_events([], [first, second])

    assert result.added == [second]


def test_extras_are_part_of_the_comparison() -> None:
    """Unlike `dtstamp`, passthrough unknown properties are not excluded:
    a producer encoding real content there should still be caught."""
    ics = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:race-1
DTSTART:20251026T200000Z
SUMMARY:Race
X-CUSTOM-STATUS:confirmed
END:VEVENT
END:VCALENDAR
"""
    old_event = IcsCalendarStream.calendar_from_ics(ics).events[0]
    new_event = IcsCalendarStream.calendar_from_ics(
        ics.replace("X-CUSTOM-STATUS:confirmed", "X-CUSTOM-STATUS:cancelled")
    ).events[0]

    result = diff_events([old_event], [new_event])

    assert result.changed == [EventChange(old=old_event, new=new_event)]


def test_result_order_follows_first_appearance_in_each_input_list() -> None:
    a = _event(uid="a")
    b = _event(uid="b")

    result = diff_events([], [b, a])

    assert result.added == [b, a]
