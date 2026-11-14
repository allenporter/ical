"""Compatibility for Exchange exceptions identifying timed occurrences at midnight."""

from collections import defaultdict
from collections.abc import Generator
import contextlib
import contextvars
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..event import Event

_enabled = contextvars.ContextVar("recurrence_id_compat", default=False)


@contextlib.contextmanager
def enable_recurrence_id_compat() -> Generator[None]:
    """Enable the Exchange recurrence identifier fix during parsing."""
    token = _enabled.set(True)
    try:
        yield
    finally:
        _enabled.reset(token)


def normalize_recurrence_ids(events: list["Event"]) -> None:
    """Match midnight exceptions to an unambiguous timed occurrence that day.

    Exchange published feeds can use midnight rather than the original start
    time in RECURRENCE-ID. Limit inference to one daily-or-less-frequent master
    with no extra recurrence dates. Never infer from the exception's DTSTART:
    the exception may have moved to a different day or time.
    """
    # Delay imports: event/type parsing imports the compatibility package.
    from ..types.recur import Frequency, RecurrenceId  # noqa: PLC0415

    if not _enabled.get():
        return
    masters: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.rrule and not event.recurrence_id:
            masters[event.uid].append(event)
    for event in events:
        if not event.recurrence_id or event.rrule:
            continue
        candidates = masters.get(event.uid, [])
        if len(candidates) != 1:
            continue
        master = candidates[0]
        if (
            not isinstance(master.dtstart, datetime.datetime)
            or not master.rrule
            or master.rrule.freq
            in (Frequency.HOURLY, Frequency.MINUTELY, Frequency.SECONDLY)
            or master.rrule.by_hour
            or master.rrule.by_minute
            or master.rrule.by_second
            or master.rdate
        ):
            continue
        if not str(event.recurrence_id).endswith("T000000"):
            continue
        original = datetime.datetime.strptime(
            str(event.recurrence_id), "%Y%m%dT%H%M%S"
        ).replace(tzinfo=event.recurrence_id.tzinfo)
        if (
            not isinstance(original, datetime.datetime)
            or original.time() != datetime.time()
            or original.tzinfo != master.dtstart.tzinfo
        ):
            continue
        candidate = original.replace(
            hour=master.dtstart.hour,
            minute=master.dtstart.minute,
            second=master.dtstart.second,
        )
        if candidate == original:
            continue
        # Verify this day is actually part of the series, including its bounds.
        rule = master.rrule.as_rrule(master.dtstart)
        if rule.before(candidate, inc=True) != candidate:
            continue
        event.recurrence_id = RecurrenceId(
            candidate.strftime("%Y%m%dT%H%M%S"),
            tzinfo=original.tzinfo,
            range=event.recurrence_id.range,
        )
