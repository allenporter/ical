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
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Union

from dateutil import rrule
try:
    from pydantic.v1 import BaseModel, Field
except ImportError:
    from pydantic import BaseModel, Field # type: ignore[assignment]

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE
from .date import DateEncoder
from .date_time import DateTimeEncoder

_LOGGER = logging.getLogger(__name__)


# Note: This can be StrEnum in python 3.11 and higher
class Weekday(str, enum.Enum):
    """Corresponds to a day of the week."""

    SUNDAY = "SU"
    MONDAY = "MO"
    TUESDAY = "TU"
    WEDNESDAY = "WE"
    THURSDAY = "TH"
    FRIDAY = "FR"
    SATURDAY = "SA"

    def __str__(self) -> str:
        """Return string representation."""
        return self.value


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

    def __str__(self) -> str:
        """Return the WeekdayValue as an encoded string."""
        return f"{self.occurrence or ''}{self.weekday}"


    def as_rrule_weekday(self) -> rrule.weekday:
        """Convert the occurrence to a weekday value."""
        wd = RRULE_WEEKDAY[self.weekday]
        if self.occurrence is None:
            return wd
        return wd(self.occurrence)


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


class Range(str, enum.Enum):
    """Specifies an effective range of recurrence instances for a recurrence id.

    This is used when modifying a recurrence rule and specifying that the action
    applies to all events following the specified event.
    """

    NONE = "NONE"
    """No range is specified, just a single instance."""

    THIS_AND_FUTURE = "THISANDFUTURE"
    """The range of the recurrence identifier and all subsequent values."""


@DATA_TYPE.register(disable_value_param=True)
class RecurrenceId(str):
    """Identifies a specific instance of a recurring calendar component.

    A property type used in conjunction with the "UID" and "SEQUENCE" properties
    to specify a specific instance of a recurrent calendar component.

    The full range of a recurrence set is referenced by the "UID". The
    recurrence id can reference a specific instance within the set.
    """

    @classmethod
    def to_value(cls, recurrence_id: str) -> datetime.datetime | datetime.date:
        """Convert a string RecurrenceId into a date or time value."""
        errors = []
        try:
            date_value = DateEncoder.__parse_property_value__(
                ParsedProperty(name="", value=recurrence_id)
            )
            if date_value:
                return date_value
        except ValueError as err:
            errors.append(err)

        try:
            date_time_value = DateTimeEncoder.__parse_property_value__(
                ParsedProperty(name="", value=recurrence_id)
            )
            if date_time_value:
                return date_time_value
        except ValueError as err:
            errors.append(err)

        raise ValueError(f"Unable to parse date/time value: {errors}")

    @classmethod
    def __parse_property_value__(cls, value: Any) -> RecurrenceId:
        """Parse a calendar user address."""
        if isinstance(value, ParsedProperty):
            value = cls._parse_value(value.value)
        if isinstance(value, str):
            value = cls._parse_value(value)
        elif isinstance(value, datetime.datetime):
            value = DateTimeEncoder.__encode_property_json__(value)
        elif isinstance(value, datetime.date):
            value = DateEncoder.__encode_property_json__(value)
        else:
            value = str(value)
        return RecurrenceId(value)

    @classmethod
    def _parse_value(cls, value: str) -> datetime.datetime | datetime.date | str:
        try:
            return cls.to_value(value)
        except ValueError:
            pass
        return str(value)


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
    str,
    Union[datetime.datetime, datetime.date, str, list[str], list[dict[str, str]], None],
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

    by_setpos: list[int] = Field(alias="bysetpos", default_factory=list)
    """Values that corresponds to the nth occurrence within the set of instances."""

    def as_rrule(self, dtstart: datetime.datetime | datetime.date) -> rrule.rrule:
        """Create a dateutil rrule for the specified event."""
        if (freq := RRULE_FREQ.get(self.freq)) is None:
            raise ValueError(f"Unsupported frequency in rrule: {self.freq}")

        byweekday: list[rrule.weekday] | None = None
        if self.by_weekday:
            byweekday = [
                weekday.as_rrule_weekday()
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
            bysetpos=self.by_setpos,
            cache=True,
        )

    def as_rrule_str(self) -> str:
        """Return the Recur instance as an RRULE string."""
        return self.__encode_property_value__(
            self.dict(by_alias=True, exclude_none=True, exclude_defaults=True)
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
        """Encode the recurrence rule in ICS format."""
        result = []
        for key, value in data.items():
            # Need to encode based on field type also using json encoders
            if key in ("bymonthday", "bymonth", "bysetpos"):
                if not value:
                    continue
                value = ",".join([str(val) for val in value])
            elif key == "byday":
                values = []
                for weekday_value in value:
                    if isinstance(weekday_value, dict):
                        weekday_value = WeekdayValue(**weekday_value)
                    values.append(str(weekday_value))
                value = ",".join(values)
            elif isinstance(value, datetime.datetime):
                value = DateTimeEncoder.__encode_property_json__(value)
            elif isinstance(value, datetime.date):
                value = DateEncoder.__encode_property_json__(value)
            elif isinstance(value, enum.Enum):
                value = value.name
            if not value:
                continue
            result.append(f"{key.upper()}={value}")
        return ";".join(result)

    @classmethod
    def __parse_property_value__(  # pylint: disable=too-many-branches
        cls, prop: Any
    ) -> RecurInputDict:
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
                new_value: datetime.datetime | datetime.date | None
                try:
                    new_value = DateTimeEncoder.__parse_property_value__(
                        ParsedProperty(name="ignored", value=value)
                    )
                except ValueError:
                    new_value = DateEncoder.__parse_property_value__(
                        ParsedProperty(name="ignored", value=value)
                    )
                result[key] = new_value
            elif key in ("bymonthday", "bymonth", "bysetpos"):
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
