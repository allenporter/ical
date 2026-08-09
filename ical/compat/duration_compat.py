"""Compatibility layer for allowing non-conforming duration formats in iCalendar files."""

from collections.abc import Generator
import contextlib
import contextvars

_duration_compat = contextvars.ContextVar("duration_compat", default=False)


@contextlib.contextmanager
def enable_duration_compat() -> Generator[None]:
    """Context manager to allow non-conforming duration formats in iCalendar files."""
    token = _duration_compat.set(True)
    try:
        yield
    finally:
        _duration_compat.reset(token)


def is_duration_compat_enabled() -> bool:
    """Check if non-conforming duration compatibility is enabled."""
    return _duration_compat.get()
