"""A List is a set of objects on a calendar.

A List is used to iterate over all objects, including expanded recurring
objects. A List is similar to a Timeline, except it does not repeat recurring
objects on the list and they are only shown once. A list does not repeat
forever.
"""

import datetime
from collections.abc import Generator, Iterable
import logging

from .todo import Todo
from .iter import (
    LazySortableItem,
    MergedIterable,
    RecurIterable,
    SortableItem,
    SortableItemValue,
    SortedItemIterable,
)
from .types.recur import RecurrenceId


_LOGGER = logging.getLogger(__name__)


class RecurAdapter:
    """An adapter that expands an Todo instance for a recurrence rule.

    This adapter is given an todo, then invoked with a specific date/time instance
    that the todo is due from a recurrence rule. The todo is copied with
    necessary updated fields to act as a flattened instance of the todo item.
    """

    def __init__(self, todo: Todo, tzinfo: datetime.tzinfo | None = None):
        """Initialize the RecurAdapter."""
        self._todo = todo
        if todo.computed_duration is None:
            raise ValueError("Recurring todo must have a duration")
        self._duration = todo.computed_duration
        self._tzinfo = tzinfo

    def get(
        self, dtstart: datetime.datetime | datetime.date
    ) -> SortableItem[datetime.datetime | datetime.date | None, Todo]:
        """Return a lazy sortable item."""

        recur_id_dt = dtstart
        # Make recurrence_id floating time to avoid dealing with serializing
        # TZID. This value will still be unique within the series and is in
        # the context of dtstart which may have a timezone.
        if isinstance(recur_id_dt, datetime.datetime) and recur_id_dt.tzinfo:
            recur_id_dt = recur_id_dt.replace(tzinfo=None)
        recurrence_id = RecurrenceId.__parse_property_value__(recur_id_dt)

        def build() -> Todo:
            return self._todo.copy(
                update={
                    "dtstart": dtstart,
                    "due": dtstart + self._duration,
                    "recurrence_id": recurrence_id,
                },
            )

        return LazySortableItem(dtstart, build)


def _todos_by_uid(todos: list[Todo]) -> dict[str, list[Todo]]:
    todos_by_uid: dict[str, list[Todo]] = {}
    for todo in todos:
        if todo.uid is None:
            raise ValueError("Todo must have a UID")
        if todo.uid not in todos_by_uid:
            todos_by_uid[todo.uid] = []
        todos_by_uid[todo.uid].append(todo)
    return todos_by_uid


def _pick_todo(todos: list[Todo], tzinfo: datetime.tzinfo) -> Todo:
    """Pick a todo to return in a list from a list of recurring todos.

    The items passed in must all be for the same original todo (either a
    single todo or instance of a recurring todo including any edits). An
    edited instance of a recurring todo has a recurrence-id that is
    different from the original todo. This function will return the
    next todo that is incomplete and has the latest due date.
    """
    # For a recurring todo, the dtstart is after the last due date. Therefore
    # we can stort items by dtstart and pick the last one that hasn't happened    
    iters = []
    for todo in todos:
        if not (recur := todo.as_rrule()):
            iters.append([SortableItemValue(todo.dtstart, todo)])
            continue
        iters.append(RecurIterable(RecurAdapter(todo, tzinfo=tzinfo).get, recur))

    root_iter = MergedIterable(iters)
    
    # Pick the first todo that hasn't started yet based on its dtstart
    now = datetime.datetime.now(tzinfo)
    last: Todo | None = None

    it = iter(root_iter)
    last = next(it, None)
    if not last:
        raise ValueError("Expected at least one item in the iterable")
    while cur := next(it, None):
        if cur.item.start_datetime is None or cur.item.start_datetime > now:
            break
        last = cur
    return last.item if last is not None else None


def todo_list_view(
    todos: list[Todo], tzinfo: datetime.tzinfo
) -> Generator[Todo, None, None]:
    """Create a list view for todos on a calendar, including recurrence."""
    todos_by_uid = _todos_by_uid(todos)
    for todos in todos_by_uid.values():
        yield _pick_todo(todos, tzinfo=tzinfo)
