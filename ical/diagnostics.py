"""Library for diagnostics or debugging information about calendars."""

from collections.abc import Generator
import itertools


__all__ = [
    "redact_ics",
]


COMPONENT_ALLOWLIST = {
    "BEGIN",
    "END",
    "DTSTAMP",
    "CREATED",
    "LAST-MODIFIED",
    "DTSTART",
    "DTEND",
    "RRULE",
    "PRODID",
}
REDACT = "***"
MAX_CONTENTLINES = 5000


def component_sep(contentline: str) -> int:
    """Return the component prefix index in the string."""
    colon = contentline.find(":")
    semi = contentline.find(";")
    if colon > -1 and semi > -1:
        return min(colon, semi)
    if colon > -1:
        return colon
    return semi


def redact_contentline(contentline: str) -> str:
    """Return a redacted version of an ics content line."""
    if (i := component_sep(contentline)) and i > -1:
        component = contentline[0:i]
        if component in COMPONENT_ALLOWLIST:
            return contentline
        return f"{component}:{REDACT}"
    return REDACT


def redact_ics(ics: str) -> Generator[str, None, None]:
    """Generate redacted ics file contents one line at a time."""
    contentlines = ics.split("\n")
    for contentline in itertools.islice(contentlines, MAX_CONTENTLINES):
        if contentline:
            yield redact_contentline(contentline)
