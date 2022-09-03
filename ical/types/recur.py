"""Implementation of recurrence rules for calendar components.

This library handles the parsing of the rules from a pydantic model and
relies on the `dateutil.rrule` implementation for the actual implementation
of the date and time repetition.

Many existing libraries, such as UI components, support directly creating or
modifying recurrence rule strings. This is an example of creating a recurring
weekly event using a string RRULE, then printing out all of the start dates
of the expanded event timeline:

```python
from ical.calendar import Calendar
from ical.event import Event
from ical.types.recur import Recur

event = Event(
    summary='Monday meeting',
    start="2022-08-29T09:00:00",
    end="2022-08-29T09:30:00",
    recur=Recur.from_rrule("FREQ=WEEKLY;COUNT=3")
)
calendar = Calendar(events=[event])
print([ev.dtstart for ev in list(calendar.timeline)])
```

The above example will output something like this:
```
[datetime.datetime(2022, 8, 29, 9, 0),
 datetime.datetime(2022, 9, 5, 9, 0),
 datetime.datetime(2022, 9, 12, 9, 0)]
```
"""

from __future__ import annotations

import datetime
import enum
import re
from dataclasses import dataclass
from typing import Any, Optional, Union

from dateutil import rrule
from pydantic import BaseModel, Field

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE
from .date_time import DateTimeEncoder


class Weekday(str, enum.Enum):
    """Corresponds to a day of the week."""

    SUNDAY = "SU"
    MONDAY = "MO"
    TUESDAY = "TU"
    WEDNESDAY = "WE"
    THURSDAY = "TH"
    FRIDAY = "FR"
    SATURDAY = "SA"


@dataclass
class WeekdayValue:
    """Holds a weekday value and optional occurrence value."""

    weekday: Weekday
    """Day of the week value."""

    occurrence: Optional[int] = None
    """The occurrence value indicates the nth occurrence.
    Indicates the nth occurrence of a specific day within the MONTHLY or
    YEARLY "RRULE". For example +1 represents the first Monday of the
    month, or -1 represents the last Monday of the month.
    """


class Frequency(str, enum.Enum):
    """Type of recurrence rule.
    Frequencies SECONDLY, MINUTELY, HOURLY, YEARLY are not supported.
    """

    DAILY = "DAILY"
    """Repeating events based on an interval of a day or more."""

    WEEKLY = "WEEKLY"
    """Repeating events based on an interval of a week or more."""

    MONTHLY = "MONTHLY"
    """Repeating events based on an interval of a month or more."""

    YEARLY = "YEARLY"
    """Repeating events based on an interval of a year or more."""


RRULE_FREQ = {
    Frequency.DAILY: rrule.DAILY,
    Frequency.WEEKLY: rrule.WEEKLY,
    Frequency.MONTHLY: rrule.MONTHLY,
    Frequency.YEARLY: rrule.YEARLY,
}
RRULE_WEEKDAY = {
    Weekday.MONDAY: rrule.MO,
    Weekday.TUESDAY: rrule.TU,
    Weekday.WEDNESDAY: rrule.WE,
    Weekday.THURSDAY: rrule.TH,
    Weekday.FRIDAY: rrule.FR,
    Weekday.SATURDAY: rrule.SA,
    Weekday.SUNDAY: rrule.SU,
}
WEEKDAY_REGEX = re.compile(r"([-+]?[0-9]*)([A-Z]+)")

RecurInputDict = dict[
    str, Union[datetime.datetime, str, list[str], list[dict[str, str]]]
]


@DATA_TYPE.register("RECUR")
class Recur(BaseModel):
    """A type used to identify properties that contain a recurrence rule specification.

    The by properties reduce or limit the number of occurrences generated. Only by day
    of the week and by month day are supported.
    Parts of rfc5545 recurrence spec not supported:
      By second, minute, hour
      By yearday, weekno, month
      Wkst rules are
      Bysetpos rules
      Negative "by" rules.
    """

    freq: Frequency

    until: Union[datetime.datetime, datetime.date, None] = None
    """The inclusive end date of the recurrence, or the last instance."""

    count: Optional[int] = None
    """The number of occurrences to bound the recurrence."""

    interval: int = 1
    """Interval at which the recurrence rule repeats."""

    by_weekday: list[WeekdayValue] = Field(alias="byday", default_factory=list)
    """Supported days of the week."""

    by_month_day: list[int] = Field(alias="bymonthday", default_factory=list)
    """Days of the month between 1 to 31."""

    by_month: list[int] = Field(alias="bymonth", default_factory=list)
    """Month number between 1 and 12."""

    def as_rrule(self, dtstart: datetime.datetime | datetime.date) -> rrule.rrule:
        """Create a dateutil rrule for the specified event."""
        if (freq := RRULE_FREQ.get(self.freq)) is None:
            raise ValueError(f"Unsupported frequency in rrule: {self.freq}")

        byweekday: list[rrule.weekday] | None = None
        if self.by_weekday:
            byweekday = [
                RRULE_WEEKDAY[weekday.weekday](
                    1 if weekday.occurrence is None else weekday.occurrence
                )
                for weekday in self.by_weekday
            ]
        return rrule.rrule(
            freq=freq,
            dtstart=dtstart,
            interval=self.interval,
            count=self.count,
            until=self.until,
            byweekday=byweekday,
            bymonthday=self.by_month_day if self.by_month_day else None,
            bymonth=self.by_month if self.by_month else None,
            cache=True,
        )

    @classmethod
    def from_rrule(cls, rrule_str: str) -> Recur:
        """Create a Recur object from an RRULE string."""
        return Recur.parse_obj(cls.__parse_property_value__(rrule_str))

    class Config:
        """Pydantic model configuration."""

        validate_assignment = True
        allow_population_by_field_name = True

    @classmethod
    def __encode_property_value__(cls, data: dict[str, Any]) -> str:
        """Encode the recurence rule in ICS format."""
        result = []
        for key, value in data.items():
            # Need to encode based on field type also using json encoders
            if key in ("bymonthday", "bymonth"):
                if not value:
                    continue
                value = ",".join([str(val) for val in value])
            elif key == "byday":
                values = []
                for weekday_dict in value:
                    weekday = weekday_dict["weekday"]
                    occurrence = weekday_dict.get("occurrence")
                    if occurrence is None:
                        occurrence = ""
                    values.append(f"{occurrence}{weekday}")
                value = ",".join(values)
            if not value:
                continue
            result.append(f"{key.upper()}={value}")
        return ";".join(result)

    @classmethod
    def __parse_property_value__(cls, prop: Any) -> RecurInputDict:
        """Parse the recurrence rule text as a dictionary as Pydantic input.
        An input rule like 'FREQ=YEARLY;BYMONTH=4' is converted
        into dictionary.
        """
        if isinstance(prop, str):
            value = prop
        elif not isinstance(prop, ParsedProperty):
            raise ValueError(f"Expected recurrence rule as ParsedProperty: {prop}")
        else:
            value = prop.value
        result: RecurInputDict = {}
        for part in value.split(";"):
            if "=" not in part:
                raise ValueError(
                    f"Recurrence rule had unexpected format missing '=': {prop.value}"
                )
            key, value = part.split("=")
            key = key.lower()
            if key == "until":
                result[key] = DateTimeEncoder.__parse_property_value__(
                    ParsedProperty(name="ignored", value=value)
                )
            elif key in ("bymonthday", "bymonth"):
                result[key] = value.split(",")
            elif key == "byday":
                # Build inputs for WeekdayValue dataclass
                results: list[dict[str, str]] = []
                for value in value.split(","):
                    if not (match := WEEKDAY_REGEX.fullmatch(value)):
                        raise ValueError(
                            f"Expected value to match UTC-OFFSET pattern: {value}"
                        )
                    occurrence, weekday = match.groups()
                    weekday_result = {"weekday": weekday}
                    if occurrence:
                        weekday_result["occurrence"] = occurrence
                    results.append(weekday_result)
                result[key] = results
            else:
                result[key] = value
        return result
