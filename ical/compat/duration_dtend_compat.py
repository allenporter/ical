"""Compatibility layer for resolving conflicting DURATION and DTEND values.

RFC 5545 Section 3.6.1 states that a VEVENT may specify either DTEND or
DURATION to describe its end, but never both. Some real-world calendar
generators emit both properties on the same event regardless (often
redundantly, with DTEND equal to DTSTART + DURATION). Strict parsing
rejects this outright; this compatibility fixup instead prefers the
more explicit DTEND value and discards DURATION.
"""

from collections.abc import Generator
import contextlib
import contextvars


_duration_dtend_compat = contextvars.ContextVar("duration_dtend_compat", default=False)


@contextlib.contextmanager
def enable_duration_dtend_compat() -> Generator[None]:
    """Context manager to enable DURATION/DTEND conflict compatibility mode."""
    token = _duration_dtend_compat.set(True)
    try:
        yield
    finally:
        _duration_dtend_compat.reset(token)


def is_duration_dtend_compat_enabled() -> bool:
    """Check if DURATION/DTEND conflict compatibility mode is enabled."""
    return _duration_dtend_compat.get()
