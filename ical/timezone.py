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

import datetime
import logging
from typing import Any, Optional, Union

from pydantic import Field, root_validator, validator

from .parsing.property import ParsedProperty
from .types import ComponentModel, Recur, Uri, UtcOffset, parse_recur
from .tzif import timezoneinfo, tz_rule
from .util import dtstamp_factory

_LOGGER = logging.getLogger(__name__)


# Assume that all tzif timezone rules start at an arbitrary old date. This library
# typically only works with "go forward" dates, so we don't need to be completely
# accurate and use the historical database of times.
TZ_START = datetime.datetime(2010, 1, 1, 0, 0, 0)


class TimezoneInfo(ComponentModel):
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

    def __init__(self, **data: dict[str, Any]) -> None:
        """Initialize Timezone."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        super().__init__(**data)

    @validator("dtstart")
    def verify_dtstart_local_time(cls, value: datetime.datetime) -> datetime.datetime:
        """Validate that dtstart is specified in a local time."""
        if value.utcoffset() is not None:
            raise ValueError(f"Start time must be in local time format: {value}")
        return value


class Timezone(ComponentModel):
    """A single free/busy entry on a calendar.

    A Timezone must have at least one definition of a standard or daylight
    sub-component.
    """

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=lambda: dtstamp_factory()
    )
    """Last revision date."""

    tz_id: str = Field(alias="tzid")
    """An identifier for this Timezone, unique within a calendar."""

    standard: list[TimezoneInfo] = Field(default_factory=list)
    """Describes the base offset from UTC for the time zone."""

    daylight: list[TimezoneInfo] = Field(default_factory=list)
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
    def from_tzif(cls, key: str, start: datetime.datetime = TZ_START) -> Timezone:
        """Create a new Timezone from a tzif data source."""
        info = timezoneinfo.read(key)
        rule = info.rule
        if not rule:
            raise ValueError("Unsupported timezoneinfo had no rule")

        dst_offset = rule.std.offset
        if rule.dst and rule.dst.offset:
            dst_offset = rule.dst.offset

        std_timezone_info = TimezoneInfo(
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
                parse_recur(rule.dst_end.rrule_str)
            )
            std_timezone_info.dtstart = rule.dst_end.rrule_dtstart(start)
            daylight.append(
                TimezoneInfo(
                    tz_name=[rule.dst.name],
                    tz_offset_to=UtcOffset(offset=rule.dst.offset),
                    tz_offset_from=UtcOffset(offset=rule.std.offset),
                    rrule=Recur.parse_obj(parse_recur(rule.dst_start.rrule_str)),
                    dtstart=rule.dst_start.rrule_dtstart(start),
                )
            )
        return Timezone(tz_id=key, standard=[std_timezone_info], daylight=daylight)

    @root_validator
    def parse_required_timezoneinfo(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Require at least one standard or daylight definition."""
        standard = values.get("standard")
        daylight = values.get("daylight")
        if not standard and not daylight:
            raise ValueError("At least one standard or daylight definition is required")
        return values
