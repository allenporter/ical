"""A set of properties that describes a free/busy times."""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import datetime
import logging
from typing import Annotated, Any, Optional, Union

from pydantic import BeforeValidator, Field, field_serializer, field_validator

from ical.types.data_types import serialize_field

from .component import ComponentModel
from .parsing.property import ParsedProperty
from .types import CalAddress, Period, RequestStatus, Uri
from .util import (
    dtstamp_factory,
    normalize_datetime,
    parse_date_and_datetime,
    uid_factory,
)

_LOGGER = logging.getLogger(__name__)


class FreeBusy(ComponentModel):
    """A single free/busy entry on a calendar."""

    dtstamp: Annotated[
        Union[datetime.date, datetime.datetime],
        BeforeValidator(parse_date_and_datetime),
    ] = Field(default_factory=lambda: dtstamp_factory())
    """Last revision date."""

    uid: str = Field(default_factory=lambda: uid_factory())
    """The persistent globally unique identifier."""

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    """The user whose free/busy time is represented."""

    comment: list[str] = Field(default_factory=list)
    """Non-processing information intended to provide comments to the calendar user."""

    contacts: list[str] = Field(alias="contact", default_factory=list)
    """Contact information associated with this component."""

    # Has an alias of 'start'
    dtstart: Annotated[
        Union[datetime.date, datetime.datetime, None],
        BeforeValidator(parse_date_and_datetime),
    ] = Field(default=None)
    """Start of the time range covered by this component."""

    # Has an alias of 'end'
    dtend: Annotated[
        Union[datetime.date, datetime.datetime, None],
        BeforeValidator(parse_date_and_datetime),
    ] = None
    """End of the time range covered by this component."""

    freebusy: list[Period] = Field(default_factory=list)
    """The free/busy intervals."""

    organizer: Optional[CalAddress] = None
    """The calendar user who requested free/busy information."""

    request_status: Optional[RequestStatus] = Field(
        default=None,
        alias="request-status",
    )
    """Return code for the scheduling request."""

    sequence: Optional[int] = None
    """The revision sequence number of this calendar component."""

    url: Optional[Uri] = None
    """The URL associated with this component."""

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        """Initialize Event."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        if "end" in data:
            data["dtend"] = data.pop("end")
        super().__init__(**data)

    @property
    def start(self) -> datetime.datetime | datetime.date | None:
        """Return the start time for the event."""
        return self.dtstart

    @property
    def end(self) -> datetime.datetime | datetime.date | None:
        """Return the end time for the event."""
        return self.dtend

    @property
    def start_datetime(self) -> datetime.datetime | None:
        """Return the events start as a datetime."""
        if not self.start:
            return None
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
        if not self.end or not self.start:
            return None
        return self.end - self.start

    @field_validator("freebusy")
    @classmethod
    def verify_freebusy_utc(cls, values: list[Period]) -> list[Period]:
        """Validate that the free/busy periods must be in UTC."""
        _LOGGER.info("verify_freebusy_utc")
        for value in values:
            if not value.start:
                continue
            if (
                offset := value.start.utcoffset()
            ) is None or offset.total_seconds() != 0:
                raise ValueError(f"Freebusy time must be in UTC format: {value}")

        return values

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]
