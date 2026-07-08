"""Compatibility layer for allowing invalid date formats in iCalendar files."""

from collections.abc import Generator
import contextlib
import contextvars

_invalid_dates = contextvars.ContextVar("invalid_dates", default=False)


@contextlib.contextmanager
def enable_allow_invalid_dates() -> Generator[None]:
    """Context manager to allow invalid dates in iCalendar files."""
    token = _invalid_dates.set(True)
    try:
        yield
    finally:
        _invalid_dates.reset(token)


def is_allow_invalid_dates_enabled() -> bool:
    """Check if allowing invalid dates is enabled."""
    return _invalid_dates.get()
