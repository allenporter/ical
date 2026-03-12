"""Compatibility layer for DTSTART/UNTIL type mismatch in recurrence rules.

Some calendar providers (notably Google Calendar) generate iCalendar files
where DTSTART is a DATE-TIME but UNTIL in the RRULE is a DATE, which violates
RFC 5545 section 3.3.10. This module provides a compat mode that silently
converts the UNTIL DATE to a DATE-TIME matching the DTSTART type.
"""

from collections.abc import Generator
import contextlib
import contextvars


_dtstart_until_compat = contextvars.ContextVar("dtstart_until_compat", default=False)


@contextlib.contextmanager
def enable_dtstart_until_compat() -> Generator[None]:
    """Context manager to enable DTSTART/UNTIL type mismatch compatibility mode."""
    token = _dtstart_until_compat.set(True)
    try:
        yield
    finally:
        _dtstart_until_compat.reset(token)


def is_dtstart_until_compat_enabled() -> bool:
    """Check if DTSTART/UNTIL compatibility mode is enabled."""
    return _dtstart_until_compat.get()
