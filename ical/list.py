"""A List is a set of objects on a calendar.

A List is used to iterate over all objects, including expanded recurring
objects. A List is similar to a Timeline, except it does not repeat recurring
objects on the list and they are only shown once. A list does not repeat
forever.
"""

import datetime
from collections.abc import Generator
import logging

from .todo import Todo
from .recur_adapter import items_by_uid, merge_and_expand_items
from .util import local_timezone

# Not part of the public API
__all__: list[str] = []

_LOGGER = logging.getLogger(__name__)


def _pick_todo(todos: list[Todo], dtstart: datetime.datetime) -> Todo:
    """Pick a todo to return in a list from a list of recurring todos.

    The items passed in must all be for the same original todo (either a
    single todo or instance of a recurring todo including any edits). An
    edited instance of a recurring todo has a recurrence-id that is
    different from the original todo. This function will return the
    next todo that is incomplete and has the latest due date.
    """
    # For a recurring todo, the dtstart is after the last due date. Therefore
    # we can stort items by dtstart and pick the last one that hasn't happened
    root_iter = merge_and_expand_items(todos, dtstart.tzinfo or local_timezone())

    it = iter(root_iter)
    last = next(it)
    while cur := next(it, None):
        if cur.item.start_datetime is None or cur.item.start_datetime > dtstart:
            break
        last = cur
    return last.item


def todo_list_view(
    todos: list[Todo],
    dtstart: datetime.datetime | None = None,
) -> Generator[Todo, None, None]:
    """Create a list view for todos on a calendar, including recurrence.

    The dtstart value is used to determine the current time for the list and
    for deciding which instance of a recurring todo to return.
    """
    if dtstart is None:
        dtstart = datetime.datetime.now(tz=local_timezone())
    todos_by_uid = items_by_uid(todos)
    for todos in todos_by_uid.values():
        yield _pick_todo(todos, dtstart)
