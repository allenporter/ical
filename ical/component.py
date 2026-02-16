"""Library for parsing and encoding rfc5545 components with pydantic.

The data model returned by the contentlines parsing is a bag of ParsedProperty
objects that support all the flexibility of the rfc5545 spec. However in the
common case the spec has a lot more flexibility than is needed for handling
simple property types e.g. a single summary field that is specified only once.

This library helps reduce boilerplate for translating that complex structure
into the simpler pydantic data model, and handles custom field types and
validators.

Just as the pydantic model provides syntax glue for parsing data and
associating necessary validators, this is also doing the same thing
in the opposite direction to encode back to ICS.
"""

from __future__ import annotations

import copy
import datetime
import json
from functools import cache
import logging
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from pydantic.fields import FieldInfo

from .parsing.property import ParsedProperty
from .parsing.component import ParsedComponent
from .types.extra import ExtraProperty
from .types.data_types import DATA_TYPE, get_field_type_info
from .types.text import TextEncoder
from .exceptions import CalendarParseError, ParameterValueError

if TYPE_CHECKING:
    from typing import TypeVar

    from .event import Event
    from .journal import Journal
    from .todo import Todo

    ModelT = TypeVar("ModelT", bound=Union[Event, Journal, Todo])
    ModelV = TypeVar("ModelV", bound=Union[Event, Todo])

_LOGGER = logging.getLogger(__name__)


ATTR_VALUE = "VALUE"


def _adjust_recurrence_date(
    date_value: datetime.datetime | datetime.date,
    dtstart: datetime.datetime | datetime.date,
) -> datetime.datetime | datetime.date:
    """Apply fixes to the recurrence rule date."""
    if isinstance(dtstart, datetime.datetime):
        if not isinstance(date_value, datetime.datetime):
            raise ValueError(
                "DTSTART was DATE-TIME but UNTIL was DATE: must be the same value type"
            )
        if dtstart.tzinfo is None:
            if date_value.tzinfo is not None:
                raise ValueError("DTSTART is date local but UNTIL was not")
            return date_value

        if date_value.utcoffset():
            raise ValueError("DTSTART had UTC or local and UNTIL must be UTC")

        return date_value

    if isinstance(date_value, datetime.datetime):
        # Fix invalid rules where UNTIL value is DATE-TIME but DTSTART is DATE
        return date_value.date()

    return date_value


def validate_until_dtstart(self: ModelT) -> ModelT:
    """Verify the until time and dtstart are the same."""
    if not (rule := self.rrule) or not rule.until or not (dtstart := self.dtstart):
        return self
    rule.until = _adjust_recurrence_date(rule.until, dtstart)
    return self


def validate_duration_unit(self: ModelV) -> ModelV:
    """Validate the duration is the appropriate units."""
    if not (duration := self.duration):
        return self
    dtstart = self.dtstart
    if type(dtstart) is datetime.date:
        if duration.seconds != 0:
            raise ValueError("Event with start date expects duration in days only")
    if duration < datetime.timedelta(seconds=0):
        raise ValueError(f"Expected duration to be positive but was {duration}")
    return self


def _as_datetime(
    date_value: datetime.datetime | datetime.date,
    dtstart: datetime.datetime,
) -> datetime.datetime:
    if not isinstance(date_value, datetime.datetime):
        new_dt = datetime.datetime.combine(date_value, dtstart.time())
        return new_dt.replace(tzinfo=dtstart.tzinfo)
    return date_value


def _as_date(
    date_value: datetime.datetime | datetime.date,
    dtstart: datetime.date,
) -> datetime.date:
    if isinstance(date_value, datetime.datetime):
        return datetime.date.fromordinal(date_value.toordinal())
    return date_value


def validate_recurrence_dates(self: ModelT) -> ModelT:
    """Verify the recurrence dates have the correct types."""
    if not self.rrule or not (dtstart := self.dtstart):
        return self
    is_datetime = isinstance(dtstart, datetime.datetime)
    validator = _as_datetime if is_datetime else _as_date
    for field in ("exdate", "rdate"):
        if not (date_values := self.__dict__.get(field)):
            continue

        self.__dict__[field] = [
            validator(date_value, dtstart)  # type: ignore[arg-type]
            for date_value in date_values
        ]
    return self


class ComponentModel(BaseModel):
    """Abstract class for rfc5545 component model."""

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as err:
            _LOGGER.debug("Failed to parse component %s", err)
            message = [
                f"Failed to parse calendar {self.__class__.__name__.upper()} component"
            ]
            for error in err.errors():
                if msg := error.get("msg"):
                    message.append(msg)
            error_str = ": ".join(message)
            raise CalendarParseError(error_str, detailed_error=str(err)) from err

    def copy_and_validate(self, update: dict[str, Any]) -> ComponentModel:
        """Create a new object with updated values and validate it."""
        # Make a deep copy since deletion may update this objects recurrence rules
        new_item_copy = self.model_copy(update=update, deep=True)
        # Create a new object using the constructor to ensure we're performing
        # validation on the new object.
        return self.__class__(**new_item_copy.model_dump())

    @classmethod
    def _parse_property(
        cls, field_type: FieldInfo, name: str, props: list[ParsedProperty]
    ) -> Any:
        """Parse an individual field value from a ParsedProperty as the specified types."""
        return DATA_TYPE.parse_field(field_type, name, props)

    @classmethod
    @cache
    def _all_fields(cls) -> dict[str, str]:
        """Return a mapping of all field names and aliases to their field names."""
        return {field.alias or name: name for name, field in cls.model_fields.items()}

    @model_validator(mode="before")
    @classmethod
    def _parse_component(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse individual ParsedProperty items for both model fields and extras."""
        new_values: dict[str, Any] = {}
        for key, value in values.items():
            field_name = cls._all_fields().get(key, "extras")
            if (
                (field := cls.model_fields.get(field_name))
                and isinstance(value, list)
                and value
                and isinstance(value[0], ParsedProperty)
            ):
                parsed_properties = cls._parse_property(field, key, value)
                if field_name == "extras":
                    key = "extras"
                    parsed_properties = new_values.get("extras", []) + parsed_properties
                new_values[key] = parsed_properties
            else:
                new_values[key] = value

        return new_values

    def __encode_component_root__(self) -> ParsedComponent:
        """Encode the calendar stream as an rfc5545 iCalendar content."""
        # The overall data model hierarchy is created by pydantic and properties
        # are encoded using the json encoders specific for each type. These are
        # marshalled through as string values. There are then additional passes
        # to get the data in to the right final format for ics encoding.
        model_data = json.loads(
            self.model_dump_json(
                by_alias=True, exclude_none=True, context={"ics": True}
            )
        )
        # The component name is ignored as we're really only encoding children components
        return self.__encode_component__(self.__class__.__name__, model_data)

    @classmethod
    def __encode_component__(
        cls, name: str, model_data: dict[str, Any]
    ) -> ParsedComponent:
        """Encode this object as a component to prepare for serialization.

        The data passed in have already been encoded with one pass from the root json
        encoder. This method takes additional passes to add more field specific encoding,
        as well as overall component objects.
        """
        parent = ParsedComponent(name=name)
        for name, field in cls.model_fields.items():
            key = field.alias or name
            values = model_data.get(key)
            if values is None:
                continue
            if not isinstance(values, list):
                values = [values]
            annotation = get_field_type_info(field.annotation).annotation
            for value in values:
                for field_type in DATA_TYPE.get_ordered_field_types(annotation):
                    if component_encoder := getattr(
                        field_type, "__encode_component__", None
                    ):
                        parent.components.append(component_encoder(key, value))
                        break
                else:
                    if prop := DATA_TYPE.encode_property(key, annotation, value):
                        parent.properties.append(prop)
        return parent

    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
