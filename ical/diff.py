"""Comparing two versions of the same set of events.

A calendar fetched on a recurring basis -- a sports fixture list, a class
timetable, a shared team calendar -- changes between fetches. This module
answers what changed, using the identity rule rfc5545 already defines
rather than a naive comparison by `uid` alone, which is wrong the moment a
recurring event has a modified instance: those share a `uid` with the
series and differ only by `recurrence_id`.
"""

from __future__ import annotations

import dataclasses

from .event import Event

__all__ = ["EventChange", "EventDiff", "diff_events"]


def _identity(event: Event) -> tuple[str, str]:
    """Return the rfc5545 identity of an event occurrence.

    The full range of a recurrence set is referenced by `uid` alone; a
    specific instance within it additionally needs `recurrence_id`. Two
    events sharing both identify the same occurrence, even across separate
    parses of separate fetches.

    Compared as a plain string. `RecurrenceId` also carries `tzinfo` and
    `range`, parsed from the TZID/RANGE property parameters, but they are
    ordinary instance attributes bolted onto a `str` subclass rather than
    part of its `__eq__` -- so two occurrences with the same recurrence_id
    string but different tzinfo/range would still identify the same
    occurrence here. That can't produce a missed content change: since
    recurrence_id is the identity key, it is always equal-by-construction
    within a pair `_content_equal` ever compares.
    """
    return (event.uid, event.recurrence_id or "")


def _content_equal(old: Event, new: Event) -> bool:
    """Return whether two same-identity events have the same content.

    `dtstamp` is excluded: it records when the ics object was generated,
    not the event's own content, and some producers regenerate it on every
    export of an otherwise unchanged event. Comparing it would report every
    event from such a producer as changed, defeating the point of a diff.
    Every other field, including `extras` (passthrough unknown properties),
    is compared -- a producer that encodes something volatile there is a
    real gap, not one to guess a fix for without a sample to test against.
    """
    return old.model_copy(update={"dtstamp": None}) == new.model_copy(
        update={"dtstamp": None}
    )


@dataclasses.dataclass
class EventChange:
    """An occurrence present in both calendars with different content."""

    old: Event
    """The occurrence as it appeared in the old calendar."""

    new: Event
    """The occurrence as it appears in the new calendar."""


@dataclasses.dataclass
class EventDiff:
    """The result of comparing the events of two calendars."""

    added: list[Event]
    """Occurrences present in the new calendar but not the old one."""

    removed: list[Event]
    """Occurrences present in the old calendar but not the new one."""

    changed: list[EventChange]
    """Occurrences present in both, with different content."""


def diff_events(old: list[Event], new: list[Event]) -> EventDiff:
    """Compare the events of two fetches of the same calendar.

    Matches occurrences by `uid` and `recurrence_id`, the identity rfc5545
    defines for a specific instance of a (possibly recurring) event, not by
    `uid` alone -- which conflates a whole recurring series with any single
    modified instance within it, since both carry the same `uid`.

    If the same identity appears more than once within `old` or within
    `new` -- a malformed but not impossible calendar -- the last occurrence
    for that identity in the list wins, matching the semantics of building
    a `dict` from it. Results are ordered by each identity's first
    appearance in the respective list.
    """
    old_by_identity: dict[tuple[str, str], Event] = {}
    for event in old:
        old_by_identity[_identity(event)] = event

    new_by_identity: dict[tuple[str, str], Event] = {}
    for event in new:
        new_by_identity[_identity(event)] = event

    added: list[Event] = []
    changed: list[EventChange] = []
    for identity, new_event in new_by_identity.items():
        if (old_event := old_by_identity.get(identity)) is None:
            added.append(new_event)
        elif not _content_equal(old_event, new_event):
            changed.append(EventChange(old=old_event, new=new_event))

    removed = [
        event
        for identity, event in old_by_identity.items()
        if identity not in new_by_identity
    ]

    return EventDiff(added=added, removed=removed, changed=changed)
