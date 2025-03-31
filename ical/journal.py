"""A grouping of component properties that describe a journal entry."""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import datetime
import enum
import logging
from collections.abc import Iterable
from typing import Any, Optional, Union

try:
    from pydantic.v1 import Field, root_validator
except ImportError:
    from pydantic import Field, root_validator  # type: ignore[no-redef, assignment]

from .component import ComponentModel, validate_until_dtstart, validate_recurrence_dates
from .parsing.property import ParsedProperty
from .types import (
    CalAddress,
    Classification,
    Recur,
    RecurrenceId,
    RequestStatus,
    Uri,
    RelatedTo,
)
from .util import dtstamp_factory, normalize_datetime, uid_factory, local_timezone
from .iter import RulesetIterable, as_rrule
from .timespan import Timespan


_LOGGER = logging.getLogger(__name__)

__all__ = ["Journal", "JournalStatus"]

_ONE_HOUR = datetime.timedelta(hours=1)
_ONE_DAY = datetime.timedelta(days=1)


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
    dtstart: Union[datetime.datetime, datetime.date] = Field(
        default=None,
    )
    exdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    organizer: Optional[CalAddress] = None
    recurrence_id: Optional[RecurrenceId] = Field(alias="recurrence-id")

    related_to: list[RelatedTo] = Field(alias="related-to", default_factory=list)
    """Used to represent a relationship or reference between events."""

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

    @property
    def computed_duration(self) -> datetime.timedelta:
        """Return the event duration."""
        if isinstance(self.dtstart, datetime.datetime):
            return _ONE_HOUR
        return _ONE_DAY

    @property
    def timespan(self) -> Timespan:
        """Return a timespan representing the item start and due date."""
        return self.timespan_of(local_timezone())

    def timespan_of(self, tzinfo: datetime.tzinfo) -> Timespan:
        """Return a timespan representing the item start and due date."""
        dtstart = normalize_datetime(self.dtstart, tzinfo) or datetime.datetime.now(
            tz=tzinfo
        )
        return Timespan.of(dtstart, dtstart + self.computed_duration, tzinfo)

    @property
    def recurring(self) -> bool:
        """Return true if this Todo is recurring.

        A recurring event is typically evaluated specially on the list. The
        data model has a single todo, but the timeline evaluates the recurrence
        to expand and copy the the event to multiple places on the timeline
        using `as_rrule`.
        """
        if self.rrule or self.rdate:
            return True
        return False

    def as_rrule(self) -> Iterable[datetime.datetime | datetime.date] | None:
        """Return an iterable containing the occurrences of a recurring todo.

        A recurring todo is typically evaluated specially on the todo list. The
        data model has a single todo item, but the timeline evaluates the recurrence
        to expand and copy the the item to multiple places on the timeline.

        This is only valid for events where `recurring` is True.
        """
        return as_rrule(self.rrule, self.rdate, self.exdate, self.dtstart)

    _validate_until_dtstart = root_validator(allow_reuse=True)(validate_until_dtstart)
    _validate_recurrence_dates = root_validator(allow_reuse=True)(
        validate_recurrence_dates
    )
