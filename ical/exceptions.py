"""Exceptions for ical library."""

__all__ = [
    "CalendarError",
    "CalendarParseError",
    "ParameterValueError",
    "RecurrenceError",
    "StoreError",
    "EventStoreError",
    "TodoStoreError",
]


class CalendarError(Exception):
    """Base exception for all ical errors."""


class CalendarParseError(CalendarError):
    """Exception raised when parsing an ical string.

    The 'message' attribute contains a human-readable message about the
    error that occurred. The 'detailed_error' attribute can provide additional
    information about the error, such as a stack trace or detailed parsing
    information, useful for debugging purposes.
    """

    def __init__(self, message: str, *, detailed_error: str | None = None) -> None:
        """Initialize the CalendarParseError with a message."""
        super().__init__(message)
        self.message = message
        self.detailed_error = detailed_error


class ParameterValueError(ValueError):
    """Exception raised when validating a datetime.

    When validating a ParsedProperty, it may not be known what data-type
    the result should be, so multiple validators may be called. We must
    distinguish between "this property does not look like this data-type"
    from "this property should be this data-type, but it is invalid". The
    former should raise a ValueError and the latter ParameterValueError.
    The motivating example is "DTSTART;TZID=GMT:20250601T171819" as either
    datetime or date. It fails to be a datetime because of an unrecognized
    timezone, and fails to be a date, because it is a datetime. Rather
    than continue trying to validate it as a date, raise ParameterValueError
    to stop, and simply return a single error.

    Note: This exception intentionally extends ``ValueError`` rather than
    ``CalendarError``. This allows pydantic's validation pipeline to catch it
    during field validation. Callers catching ``CalendarError`` will **not**
    catch this exception.
    """


class RecurrenceError(CalendarError):
    """Exception raised when evaluating a recurrence rule.

    Recurrence rules have complex logic and it is common for there to be
    invalid dates or bugs, so this special exception exists to help
    provide additional debug data to find the source of the issue. Often
    `dateutil.rrule` has limitations and ical has to work around them
    by providing special wrapping libraries.
    """


class StoreError(CalendarError):
    """Exception raised by store operations.

    Raised when a store operation fails, for example when trying to edit
    or delete an event that does not exist, or when timezone information
    cannot be resolved for a datetime value being added to the calendar.
    """


class EventStoreError(StoreError):
    """Exception raised by EventStore operations.

    Raised by :class:`ical.store.EventStore` when an event operation fails.
    """


class TodoStoreError(StoreError):
    """Exception raised by TodoStore operations.

    Raised by :class:`ical.store.TodoStore` when a todo operation fails.
    """
