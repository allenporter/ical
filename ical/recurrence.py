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
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from .parsing.property import (
    parse_contentlines,
)
from .parsing.component import ParsedComponent

from .types.data_types import serialize_field
from .types.date import DateEncoder
from .types.recur import Recur
from .types.date_time import DateTimeEncoder
from .component import (
    ComponentModel,
    _adjust_recurrence_date,
    _as_date,
    _as_datetime,
)
from .exceptions import CalendarParseError
from .iter import RulesetIterable
from .util import (
    parse_date_and_datetime,
    parse_date_and_datetime_list,
    parse_rdate_list,
)
from .types.period import Period


_LOGGER = logging.getLogger(__name__)

__all__ = ["Recurrences"]


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
        list[Union[datetime.date, datetime.datetime, Period]],
        BeforeValidator(parse_rdate_list),
    ] = Field(default_factory=list)
    """Dates for the event."""

    exdate: Annotated[
        list[Union[datetime.date, datetime.datetime]],
        BeforeValidator(parse_date_and_datetime_list),
    ] = Field(default_factory=list)
    """Excluded dates for the event."""

    @model_validator(mode="after")
    def _validate_until_dtstart(self) -> Self:
        """Verify the until time and dtstart are the same."""
        if not self.rrule or not (dtstart := self.dtstart):
            return self
        for rule in self.rrule:
            if rule.until:
                rule.until = _adjust_recurrence_date(rule.until, dtstart)
        return self

    @model_validator(mode="after")
    def _validate_recurrence_dates(self) -> Self:
        """Verify the recurrence dates have the correct types."""
        if not self.rrule or not (dtstart := self.dtstart):
            return self
        for field in ("exdate", "rdate"):
            if not (date_values := self.__dict__.get(field)):
                continue

            if isinstance(dtstart, datetime.datetime):
                normalized: list[datetime.date | datetime.datetime | Period] = []
                for date_value in date_values:
                    if isinstance(date_value, Period):
                        normalized.append(date_value)
                    else:
                        dt_val = _as_datetime(date_value, dtstart)
                        if dtstart.tzinfo is not None and dt_val.tzinfo is None:
                            dt_val = dt_val.replace(tzinfo=dtstart.tzinfo)
                        elif dtstart.tzinfo is None and dt_val.tzinfo is not None:
                            dt_val = dt_val.replace(tzinfo=None)
                        normalized.append(dt_val)
                self.__dict__[field] = normalized
            else:
                self.__dict__[field] = [
                    date_value
                    if isinstance(date_value, Period)
                    else _as_date(date_value, dtstart)
                    for date_value in date_values
                ]
        return self

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
