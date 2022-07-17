"""Calendar implementation."""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from typing import Any, Generator, Optional, Union

from pydantic import BaseModel, Field

from .contentlines import parse_content
from .event import Event
from .timeline import Timeline

FOLD = re.compile("(\r?\n)+[ \t]")
DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
DATE_REGEX = re.compile(r"^([0-9]{8})$")
DATE_PARAM = "DATE"
DATETIME_PARAM = "DATE-TIME"

PROPERTY_VALUE = re.compile(r"^VALUE=([^:]+):(.*)$")
PROPERTY_ALTREP = re.compile(r"ALTREP=\"([^\"]+)\"")

ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}


def unescape(value: str) -> str:
    """Escape human readable text items."""
    for key, vin in ESCAPE_CHAR.items():
        value = value.replace(key, vin)
    return value


class Calendar(BaseModel):
    """A calendar with events."""

    events: list[Event] = Field(default=[])

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return Timeline(self.events)


class Date(datetime.date):
    """Parser for rfc5545 date."""

    @classmethod
    def __get_validators__(
        cls,
    ) -> Generator[Callable[[str], datetime.date], None, None]:
        yield cls.parse_date

    @classmethod
    def parse_date(cls, value: Any) -> datetime.date:
        """Parse a rfc5545 into a datetime.date."""
        if not isinstance(value, str):
            raise TypeError(f"Expected string for {DATE_PARAM} value: {value}")
        if value_match := PROPERTY_VALUE.fullmatch(value):
            if value_match.group(1) != DATE_PARAM:
                raise TypeError(f"Expected VALUE={DATE_PARAM} value: {value}")
            value = value_match.group(2)
        if not (match := DATE_REGEX.fullmatch(value)):
            raise ValueError(f"Expected value to match {DATE_PARAM} pattern: {value}")
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        return datetime.date(year, month, day)


class DateTime(datetime.datetime):
    """Parser for rfc5545 date times."""

    @classmethod
    def __get_validators__(
        cls,
    ) -> Generator[Callable[[str], datetime.datetime], None, None]:
        yield cls.parse_date_time

    @classmethod
    def parse_date_time(cls, value: Any) -> datetime.datetime:
        """Parse a rfc5545 into a datetime.datetime."""
        if not isinstance(value, str):
            raise TypeError(f"Expected string for {DATETIME_PARAM} value: {value}")
        if value_match := PROPERTY_VALUE.fullmatch(value):
            if value_match.group(1) != DATETIME_PARAM:
                raise TypeError(f"Expected VALUE={DATETIME_PARAM} value: {value}")
            value = value_match.group(2)
        if not (match := DATETIME_REGEX.fullmatch(value)):
            raise ValueError(
                f"Expected value to match {DATETIME_PARAM} pattern: {value}"
            )

        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])

        time_value = match.group(2)
        hour = int(time_value[0:2])
        minute = int(time_value[2:4])
        second = int(time_value[4:6])

        # In the future, add support for timezone offset handling
        # is_utc_offset = m.group(3)
        return datetime.datetime(year, month, day, hour, minute, second)


class Description(str):
    """A calendar description."""

    @classmethod
    def __get_validators__(
        cls,
    ) -> Generator[Callable[[str], str], None, None]:
        yield cls.parse_description

    @classmethod
    def parse_description(cls, value: Any) -> str:
        """Parse a rfc5545 description into a str."""
        if not isinstance(value, str):
            raise TypeError(f"Expected description as string: {value}")
        if value_match := PROPERTY_ALTREP.match(value):
            # This currently strips the altrep property, but needs to be updated
            # to preserve it.
            # altrep = value_match.group(1)
            index = value_match.span()[1] + 1
            value = value[index:]
        return unescape(value)


class IcsEvent(BaseModel):
    """A calendar event component."""

    dtstamp: Union[DateTime, Date]
    uid: str
    dtstart: Union[DateTime, Date]
    dtend: Union[DateTime, Date]
    summary: str
    description: Optional[Description]
    transparency: Optional[str] = Field(alias="transp")


class IcsCalendar(BaseModel):
    """A sequence of calendar properities and calendar components."""

    prodid: str
    version: str
    calscale: Optional[str] = None
    method: Optional[str] = None
    x_prop: Optional[str] = None
    iana_prop: Optional[str] = None
    events: list[IcsEvent] = Field(alias="vevent")


class IcsStream(BaseModel):
    """A container that is a collection of calendaring information."""

    calendars: list[IcsCalendar] = Field(alias="vcalendar")

    @staticmethod
    def from_content(content: str) -> "IcsStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        return IcsStream.parse_obj(parse_content(content))
