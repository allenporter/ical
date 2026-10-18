"""Library for diagnostics or debugging information about calendars."""

from __future__ import annotations

from collections.abc import Generator
import itertools

from ical.parsing.component import unfolded_lines


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


def redact_contentline(contentline: str, component_allowlist: set[str]) -> str:
    """Return a redacted version of an ics content line."""
    if (i := component_sep(contentline)) and i > -1:
        component = contentline[0:i]
        if component in component_allowlist:
            return contentline
        return f"{component}:{REDACT}"
    return REDACT


def redact_ics(
    ics: str,
    max_contentlines: int = MAX_CONTENTLINES,
    component_allowlist: set[str] | None = None,
) -> Generator[str, None, None]:
    """Generate redacted ics file contents one line at a time."""
    if component_allowlist is None:
        component_allowlist = COMPONENT_ALLOWLIST
    contentlines = unfolded_lines(ics)
    raw_lines = ics.splitlines()
    raw_idx = 0
    raw_len = len(raw_lines)
    emitted = 0
    for contentline in itertools.islice(contentlines, max_contentlines):
        fold_count = 0
        if raw_idx < raw_len:
            raw_idx += 1
            while (
                raw_idx < raw_len
                and raw_lines[raw_idx]
                and raw_lines[raw_idx][0] in (" ", "\t")
            ):
                fold_count += 1
                raw_idx += 1
        if contentline:
            if emitted >= max_contentlines:
                break
            redacted = redact_contentline(contentline, component_allowlist)
            yield redacted
            emitted += 1
            if redacted.endswith(f":{REDACT}") or redacted == REDACT:
                for _ in range(fold_count):
                    if emitted >= max_contentlines:
                        break
                    yield REDACT
                    emitted += 1
