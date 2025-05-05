"""Compatibility layer for allowing extended timezones in iCalendar files."""

from collections.abc import Generator
import contextlib
import contextvars


_invalide_timezones = contextvars.ContextVar("invalid_timezones", default=False)
_extended_timezones = contextvars.ContextVar("extended_timezones", default=False)


@contextlib.contextmanager
def enable_extended_timezones() -> Generator[None]:
    """Context manager to allow extended timezones in iCalendar files."""
    token = _extended_timezones.set(True)
    try:
        yield
    finally:
        _extended_timezones.reset(token)


def is_extended_timezones_enabled() -> bool:
    """Check if extended timezones are enabled."""
    return _extended_timezones.get()


@contextlib.contextmanager
def enable_allow_invalid_timezones() -> Generator[None]:
    """Context manager to allow invalid timezones in iCalendar files."""
    token = _invalide_timezones.set(True)
    try:
        yield
    finally:
        _invalide_timezones.reset(token)


def is_allow_invalid_timezones_enabled() -> bool:
    """Check if allowing invalid timezones is enabled."""
    return _invalide_timezones.get()
