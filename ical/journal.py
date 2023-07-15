"""A grouping of component properties that describe a journal entry."""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import datetime
import enum
import logging
from typing import Any, Optional, Union

try:
    from pydantic.v1 import Field, root_validator
except ImportError:
    from pydantic import Field, root_validator

from .component import ComponentModel, validate_until_dtstart, validate_recurrence_dates
from .parsing.property import ParsedProperty
from .types import CalAddress, Classification, Recur, RecurrenceId, RequestStatus, Uri
from .util import dtstamp_factory, normalize_datetime, uid_factory

_LOGGER = logging.getLogger(__name__)


class JournalStatus(str, enum.Enum):
    """Status or confirmation of the journal entry."""

    DRAFT = "DRAFT"
    FINAL = "FINAL"
    CANCELLED = "CANCELLED"


class Journal(ComponentModel):
    """A single journal entry on a calendar.

    A journal entry consists of one or more text notes associated with a
    specific calendar date.

    Can either be for a specific day, or with a start time and duration/end time.

    The dtstamp and uid functions have factory methods invoked with a lambda to facilitate
    mocking in unit tests.
    """

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=lambda: dtstamp_factory()
    )
    uid: str = Field(default_factory=lambda: uid_factory())
    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    categories: list[str] = Field(default_factory=list)
    classification: Optional[Classification] = Field(alias="class", default=None)
    comment: list[str] = Field(default_factory=list)
    contacts: list[str] = Field(alias="contact", default_factory=list)
    created: Optional[datetime.datetime] = None
    description: Optional[str] = None
    # Has an alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date] = Field(  # type: ignore
        default=None,
    )
    exdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    organizer: Optional[CalAddress] = None
    recurrence_id: Optional[RecurrenceId] = Field(alias="recurrence-id")
    related: list[str] = Field(default_factory=list)
    rrule: Optional[Recur] = None
    rdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    request_status: Optional[RequestStatus] = Field(
        alias="request-status", default_value=None
    )
    sequence: Optional[int] = None
    status: Optional[JournalStatus] = None
    summary: Optional[str] = None
    url: Optional[Uri] = None

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        """Initialize Event."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        super().__init__(**data)

    @property
    def start(self) -> datetime.datetime | datetime.date:
        """Return the start time for the event."""
        return self.dtstart

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the events start as a datetime."""
        return normalize_datetime(self.start).astimezone(tz=datetime.timezone.utc)

    _validate_until_dtstart = root_validator(allow_reuse=True)(validate_until_dtstart)
    _validate_recurrence_dates = root_validator(allow_reuse=True)(validate_recurrence_dates)