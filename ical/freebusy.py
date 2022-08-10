"""A set of properties that describes a free/busy times."""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import datetime
import logging
from typing import Any, Optional, Union

from pydantic import Field, validator

from .parsing.property import ParsedProperty
from .types import CalAddress, ComponentModel, Period, RequestStatus, Uri
from .util import dtstamp_factory, normalize_datetime, uid_factory

_LOGGER = logging.getLogger(__name__)


class FreeBusy(ComponentModel):
    """A single free/busy entry on a calendar."""

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=lambda: dtstamp_factory()
    )
    """Last revision date."""

    uid: str = Field(default_factory=lambda: uid_factory())
    """The persistent globally unique identifier."""

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    """."""

    comment: list[str] = Field(default_factory=list)
    contacts: list[str] = Field(alias="contact", default_factory=list)
    # Has an alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date] = Field(
        default=None,
    )
    # Has an alias of 'end'
    dtend: Optional[Union[datetime.datetime, datetime.date]] = None

    freebusy: list[Period] = Field(default_factory=list)
    """The free/busy intervals."""

    organizer: Optional[CalAddress] = None
    request_status: Optional[RequestStatus] = Field(
        alias="request-status", default_value=None
    )
    sequence: Optional[int] = None
    url: Optional[Uri] = None

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    def __init__(self, **data: dict[str, Any]) -> None:
        """Initialize Event."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        if "end" in data:
            data["dtend"] = data.pop("end")
        super().__init__(**data)

    @property
    def start(self) -> datetime.datetime | datetime.date:
        """Return the start time for the event."""
        return self.dtstart

    @property
    def end(self) -> datetime.datetime | datetime.date | None:
        """Return the end time for the event."""
        return self.dtend

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the events start as a datetime."""
        return normalize_datetime(self.start).astimezone(tz=datetime.timezone.utc)

    @property
    def end_datetime(self) -> datetime.datetime | None:
        """Return the events end as a datetime."""
        if not self.end:
            return None
        return normalize_datetime(self.end).astimezone(tz=datetime.timezone.utc)

    @property
    def computed_duration(self) -> datetime.timedelta | None:
        """Return the event duration."""
        if not self.end:
            return None
        return self.end - self.start

    @validator("freebusy", allow_reuse=True)
    def verify_freebusy_utc(cls, values: list[Period]) -> list[Period]:
        """Validate that the free/busy periods must be in UTC."""
        for value in values:
            if not value.start:
                continue
            if (
                offset := value.start.utcoffset()
            ) is None or offset.total_seconds() != 0:
                raise ValueError(f"Freebusy time must be in UTC format: {value}")

        return values
