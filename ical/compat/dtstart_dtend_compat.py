"""Compatibility layer for resolving DTSTART and DTEND type mismatches.

RFC 5545 Section 3.8.2.2 states that the value type of DTEND must match the value
type of DTSTART (both DATE or both DATE-TIME). Some real-world calendar feeds
(such as Edlio webcal calendars) emit DTSTART as DATE and DTEND as DATE-TIME
(e.g., DTSTART;VALUE=DATE:20260526 and DTEND;TZID=...:20260529T235959), or vice-versa.
Strict parsing rejects these files with a CalendarParseError. This compatibility
fixup coerces DTEND to match DTSTART's value type.
"""

from collections.abc import Generator
import contextlib
import contextvars


_dtstart_dtend_compat = contextvars.ContextVar("dtstart_dtend_compat", default=False)


@contextlib.contextmanager
def enable_dtstart_dtend_compat() -> Generator[None]:
    """Context manager to enable DTSTART/DTEND type mismatch compatibility mode."""
    token = _dtstart_dtend_compat.set(True)
    try:
        yield
    finally:
        _dtstart_dtend_compat.reset(token)


def is_dtstart_dtend_compat_enabled() -> bool:
    """Check if DTSTART/DTEND type mismatch compatibility mode is enabled."""
    return _dtstart_dtend_compat.get()
