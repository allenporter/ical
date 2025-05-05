"""Compatibility layer for fixing invalid ical files.

This module provides a compatibility layer for handling invalid iCalendar files.
"""

from .make_compat import enable_compat_mode

__all__ = [
    "enable_compat_mode",
]
