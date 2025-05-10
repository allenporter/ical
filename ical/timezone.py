"""A grouping of component properties that defines a time zone.

An iCal timezone is a complete description of a timezone, separate
from the built-in timezones used by python datetime objects. You can
think of this like fully persisting all timezone informating referenced
in the calendar for dates to reference. Timezones are captured to
unambiguously describe time information to aid in interoperability between
different calendaring systems.
"""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import copy
import traceback
import datetime
import enum
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Union

from dateutil.rrule import rruleset

try:
    from pydantic.v1 import Field, root_validator, validator
except ImportError:
    from pydantic import Field, root_validator, validator  # type: ignore[no-redef, assignment]

from .component import ComponentModel
from .iter import MergedIterable, RecurIterable
from .parsing.property import ParsedProperty
from .types import Recur, Uri, UtcOffset
from .tzif import timezoneinfo, tz_rule

__all__ = [
    "Timezone",
    "Observance",
]

_LOGGER = logging.getLogger(__name__)


# Assume that all tzif timezone rules start at an arbitrary old date. This library
# typically only works with "go forward" dates, so we don't need to be completely
# accurate and use the historical database of times.
_TZ_START = datetime.datetime(2010, 1, 1, 0, 0, 0)

_ZERO = datetime.timedelta(0)


class Observance(ComponentModel):
    """A sub-component with properties for a set of timezone observances."""

    # Has an alias of 'start'
    dtstart: datetime.datetime = Field(default_factory=None)
    """The first onset datetime (local time) for the observance."""

    tz_offset_to: UtcOffset = Field(alias="tzoffsetto")
    """Gives the UTC offset for the time zone when this observance is in use."""

    tz_offset_from: UtcOffset = Field(alias="tzoffsetfrom")
    """The timezone offset used when the onset of this time zone observance begins.

    The tz_offset_from and dtstart define the effective onset for the time zone sub-component.
    """

    rrule: Optional[Recur] = None
    """The recurrence rule for the onset of observances defined in this sub-component."""

    rdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    """A rule to determine the onset of the observances defined in this sub-component."""

    tz_name: list[str] = Field(alias="tzname", default_factory=list)
    """A name for the observance."""

    comment: list[str] = Field(default_factory=list)
    """Descriptive explanatory text."""

    extras: list[ParsedProperty] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        """Initialize Timezone."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        super().__init__(**data)

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the start of the observance."""
        return self.dtstart

    def as_ruleset(self) -> rruleset:
        """Represent the occurrence as a rule of repeated dates or datetimes."""
        ruleset = rruleset()
        if self.rrule:
            ruleset.rrule(self.rrule.as_rrule(self.dtstart))
        for rdate in self.rdate:
            ruleset.rdate(rdate)  # type: ignore[no-untyped-call]
        return ruleset

    @validator("dtstart", allow_reuse=True)
    def verify_dtstart_local_time(cls, value: datetime.datetime) -> datetime.datetime:
        """Validate that dtstart is specified in a local time."""
        if value.utcoffset() is not None:
            raise ValueError(f"Start time must be in local time format: {value}")
        return value


class _ObservanceType(str, enum.Enum):
    """Type of a timezone observance."""

    STANDARD = "STANDARD"
    DAYLIGHT = "DAYLIGHT"


@dataclass
class _ObservanceInfo:
    """Object holding observance information."""

    observance_type: _ObservanceType
    observance: Observance

    def get(
        self,
        value: datetime.datetime | datetime.date,
    ) -> tuple[datetime.datetime | datetime.date, "_ObservanceInfo"]:
        """Adapt for an iterator over observances."""
        return (value, self)


class Timezone(ComponentModel):
    """A single free/busy entry on a calendar.

    A Timezone must have at least one definition of a standard or daylight
    sub-component.
    """

    tz_id: str = Field(alias="tzid")
    """An identifier for this Timezone, unique within a calendar."""

    standard: list[Observance] = Field(default_factory=list)
    """Describes the base offset from UTC for the time zone."""

    daylight: list[Observance] = Field(default_factory=list)
    """Describes adjustments made to account for changes in daylight hours."""

    tz_url: Optional[Uri] = Field(alias="tzurl", default=None)
    """Url that points to a published timezone definition."""

    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    """Specifies the date and time that this time zone was last updated."""

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    @classmethod
    def from_tzif(cls, key: str, start: datetime.datetime = _TZ_START) -> Timezone:
        """Create a new Timezone from a tzif data source."""
        info = timezoneinfo.read(key)
        rule = info.rule
        if not rule:
            raise ValueError("Unsupported timezoneinfo had no rule")

        dst_offset = rule.std.offset
        if rule.dst and rule.dst.offset:
            dst_offset = rule.dst.offset

        std_timezone_info = Observance(
            tz_name=[rule.std.name],
            tz_offset_to=UtcOffset(offset=rule.std.offset),
            tz_offset_from=UtcOffset(dst_offset),
            dtstart=start,
        )
        daylight = []
        if (
            rule.dst
            and rule.dst_start
            and isinstance(rule.dst_start, tz_rule.RuleDate)
            and rule.dst_end
            and isinstance(rule.dst_end, tz_rule.RuleDate)
        ):
            std_timezone_info.rrule = Recur.parse_obj(
                Recur.__parse_property_value__(rule.dst_end.rrule_str)
            )
            std_timezone_info.dtstart = rule.dst_end.rrule_dtstart(start)
            daylight.append(
                Observance(
                    tz_name=[rule.dst.name],
                    tz_offset_to=UtcOffset(offset=rule.dst.offset),
                    tz_offset_from=UtcOffset(offset=rule.std.offset),
                    rrule=Recur.parse_obj(
                        Recur.__parse_property_value__(rule.dst_start.rrule_str)
                    ),
                    dtstart=rule.dst_start.rrule_dtstart(start),
                )
            )
        # https://github.com/pydantic/pydantic/issues/3923 is not working even
        # when the model config allows population by name. Try again on v2.
        return Timezone(tz_id=key, standard=[std_timezone_info], daylight=daylight)  # type: ignore[call-arg]

    def _observances(
        self,
    ) -> Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]:
        return MergedIterable(self._std_observances() + self._dst_observances())

    def _std_observances(
        self,
    ) -> list[Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]]:
        iters: list[
            Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]
        ] = []
        for observance in self.standard:
            iters.append(
                RecurIterable(
                    _ObservanceInfo(_ObservanceType.STANDARD, observance).get,
                    observance.as_ruleset(),
                )
            )
        return iters

    def _dst_observances(
        self,
    ) -> list[Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]]:
        iters: list[
            Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]
        ] = []
        for observance in self.daylight:
            iters.append(
                RecurIterable(
                    _ObservanceInfo(_ObservanceType.DAYLIGHT, observance).get,
                    observance.as_ruleset(),
                )
            )
        return iters

    def get_observance(self, value: datetime.datetime) -> _ObservanceInfo | None:
        """Return the specified observence for the specified date."""
        if value.tzinfo is not None:
            raise ValueError("Start time must be in local time format")
        last_observance_info: _ObservanceInfo | None = None
        for dt_start, observance_info in self._observances():
            if dt_start > value:
                return last_observance_info
            last_observance_info = observance_info
        return last_observance_info

    @root_validator
    def parse_required_timezoneinfo(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Require at least one standard or daylight definition."""
        standard = values.get("standard")
        daylight = values.get("daylight")
        if not standard and not daylight:
            raise ValueError("At least one standard or daylight definition is required")
        return values


class IcsTimezoneInfo(datetime.tzinfo):
    """An implementation of tzinfo based on an ICS Timezone.

    This class is used to provide a tzinfo object for any datetime object
    used within a calendar. An rfc5545 calendar is an unambiguous definition of
    a calendar, and as a result, must encode all timezone information used in
    the calendar, hence this class.
    """

    def __init__(self, timezone: Timezone) -> None:
        """Initialize IcsTimezoneInfo."""
        self._timezone = timezone

    def __deepcopy__(self, memo: Any) -> IcsTimezoneInfo:
        """Return a deep copy of the timezone object."""
        return IcsTimezoneInfo(
            timezone=copy.deepcopy(self._timezone, memo),
        )

    @classmethod
    def from_timezone(cls, timezone: Timezone) -> IcsTimezoneInfo:
        """Create a new instance of an IcsTimezoneInfo."""
        return cls(timezone)

    def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta:
        """Return offset of local time from UTC, as a timedelta object."""
        if not dt or not (obs := self._get_observance(dt)):
            return _ZERO
        return obs.observance.tz_offset_to.offset

    def tzname(self, dt: datetime.datetime | None) -> str | None:
        """Return the time zone name for the datetime as a sorting."""
        if (
            not dt
            or not (obs := self._get_observance(dt))
            or not obs.observance.tz_name
        ):
            return None
        return obs.observance.tz_name[0]

    def dst(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
        """Return the daylight saving time (DST) adjustment, if applicable."""
        if (
            not dt
            or not (obs := self._get_observance(dt))
            or obs.observance_type != _ObservanceType.DAYLIGHT
        ):
            return _ZERO
        return obs.observance.tz_offset_to.offset - obs.observance.tz_offset_from.offset

    def _get_observance(self, value: datetime.datetime) -> _ObservanceInfo | None:
        return self._timezone.get_observance(value.replace(tzinfo=None))

    def __str__(self) -> str:
        """A string representation of the timezone object."""
        return self._timezone.tz_id

    def __repr__(self) -> str:
        """A string representation of the timezone object."""
        return f"{self.__class__.__name__}({self._timezone.tz_id})"


class TimezoneModel(ComponentModel):
    """A parser of a calendar that just parses timezone data.

    This exists so that we can parse timezone information in a first pass then propagate
    that information down to child objects when parsing the rest of the calendar. This is
    so we can do one pass on parsing events and timezone information at once, rather than
    deferring to later.
    """

    timezones: list[Timezone] = Field(alias="vtimezone", default_factory=list)
    """Timezones associated with this calendar."""
