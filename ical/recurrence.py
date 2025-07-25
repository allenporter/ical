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
from typing import Annotated, Union, Self

from dateutil import rrule
from pydantic import BeforeValidator, ConfigDict, Field, field_serializer

from .parsing.property import (
    parse_contentlines,
)
from .parsing.component import ParsedComponent

from .types.data_types import serialize_field
from .types.date import DateEncoder
from .types.recur import Recur
from .types.date_time import DateTimeEncoder
from .component import ComponentModel
from .exceptions import CalendarParseError
from .iter import RulesetIterable
from .util import parse_date_and_datetime, parse_date_and_datetime_list


_LOGGER = logging.getLogger(__name__)


class Recurrences(ComponentModel):
    """A common set of recurrence related properties for calendar components."""

    dtstart: Annotated[
        Union[datetime.date, datetime.datetime, None],
        BeforeValidator(parse_date_and_datetime),
    ] = None
    """The start date for the event."""

    rrule: list[Recur] = Field(default_factory=list)
    """The recurrence rule for the event."""

    rdate: Annotated[
        list[Union[datetime.date, datetime.datetime]],
        BeforeValidator(parse_date_and_datetime_list),
    ] = Field(default_factory=list)
    """Dates for the event."""

    exdate: Annotated[
        list[Union[datetime.date, datetime.datetime]],
        BeforeValidator(parse_date_and_datetime_list),
    ] = Field(default_factory=list)
    """Excluded dates for the event."""

    @classmethod
    def from_basic_contentlines(cls, contentlines: list[str]) -> Self:
        """Parse a raw component from a list of contentlines making up the body.

        This is meant to be a performance optimized version of the parsing
        that is done in the main parser. It is used for parsing recurrences
        from a calendar component only.
        """
        try:
            properties = list(parse_contentlines(contentlines))
        except ValueError as err:
            raise CalendarParseError(
                "Failed to parse recurrence", detailed_error=str(err)
            ) from err
        component = ParsedComponent(
            name="recurrences",  # Not used in the model
            properties=properties,
        )
        return cls.model_validate(component.as_dict())

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

    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
    )
    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]
