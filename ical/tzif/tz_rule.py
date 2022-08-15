"""Library for parsing TZ rules.

TZ supports these two formats

No DST: std offset
  - std: Name of the timezone
  - offset: Time added to local time to get UTC
  Example: EST+5

DST: std offset dst [offset],start[/time],end[/time]
  - dst: Name of the Daylight savings time timezone
  - offset: Defaults to 1 hour ahead of STD offset if not specified
  - start & end: Time period when DST is in effect. The start/end have
    the following formats:
      Jn: A julian day between 1 and 365 (Feb 29th never counted)
      n: A julian day between 0 and 364 (Feb 29th is counted in leap years)
      Mm.w.d:
          m: Month between 1 and 12
          d: Between 0 (Sunday) and 6 (Saturday)
          w: Between 1 and 5. Week 1 is first week d occurs
      The time field is in hh:mm:ss. The hour can be 167 to -167.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, root_validator, validator

_LOGGER = logging.getLogger(__name__)

_ZERO = datetime.timedelta(seconds=0)


def _parse_time(value: str) -> str | int:
    """Convert an offset from [+/-]hh[:mm[:ss]] to a valid timedelta pydantic format."""
    if not value:
        return 0
    parts = value.split(":")
    if len(parts) < 2:
        parts.append("00")
    if len(parts) < 3:
        parts.append("00")
    if parts[0].startswith("+"):  # Strip a leading +
        parts[0] = parts[0][1:]
    return ":".join(parts)


@dataclass
class RuleDate:
    """A date referenced in a timezone rule."""

    month: int
    """A month between 1 and 12."""

    day_of_week: int
    """A day of the week between 0 (Sunday) and 6 (Saturday)."""

    week_of_month: int
    """A week number of the month (1 to 5) based on the first occurrence of day_of_week."""

    time: Optional[datetime.time] = None
    """Time in current local time when the rule goes into effect, defaulting to 02:00:00."""

    _parse_time = validator("time", pre=True, allow_reuse=True)(_parse_time)

    @validator("month", pre=True)
    def parse_month(cls, value: str) -> str:
        """Convert a TZ month to an integer."""
        if not value.startswith("M"):
            raise ValueError(f"Unexpected month date format missing M prefix: {value}")
        return value[1:]


@dataclass
class RuleOccurrence:
    """A TimeZone rule occurrence."""

    name: str
    """The name of the timezone occurrence e.g. EST."""

    offset: datetime.timedelta
    """UTC offset for this timezone occurrence (not time added to local time)."""

    _parse_offset = validator("offset", pre=True, allow_reuse=True)(_parse_time)

    @validator("offset")
    def negate_offset(cls, value: datetime.timedelta) -> datetime.timedelta:
        """Convert the offset from time added to local time to get UTC to a UTC offset."""
        return _ZERO - value


# RE for matching: std offset dst [offset]
_OCURRENCE_RE = re.compile(
    r"^(?P<std>[a-zA-Z]+[-+:0-9]*?)(?P<dst>[a-zA-Z]+[-+0-9]*?)?$"
)
_OCURRENCE_SPLIT_RE = re.compile(r"^(?P<name>[a-zA-Z]+)(?P<offset>[-+:0-9]+)?$")


def _parse_rule_occurrence(value: str) -> dict[str, Any]:
    """Rule for parsing a rule occurrence into input for RuleOcurrence."""
    if not (match := _OCURRENCE_SPLIT_RE.match(value)):
        raise ValueError(f"Occurrence did not match pattern: {value}")
    (name, offset) = match.group("name", "offset")
    if not offset:
        offset = ""
    return {"name": name, "offset": offset}


def _parse_rule_date(value: str) -> dict[str, Any]:
    """Rule for parsing a rule occurrence into input for RuleOcurrence."""
    _LOGGER.debug("_parse_rule_date=%s", value)
    if "/" in value:
        (date, time) = value.split("/", maxsplit=2)
    else:
        date = value
        time = "02:00:00"  # If omitted, the default is 02:00:00
    parts = date.split(".")
    if len(parts) != 3:
        raise ValueError(f"Rule date had unexpected number of parts: {value}")
    return {
        "month": parts[0],
        "week_of_month": parts[1],
        "day_of_week": parts[2],
        "time": time,
    }


class Rule(BaseModel):
    """A rule for evaluating future timezone transitions."""

    std: RuleOccurrence
    """An occurrence of a timezone transition for standard time."""

    dst: Optional[RuleOccurrence] = None
    """An occurrence of a timezone transition for standard time."""

    dst_start: Optional[RuleDate] = None
    """Describes when dst goes into effect."""

    dst_end: Optional[RuleDate] = None
    """Describes when dst ends."""

    _parse_std = validator("std", pre=True, allow_reuse=True)(_parse_rule_occurrence)
    _parse_dst = validator("dst", pre=True, allow_reuse=True)(_parse_rule_occurrence)
    _parse_dst_start = validator("dst_start", pre=True, allow_reuse=True)(
        _parse_rule_date
    )
    _parse_dst_end = validator("dst_end", pre=True, allow_reuse=True)(_parse_rule_date)

    @root_validator
    def default_dst_offset(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Infer the default DST offset based on STD offset if not specified."""
        if values.get("dst") and not values["dst"].offset:
            # If the dst offset is omitted, it defaults to one hour ahead of standard time.
            values["dst"].offset = values["std"].offset + datetime.timedelta(hours=1)
            _LOGGER.info("std offset=%s", values["std"].offset)
            _LOGGER.info("new dst offset=%s", values["dst"].offset)
        return values


def parse_tz_rule(tz_str: str) -> Rule:
    """Parse a Rule object from a string."""
    parts = tz_str.split(",")
    if len(parts) not in (1, 3):
        raise ValueError(f"TZ rule had unexpected ',': {tz_str}")
    match = _OCURRENCE_RE.match(parts[0])
    if not match:
        raise ValueError(f"Unable to parse TZ rule occurrence: {tz_str}")
    result = {
        "std": match.group("std"),
    }
    if dst := match.group("dst"):
        result["dst"] = dst
    if len(parts) == 3:
        result.update(
            {
                "dst_start": parts[1],
                "dst_end": parts[2],
            }
        )
    return Rule.parse_obj(result)
