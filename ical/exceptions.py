"""Exceptions for ical library."""


class CalendarError(Exception):
    """Base exception for all ical errors."""


class CalendarParseError(CalendarError):
    """Exception raised when parsing an ical string."""


class RecurrenceError(CalendarError):
    """Exception raised when evaluating a recurrence rule.

    Recurrence rules have complex logic and it is common for there to be
    invalid date or bugs, so this special exception exists to help
    provide additional debug data to find the source of the issue. Often
    `dateutil.rrule` has limitataions and ical has to work around them
    by providing special wrapping libraries.
    """


class StoreError(CalendarError):
    """Exception thrown by a Store."""


class EventStoreError(StoreError):
    """Exception thrown by the EventStore."""


class TodoStoreError(StoreError):
    """Exception thrown by the TodoStore."""