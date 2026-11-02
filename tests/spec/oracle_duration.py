"""Clean-room RFC 5545 Section 3.3.6 / 3.8.2.5 DURATION parser and canonicalizer.

Uses ONLY the Python standard library. Shared by the invariant layer and the
reference store oracle so duration syntax, positivity, and DATE unit rules are
enforced identically.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Any

from .oracle_policy import StoreError

_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])?P"
    r"(?:(?P<weeks>\d+)W"
    r"|(?P<days>\d+)D(?:T(?P<d_hours>\d+)H(?:(?P<d_mins>\d+)M(?:(?P<d_secs>\d+)S)?)?"
    r"|T(?P<dm_mins>\d+)M(?:(?P<dm_secs>\d+)S)?"
    r"|T(?P<ds_secs>\d+)S)?"
    r"|T(?:(?P<hours>\d+)H(?:(?P<mins>\d+)M(?:(?P<secs>\d+)S)?)?"
    r"|(?P<m_mins>\d+)M(?:(?P<m_secs>\d+)S)?"
    r"|(?P<s_secs>\d+)S))$"
)


@dataclasses.dataclass(frozen=True)
class ParsedDuration:
    """A parsed RFC 5545 DURATION value with unit-granularity metadata."""

    raw: str
    delta: datetime.timedelta
    has_time_part: bool


def parse_rfc5545_duration(raw: Any, field_name: str = "duration") -> ParsedDuration:
    """Parse an RFC 5545 Section 3.3.6 DURATION string, rejecting negative values."""
    if not isinstance(raw, str) or not raw:
        raise StoreError(f"Invalid {field_name} value: {raw!r}")
    match = _DURATION_RE.match(raw)
    if match is None:
        raise StoreError(f"Malformed RFC 5545 DURATION for {field_name}: {raw!r}")
    if match.group("sign") == "-":
        raise StoreError(
            f"Negative DURATION is not permitted on components ({field_name}={raw!r})"
        )
    groups = {k: int(v) for k, v in match.groupdict().items() if k != "sign" and v}
    weeks = groups.get("weeks", 0)
    days = groups.get("days", 0)
    hours = groups.get("d_hours", 0) + groups.get("hours", 0)
    minutes = (
        groups.get("d_mins", 0)
        + groups.get("dm_mins", 0)
        + groups.get("mins", 0)
        + groups.get("m_mins", 0)
    )
    seconds = (
        groups.get("d_secs", 0)
        + groups.get("dm_secs", 0)
        + groups.get("ds_secs", 0)
        + groups.get("secs", 0)
        + groups.get("m_secs", 0)
        + groups.get("s_secs", 0)
    )
    delta = datetime.timedelta(
        weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return ParsedDuration(raw=raw, delta=delta, has_time_part="T" in raw)


def try_parse_duration(raw: Any) -> ParsedDuration | None:
    """Parse an RFC 5545 DURATION string, returning None if absent or invalid."""
    if raw is None:
        return None
    try:
        return parse_rfc5545_duration(raw)
    except StoreError:
        return None
