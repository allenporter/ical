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
from typing import Any, Optional, Union

from dateutil import rrule
import re

try:
    from pydantic.v1 import BaseModel, root_validator, validator
except ImportError:
    from pydantic import BaseModel, root_validator, validator  # type: ignore[no-redef, assignment]

_LOGGER = logging.getLogger(__name__)

_ZERO = datetime.timedelta(seconds=0)
_DEFAULT_TIME_DELTA = datetime.timedelta(hours=2)


def _parse_time(values: Any) -> datetime.timedelta | None:
    """Convert an offset from [+/-]hh[:mm[:ss]] to a valid timedelta pydantic format.

    The parse tree dict expects fields of hour, minutes, seconds (see tz_time rule in parser).
    """
    if isinstance(values, datetime.timedelta):
        return values
    if not values:
        return None
    if not isinstance(values, dict):
        raise ValueError("time was not parse tree dict or timedelta")

    if (hour := values["hour"]) is None:
        return None
    sign = 1
    if hour.startswith("+"):
        hour = hour[1:]
    elif hour.startswith("-"):
        sign = -1
        hour = hour[1:]
    minutes = values.get("minutes") or "0"
    seconds = values.get("seconds") or "0"
    return datetime.timedelta(
        seconds=sign * (int(hour) * 60 * 60 + int(minutes) * 60 + int(seconds))
    )


class RuleDay(BaseModel):
    """A date referenced in a timezone rule for a julian day."""

    day_of_year: int
    """A day of the year between 1 and 365, leap days never supported."""

    time: datetime.timedelta
    """Offset of time in current local time when the rule goes into effect, default of 02:00:00."""

    _parse_time = validator("time", pre=True, allow_reuse=True)(_parse_time)


class RuleDate(BaseModel):
    """A date referenced in a timezone rule."""

    month: int
    """A month between 1 and 12."""

    day_of_week: int
    """A day of the week between 0 (Sunday) and 6 (Saturday)."""

    week_of_month: int
    """A week number of the month (1 to 5) based on the first occurrence of day_of_week."""

    time: datetime.timedelta
    """Offset of time in current local time when the rule goes into effect, default of 02:00:00."""

    _parse_time = validator("time", pre=True, allow_reuse=True)(_parse_time)

    def as_rrule(self, dtstart: datetime.datetime | None = None) -> rrule.rrule:
        """Return a recurrence rule for this timezone occurrence (no start date)."""
        dst_start_weekday = self._rrule_byday(self._rrule_week_of_month)
        if dtstart:
            dtstart = dtstart.replace(hour=0, minute=0, second=0) + self.time
        return rrule.rrule(
            freq=rrule.YEARLY,
            bymonth=self.month,
            byweekday=dst_start_weekday,
            dtstart=dtstart,
        )

    @property
    def rrule_str(self) -> str:
        """Return a recurrence rule string for this timezone occurrence."""
        return ";".join(
            [
                "FREQ=YEARLY",
                f"BYMONTH={self.month}",
                f"BYDAY={self._rrule_week_of_month}{self._rrule_byday}",
            ]
        )

    def rrule_dtstart(self, start: datetime.datetime) -> datetime.datetime:
        """Return an rrule dtstart starting at the specified date with the time applied."""
        dt_start = start.replace(hour=0, minute=0, second=0) + self.time
        return next(iter(self.as_rrule(dt_start)))

    @property
    def _rrule_byday(self) -> rrule.weekday:
        """Return the dateutil weekday for this rule based on day_of_week."""
        return rrule.weekdays[(self.day_of_week - 1) % 7]

    @property
    def _rrule_week_of_month(self) -> int:
        """Return the byday modifier for the week of the month."""
        if self.week_of_month == 5:
            return -1
        return self.week_of_month


class RuleOccurrence(BaseModel):
    """A TimeZone rule occurrence."""

    name: str
    """The name of the timezone occurrence e.g. EST."""

    offset: datetime.timedelta
    """UTC offset for this timezone occurrence (not time added to local time)."""

    _parse_offset = validator("offset", pre=True, allow_reuse=True)(_parse_time)

    @validator("offset", allow_reuse=True)
    def negate_offset(cls, value: datetime.timedelta) -> datetime.timedelta:
        """Convert the offset from time added to local time to get UTC to a UTC offset."""
        result = _ZERO - value
        return result


class Rule(BaseModel):
    """A rule for evaluating future timezone transitions."""

    std: RuleOccurrence
    """An occurrence of a timezone transition for standard time."""

    dst: Optional[RuleOccurrence] = None
    """An occurrence of a timezone transition for standard time."""

    dst_start: Union[RuleDate, RuleDay, None] = None
    """Describes when dst goes into effect."""

    dst_end: Union[RuleDate, RuleDay, None] = None
    """Describes when dst ends (std starts)."""

    @root_validator(allow_reuse=True)
    def default_dst_offset(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Infer the default DST offset based on STD offset if not specified."""
        if values.get("dst") and not values["dst"].offset:
            # If the dst offset is omitted, it defaults to one hour ahead of standard time.
            values["dst"].offset = values["std"].offset + datetime.timedelta(hours=1)
        return values


class TzParser:
    """Parser for TZ strings into Rule objects."""


    def __init__(self, str: str) -> None:
        self._str = str
        self._pos = 0

    def parse(self) -> Rule:
        """Parse the TZ string into a Rule object."""
        if not (std := self._parse_tz_rule_occurrence()):
            raise ValueError(f"Unable to parse TZ string: {self._str}")

        dst = self._parse_tz_rule_occurrence()
        std_start = self._parse_tz_rule_date()
        std_end = self._parse_tz_rule_date()

        # either both dates are set or both are None
        if (std_start is None) != (std_end is None):
            raise ValueError(f"Unable to parse TZ string: {self._str}")

        # make sure we have reached the end of the string
        if self._pos < len(self._str):
            raise ValueError(
                f"Unable to parse TZ string: {self._str}. Unexpected end of string at position {self._pos}."
            )

        return Rule(std=std, dst=dst, dst_start=std_start, dst_end=std_end)

    def _parse_tz_rule_occurrence(self) -> RuleOccurrence | None:
        """Parse the TZ string into a RuleOccurrence object."""
        if not (match := _OFFSET_RE_PATTERN.match(self._str, self._pos)):
            return None

        self._pos = match.end()

        return RuleOccurrence(
            name=match.group("name"), offset=_parse_time(match.groupdict()) or _ZERO
        )

    def _parse_tz_rule_date(self) -> Union[RuleDate, RuleDay, None]:
        """Parse the TZ string into a RuleDate or RuleDay object."""
        if not (match := _START_END_RE_PATTERN.match(self._str, self._pos)):
            return None

        self._pos = match.end()

        if match["day_of_year"] is not None:
            return RuleDay(
                day_of_year=int(match.group("day_of_year")),
                time=_parse_time(match.groupdict()) or _DEFAULT_TIME_DELTA,
            )

        return RuleDate(
            month=int(match.group("month")),
            week_of_month=int(match.group("week_of_month")),
            day_of_week=int(match.group("day_of_week")),
            time=_parse_time(match.groupdict()) or _DEFAULT_TIME_DELTA,
        )


def build_offset_regex() -> re.Pattern[str]:
    """Create a regular expression for the given TZ string. Alternative implementation to pyparsing."""
    return re.compile(
        r"(?P<name>(\<[+\-]?\d+\>|[a-zA-Z]+))"   # name
        r"((?P<hour>[+-]?\d+)(?::(?P<minutes>\d{1,2})(?::(?P<seconds>\d{1,2}))?)?)?"  # offset
    )


def build_start_end_regex() -> re.Pattern[str]:
    # days in either julian (J prefix) or month.week.day (M prefix) format
    result = r",(J(?P<day_of_year>\d+)|M(?P<month>\d{1,2})\.(?P<week_of_month>\d)\.(?P<day_of_week>\d))"
    # time
    result += (
        r"(\/(?P<hour>[+-]?\d+)(?::(?P<minutes>\d{1,2})(?::(?P<seconds>\d{1,2}))?)?)?"
    )
    return re.compile(result)


def parse_tz_rule(tz_str: str) -> Rule:
    """Parse the TZ string into a Rule object."""
    parser = TzParser(tz_str)
    return parser.parse()


_OFFSET_RE_PATTERN = build_offset_regex()
_START_END_RE_PATTERN = build_start_end_regex()
