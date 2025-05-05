"""Compatibility layer for Office 365 and Exchange Server iCalendar files.

This module provides a context manager that can allow invalid calendar files
to be parsed.
"""

import contextlib
from collections.abc import Generator
import logging
import re

from . import timezone_compat


_LOGGER = logging.getLogger(__name__)

# Capture group that extracts the PRODID from the ics content.
_PRODID_RE = r"PRODID:(?P<prodid>.*[^\\r\\n]+)"

_EXCHANGE_PRODID = "Microsoft Exchange Server"


def _get_prodid(ics: str) -> str | None:
    """Extract the PRODID from the iCalendar content."""
    match = re.search(_PRODID_RE, ics)
    if match:
        _LOGGER.debug("Extracted PRODID: %s", match)
        return match.group("prodid")
    return None


@contextlib.contextmanager
def enable_compat_mode(ics: str) -> Generator[str]:
    """Enable compatibility mode to fix known broken calendar content."""

    # Check if the PRODID is from Microsoft Exchange Server
    prodid = _get_prodid(ics)
    if prodid and _EXCHANGE_PRODID in prodid:
        _LOGGER.debug("Enabling compatibility mode for Microsoft Exchange Server")
        # Enable compatibility mode for Microsoft Exchange Server
        with timezone_compat.enable_allow_invalid_timezones(), timezone_compat.enable_extended_timezones():
            yield ics
    else:
        _LOGGER.debug("No compatibility mode needed")
        # No compatibility mode needed
        yield ics
