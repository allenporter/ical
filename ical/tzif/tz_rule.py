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

try:
    from pydantic.v1 import BaseModel, root_validator, validator
except ImportError:
    from pydantic import BaseModel, root_validator, validator  # type: ignore[no-redef, assignment]
from pyparsing import (
    Char,
    Combine,
    Group,
    Opt,
    ParseException,
    ParserElement,
    Word,
    alphas,
    nums,
)

_LOGGER = logging.getLogger(__name__)

_ZERO = datetime.timedelta(seconds=0)


def _parse_time(values: Any) -> int | str | datetime.timedelta:
    """Convert an offset from [+/-]hh[:mm[:ss]] to a valid timedelta pydantic format.

    The parse tree dict expects fields of hour, minutes, seconds (see tz_time rule in parser).
    """
    if not values:
        return 0
    if isinstance(values, (int, str, datetime.timedelta)):
        return values
    if not isinstance(values, dict):
        raise ValueError("time was not parse tree dict, timedelta, string, or int")
    hour = values["hour"]
    sign = 1
    if hour.startswith("+"):
        hour = hour[1:]
    elif hour.startswith("-"):
        sign = -1
        hour = hour[1:]
    minutes = values.get("minutes", "0")
    seconds = values.get("seconds", "0")
    return sign * (int(hour) * 60 * 60 + int(minutes) * 60 + int(seconds))


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


def _default_time_value(values: dict[str, Any]) -> dict[str, Any]:
    """Set a default time value when none is specified."""
    if "time" not in values:
        values["time"] = {"hour": "2"}
    return values


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

    _default_start_time = validator("dst_start", pre=True, allow_reuse=True)(
        _default_time_value
    )
    _default_end_time = validator("dst_end", pre=True, allow_reuse=True)(
        _default_time_value
    )

    @root_validator(allow_reuse=True)
    def default_dst_offset(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Infer the default DST offset based on STD offset if not specified."""
        if values.get("dst") and not values["dst"].offset:
            # If the dst offset is omitted, it defaults to one hour ahead of standard time.
            values["dst"].offset = values["std"].offset + datetime.timedelta(hours=1)
        return values


def parse_tz_rule(tz_str: str) -> Rule:
    """Parse the TZ string into a Rule object."""

    hour = Combine(Opt(Word("+-")) + Word(nums))
    tz_time = hour.set_results_name("hour") + Opt(
        ":"
        + Word(nums).set_results_name("minutes")
        + Opt(":" + Word(nums).set_results_name("seconds"))
    )

    name: ParserElement
    # Hack for inability to deal with both start word options
    if tz_str.startswith("<"):
        name = Combine(Char("<") + Opt(Word("+-")) + Word(nums) + Char(">"))
    else:
        name = Word(alphas)

    onset = name.set_results_name("name") + Group(Opt(tz_time)).set_results_name(
        "offset"
    )
    month_date = (
        "M"
        + Word(nums).set_results_name("month")
        + "."
        + Word(nums).set_results_name("week_of_month")
        + "."
        + Word(nums).set_results_name("day_of_week")
    )
    julian_date = "J" + Word(nums).set_results_name("day_of_year")
    # Hack for inabiliy to have a single rule with both date types
    if ",J" in tz_str:
        tz_days = julian_date
    else:
        tz_days = month_date
    tz_date = tz_days + Opt("/" + Group(tz_time).set_results_name("time"))

    tz_rule = (
        Group(onset).set_results_name("std")
        + Opt(Group(onset).set_results_name("dst"))
        + Opt(
            ","
            + Group(tz_date).set_results_name("dst_start")
            + ","
            + Group(tz_date).set_results_name("dst_end")
        )
    )
    if _LOGGER.isEnabledFor(logging.DEBUG):
        tz_rule.set_debug(flag=True)
    try:
        result = tz_rule.parse_string(tz_str, parse_all=True)
    except ParseException as err:
        raise ValueError(f"Unable to parse TZ string: {tz_str}") from err

    return Rule.parse_obj(result.as_dict())
