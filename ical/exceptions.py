"""Exceptions for ical library."""


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
    """Exception thrown by a Store."""


class EventStoreError(StoreError):
    """Exception thrown by the EventStore."""


class TodoStoreError(StoreError):
    """Exception thrown by the TodoStore."""
