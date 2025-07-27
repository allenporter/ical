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


from dataclasses import dataclass
import datetime
import logging
import re
from typing import Any, Optional, Self, Union

from dateutil import rrule
from pydantic import BaseModel, field_validator, model_validator


_LOGGER = logging.getLogger(__name__)

_ZERO = datetime.timedelta(seconds=0)
_DEFAULT_TIME_DELTA = datetime.timedelta(hours=2)


def _parse_time(values: dict[str, Any]) -> datetime.timedelta | None:
    """Convert an offset from [+/-]hh[:mm[:ss]] to a valid timedelta pydantic format.

    The parse tree dict expects fields of hour, minutes, seconds (see tz_time rule in parser).
    """
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


@dataclass
class RuleDay:
    """A date referenced in a timezone rule for a julian day."""

    day_of_year: int
    """A day of the year between 1 and 365, leap days never supported."""

    time: datetime.timedelta
    """Offset of time in current local time when the rule goes into effect, default of 02:00:00."""


@dataclass
class RuleDate:
    """A date referenced in a timezone rule."""

    month: int
    """A month between 1 and 12."""

    day_of_week: int
    """A day of the week between 0 (Sunday) and 6 (Saturday)."""

    week_of_month: int
    """A week number of the month (1 to 5) based on the first occurrence of day_of_week."""

    time: datetime.timedelta
    """Offset of time in current local time when the rule goes into effect, default of 02:00:00."""

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


@dataclass
class RuleOccurrence:
    """A TimeZone rule occurrence."""

    name: str
    """The name of the timezone occurrence e.g. EST."""

    offset: datetime.timedelta
    """UTC offset for this timezone occurrence (not time added to local time)."""

    def __post_init__(self) -> None:
        """Convert the offset from time added to local time to get UTC to a UTC offset."""
        self.offset = _ZERO - self.offset


@dataclass
class Rule:
    """A rule for evaluating future timezone transitions."""

    std: RuleOccurrence
    """An occurrence of a timezone transition for standard time."""

    dst: Optional[RuleOccurrence] = None
    """An occurrence of a timezone transition for standard time."""

    dst_start: Union[RuleDate, RuleDay, None] = None
    """Describes when dst goes into effect."""

    dst_end: Union[RuleDate, RuleDay, None] = None
    """Describes when dst ends (std starts)."""

    def __post_init__(self) -> None:
        """Infer the default DST offset if not specified."""
        if self.dst and not self.dst.offset:
            # If the dst offset is omitted, it defaults to one hour ahead of standard time.
            self.dst.offset = self.std.offset + datetime.timedelta(hours=1)


# Regexp for parsing the TZ string
_OFFSET_RE_PATTERN: re.Pattern[str] = re.compile(
    r"(?P<name>(\<[+\-]?\d+\>|[a-zA-Z]+))"  # name
    r"((?P<hour>[+-]?\d+)(?::(?P<minutes>\d{1,2})(?::(?P<seconds>\d{1,2}))?)?)?"  # offset
)
_START_END_RE_PATTERN = re.compile(
    # days in either julian (J prefix) or month.week.day (M prefix) format
    r",(J(?P<day_of_year>\d+)|M(?P<month>\d{1,2})\.(?P<week_of_month>\d)\.(?P<day_of_week>\d))"
    # time
    r"(\/(?P<hour>[+-]?\d+)(?::(?P<minutes>\d{1,2})(?::(?P<seconds>\d{1,2}))?)?)?"
)


def _rule_occurrence_from_match(match: re.Match[str]) -> RuleOccurrence:
    """Create a rule occurrence from a regex match."""
    return RuleOccurrence(
        name=match.group("name"), offset=_parse_time(match.groupdict()) or _ZERO
    )


def _rule_date_from_match(match: re.Match[str]) -> Union[RuleDay, RuleDate]:
    """Create a rule date from a regex match."""
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


def parse_tz_rule(tz_str: str) -> Rule:
    """Parse the TZ string into a Rule object."""
    buffer = tz_str
    if (std_match := _OFFSET_RE_PATTERN.match(buffer)) is None:
        raise ValueError(f"Unable to parse TZ string: {tz_str}")
    buffer = buffer[std_match.end() :]
    if (dst_match := _OFFSET_RE_PATTERN.match(buffer)) is not None:
        buffer = buffer[dst_match.end() :]
    if (std_start := _START_END_RE_PATTERN.match(buffer)) is not None:
        buffer = buffer[std_start.end() :]
    if (std_end := _START_END_RE_PATTERN.match(buffer)) is not None:
        buffer = buffer[std_end.end() :]
    if (std_start is None) != (std_end is None):
        raise ValueError(
            f"Unable to parse TZ string, should have both or neither start and end dates: {tz_str}"
        )
    if buffer:
        raise ValueError(
            f"Unable to parse TZ string, unexpected trailing data: {tz_str}"
        )
    return Rule(
        std=_rule_occurrence_from_match(std_match),
        dst=_rule_occurrence_from_match(dst_match) if dst_match else None,
        dst_start=_rule_date_from_match(std_start) if std_start else None,
        dst_end=_rule_date_from_match(std_end) if std_end else None,
    )
