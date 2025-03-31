"""A grouping of component properties for describing recurrence rules.

This is a standalone component used for defining recurrence rules for
any other component. This is a faster performance library than invoking
the full rfc5545 parser for the same data. As a result, it does not support
the full rfc5545 specification, but only a subset of it.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Iterable
from typing import Any, Optional, Union, Self

from dateutil import rrule
from pydantic.v1 import BaseModel, Field

from .parsing.property import (
    ParsedProperty,
    ParsedPropertyParameter,
    parse_basic_ics_properties,
)
from .parsing.component import ParsedComponent

from .types.data_types import DATA_TYPE
from .types.date import DateEncoder
from .types.recur import Recur
from .types.date_time import DateTimeEncoder
from .component import ComponentModel
from .exceptions import CalendarParseError
from .iter import RulesetIterable


_LOGGER = logging.getLogger(__name__)


class Recurrences(ComponentModel):
    """A common set of recurrence related properties for calendar components."""

    dtstart: Optional[Union[datetime.datetime | datetime.date]] = None
    """The start date for the event."""

    rrule: list[Recur] = Field(default_factory=list)
    """The recurrence rule for the event."""

    rdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    """Dates for the event."""

    exdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    """Excluded dates for the event."""

    @classmethod
    def from_basic_contentlines(cls, contentlines: list[str]) -> Self:
        """Parse a raw component from a list of contentlines making up the body.

        This is meant to be a performance optimized version of the parsing
        that is done in the main parser. It is used for parsing recurrences
        from a calendar component only.
        """
        try:
            properties = list(parse_basic_ics_properties(contentlines))
        except ValueError as err:
            raise CalendarParseError(
                "Failed to parse recurrence", detailed_error=str(err)
            ) from err
        component = ParsedComponent(
            name="recurrences",  # Not used in the model
            properties=properties,
        )
        return cls.parse_obj(component.as_dict())

    def as_rrule(
        self, dtstart: datetime.date | datetime.datetime | None = None
    ) -> Iterable[datetime.date | datetime.datetime]:
        """Return the set of recurrences as a rrule that emits start times."""
        if dtstart is None:
            dtstart = self.dtstart
        if dtstart is None:
            raise ValueError("dtstart is required to generate recurrences")
        return RulesetIterable(
            dtstart,
            [rule.as_rrule(dtstart) for rule in self.rrule],
            self.rdate,
            self.exdate,
        )

    def ics(self) -> list[str]:
        """Serialize the recurrence rules as strings."""
        return [prop.ics() for prop in self.__encode_component_root__().properties]

    class Config:
        """Configuration for IcsCalendarStream pydantic model."""

        json_encoders = DATA_TYPE.encode_property_json
        validate_assignment = True
        allow_population_by_field_name = True
