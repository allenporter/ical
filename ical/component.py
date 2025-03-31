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
import logging
from typing import Any, Union, get_args, get_origin

try:
    from pydantic.v1 import BaseModel, root_validator, ValidationError
    from pydantic.v1.fields import SHAPE_LIST
except ImportError:
    from pydantic import BaseModel, root_validator, ValidationError  # type: ignore[no-redef, assignment]
    from pydantic.fields import SHAPE_LIST  # type: ignore[attr-defined, no-redef]

from .parsing.component import ParsedComponent
from .parsing.property import ParsedProperty
from .types.data_types import DATA_TYPE
from .exceptions import CalendarParseError

_LOGGER = logging.getLogger(__name__)


ATTR_VALUE = "VALUE"

# Repeated values can either be specified as multiple separate values, but
# also some values support repeated values within a single value with a
# comma delimiter, listed here.
EXPAND_REPEATED_VALUES = {
    "categories",
    "classification",
    "exdate",
    "rdate",
    "resources",
    "freebusy",
}


def _adjust_recurrence_date(
    date_value: datetime.datetime | datetime.date,
    dtstart: datetime.datetime | datetime.date,
) -> datetime.datetime | datetime.date:
    """Apply fixes to the recurrence rule date."""
    if isinstance(dtstart, datetime.datetime):
        if not isinstance(date_value, datetime.datetime):
            raise ValueError(
                "DTSTART was DATE-TIME but UNTIL was DATE: "
                "must be the same value type"
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


def validate_until_dtstart(_cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Verify the until time and dtstart are the same."""
    if (
        not (rule := values.get("rrule"))
        or not rule.until
        or not (dtstart := values.get("dtstart"))
    ):
        return values
    rule.until = _adjust_recurrence_date(rule.until, dtstart)
    return values


def _as_datetime(
    date_value: datetime.datetime | datetime.date,
    dtstart: datetime.datetime,
) -> datetime.datetime:
    if not isinstance(date_value, datetime.datetime):
        return datetime.datetime.combine(date_value, dtstart.time())
    return date_value


def _as_date(
    date_value: datetime.datetime | datetime.date,
    dtstart: datetime.datetime,
) -> datetime.date:
    if isinstance(date_value, datetime.datetime):
        return datetime.date.fromordinal(date_value.toordinal())
    return date_value


def validate_recurrence_dates(
    _cls: BaseModel, values: dict[str, Any]
) -> dict[str, Any]:
    """Verify the recurrence dates have the correct types."""
    if (
        not values.get("rrule")
        or not (dtstart := values.get("dtstart"))
        or not (
            isinstance(dtstart, datetime.datetime) or isinstance(dtstart, datetime.date)
        )
    ):
        return values
    is_datetime = isinstance(dtstart, datetime.datetime)
    validator = _as_datetime if is_datetime else _as_date
    for field in ("exdate", "rdate"):
        if not (date_values := values.get(field)):
            continue

        values[field] = [validator(date_value, dtstart) for date_value in date_values]
    return values


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
        new_item_copy = self.copy(update=update, deep=True)
        # Create a new object using the constructore to ensure we're performing
        # validation on the new object.
        return self.__class__(**new_item_copy.dict())

    @root_validator(pre=True, allow_reuse=True)
    def parse_extra_fields(
        cls, values: dict[str, list[ParsedProperty | ParsedComponent]]
    ) -> dict[str, Any]:
        """Parse extra fields not in the model."""
        all_fields = set()
        for field in cls.__fields__.values():
            all_fields |= {field.alias, field.name}

        extras: list[ParsedProperty | ParsedComponent] = []
        for field_name, value in values.items():
            if field_name in all_fields:
                continue
            for prop in value:
                if isinstance(prop, ParsedProperty):
                    extras.append(prop)
        if extras:
            values["extras"] = extras
        return values

    @root_validator(pre=True, allow_reuse=True)
    def parse_property_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse individual ParsedProperty value fields."""
        _LOGGER.debug("Parsing value data %s", values)

        for field in cls.__fields__.values():
            if field.alias == "extras":
                continue
            if not (value := values.get(field.alias)):
                continue
            if not (isinstance(value, list) and isinstance(value[0], ParsedProperty)):
                # The incoming value is not from the parse tree
                continue
            if field.alias in EXPAND_REPEATED_VALUES:
                value = cls._expand_repeated_property(value)
            # Repeated values will accept a list, otherwise truncate to a single
            # value when repeated is not allowed.
            allow_repeated = field.shape == SHAPE_LIST
            if not allow_repeated and len(value) > 1:
                raise ValueError(f"Expected one value for field: {field.alias}")
            field_types = cls._get_field_types(field.type_)
            validated = [cls._parse_property(field_types, prop) for prop in value]
            values[field.alias] = validated if allow_repeated else validated[0]

        _LOGGER.debug("Completed parsing value data %s", values)

        return values

    @classmethod
    def _parse_property(cls, field_types: list[type], prop: ParsedProperty) -> Any:
        """Parse an individual field value from a ParsedProperty as the specified types."""
        _LOGGER.debug(
            "Parsing field '%s' with value '%s' as types %s",
            prop.name,
            prop.value,
            field_types,
        )
        errors = []
        for sub_type in field_types:
            try:
                return cls._parse_single_property(sub_type, prop)
            except ValueError as err:
                _LOGGER.debug(
                    "Unable to parse property value as type %s: %s", sub_type, err
                )
                errors.append(str(err))
                continue
        raise ValueError(f"Failed to validate: {prop.value}, errors: ({errors})")

    @classmethod
    def _parse_single_property(cls, field_type: type, prop: ParsedProperty) -> Any:
        """Parse an individual field as a single type."""
        if (
            value_type := prop.get_parameter_value(ATTR_VALUE)
        ) and field_type not in DATA_TYPE.disable_value_param:
            # Property parameter specified a strong type
            if func := DATA_TYPE.parse_parameter_by_name.get(value_type):
                _LOGGER.debug("Parsing %s as value type '%s'", prop.name, value_type)
                return func(prop)
            # Consider graceful degradation instead in the future
            raise ValueError(
                f"Property parameter specified unsupported type: {value_type}"
            )

        if decoder := DATA_TYPE.parse_property_value.get(field_type):
            _LOGGER.debug("Decoding '%s' as type '%s'", prop.name, field_type)
            return decoder(prop)

        _LOGGER.debug("Using '%s' bare property value '%s'", prop.name, prop.value)
        return prop.value

    @classmethod
    def _expand_repeated_property(
        cls, value: list[ParsedProperty]
    ) -> list[ParsedProperty]:
        """Expand properties with repeated values into separate properties."""
        result: list[ParsedProperty] = []
        for prop in value:
            if "," in prop.value:
                for sub_value in prop.value.split(","):
                    sub_prop = copy.deepcopy(prop)
                    sub_prop.value = sub_value
                    result.append(sub_prop)
            else:
                result.append(prop)
        return result

    @classmethod
    def _get_field_types(cls, field_type: type) -> list[type]:
        """Return type to attempt for encoding/decoding based on the field type."""
        origin = get_origin(field_type)
        if origin is Union:
            if not (args := get_args(field_type)):
                raise ValueError(f"Unable to determine args of type: {field_type}")

            # get_args does not have a deterministic order, so use the order supplied
            # in the registry. Ignore None as its not a parseable type.
            sortable_args = [
                (DATA_TYPE.parse_order.get(arg, 0), arg)
                for arg in args
                if arg is not type(None)  # noqa: E721
            ]
            sortable_args.sort(reverse=True)
            return [arg for (order, arg) in sortable_args]
        return [field_type]

    def __encode_component_root__(self) -> ParsedComponent:
        """Encode the calendar stream as an rfc5545 iCalendar content."""
        # The overall data model hierarchy is created by pydantic and properties
        # are encoded using the json encoders specific for each type. These are
        # marshalled through as string values. There are then additional passes
        # to ge the data in to the right final format for ics encoding.
        model_data = json.loads(
            self.json(by_alias=True, exclude_none=True, exclude_defaults=True)
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
        for field in cls.__fields__.values():
            key = field.alias
            values = model_data.get(key)
            if values is None or key == "extras":
                continue
            if not isinstance(values, list):
                values = [values]
            for value in values:
                if component_encoder := getattr(
                    field.type_, "__encode_component__", None
                ):
                    parent.components.append(component_encoder(key, value))
                    continue
                if prop := cls._encode_property(key, field.type_, value):
                    parent.properties.append(prop)
        return parent

    @classmethod
    def _encode_property(cls, key: str, field_type: type, value: Any) -> ParsedProperty:
        """Encode an individual property for the specified field."""
        # A property field may have multiple possible types, like for
        # a Union. Pick the first type that is able to encode the value.
        errors = []
        for sub_type in cls._get_field_types(field_type):
            encoded_value: Any | None = None
            if value_encoder := DATA_TYPE.encode_property_value.get(sub_type):
                try:
                    encoded_value = value_encoder(value)
                except ValueError as err:
                    _LOGGER.debug("Encoding failed for property: %s", err)
                    errors.append(str(err))
                    continue
            else:
                encoded_value = value

            if encoded_value is not None:
                prop = ParsedProperty(name=key, value=encoded_value)
                if params_encoder := DATA_TYPE.encode_property_params.get(
                    sub_type, None
                ):
                    if params := params_encoder(value):
                        prop.params = params
                return prop

        raise ValueError(f"Unable to encode property: {value}, errors: {errors}")

    class Config:
        """Pyandtic model configuration."""

        validate_assignment = True
        allow_population_by_field_name = True
        smart_union = True
        arbitrary_types_allowed = True
