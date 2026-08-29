"""Library for parsing and encoding rfc5545 types."""

from __future__ import annotations

import copy
import logging
from functools import cache
from collections.abc import Callable
from types import NoneType
from contextvars import ContextVar
import dataclasses
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    NamedTuple,
    Protocol,
    TypeVar,
    Union,
    get_args,
    get_origin,
    runtime_checkable,
)

from pydantic import BaseModel, SerializationInfo, ConfigDict
from pydantic.fields import FieldInfo

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.exceptions import ParameterValueError

_LOGGER = logging.getLogger(__name__)

T_TYPE = TypeVar("T_TYPE", bound=type)


class EncodedJcalValue(NamedTuple):
    """An encoded jCal property value pre-serialization."""

    params: dict[str, Any]
    values: list[Any]
    type_name: str | None = None


@dataclasses.dataclass
class FieldTypeInfo:
    """Information about a field type."""

    annotation: Any
    """The base type of the field (e.g. without Optional or list)."""

    is_repeated: bool = False
    """True if the field is a list."""

    is_optional: bool = False
    """True if the field is an Optional."""


# Properties that are represented as a list in the python data model, but
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


class DataType(Protocol):
    """Defines the protocol implemented by data types in this library.

    The methods defined in this protocol are all optional.
    """

    @classmethod
    def __property_type__(cls) -> type:
        """Defines the python type to match, if different from the type itself."""

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> type:
        """Parse the specified property value as a python type."""

    @classmethod
    def __parse_jcal_value__(
        cls, value: Any, params: dict[str, Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Parse the specified jCal property value as a python type."""
        return value

    @classmethod
    def __encode_property__(cls, value: Any) -> ParsedProperty | None:
        """Encode the property from the object model to a ParsedProperty."""
        return ParsedProperty(name="", value=value)

    @classmethod
    def __encode_property_json__(cls, value: Any) -> str | dict[str, str]:
        """Encode the property during pydantic serialization to object model."""

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode the property value as jCal parameters dict and value list."""
        return EncodedJcalValue({}, [value])


class Registry:
    """Registry of data types."""

    def __init__(
        self,
    ) -> None:
        """Initialize Registry."""
        self._items: dict[str, type] = {}
        self._type_names: dict[type, str] = {}
        self._parse_property_value: dict[type, Callable[[ParsedProperty], Any]] = {}
        self._parse_parameter_by_name: dict[str, Callable[[ParsedProperty], Any]] = {}
        self._parse_jcal_value: dict[type, Callable[..., Any]] = {}
        self._parse_jcal_parameter_by_name: dict[str, Callable[..., Any]] = {}
        self._encode_property: dict[type, Callable[[Any], ParsedProperty | None]] = {}
        self._encode_property_json: dict[
            type, Callable[[Any], str | dict[str, str]]
        ] = {}
        self._encode_jcal_value: dict[
            type, Callable[[Any], EncodedJcalValue | None]
        ] = {}
        self._disable_value_param: set[type] = set()
        self._parse_order: dict[type, int] = {}

    def get_ordered_field_types(self, field_type: type) -> list[type]:
        """Return type to attempt for encoding/decoding based on the field type."""
        type_info = get_field_type_info(field_type)
        if get_origin(type_info.annotation) is Union:
            if not (args := get_args(type_info.annotation)):
                raise ValueError(f"Unable to determine args of type: {field_type}")

            # get_args does not have a deterministic order, so use the order supplied
            # in the registry. Ignore None as its not a parseable type.
            sortable_args = [
                (self._parse_order.get(arg, 0), arg)
                for arg in args
                if arg is not type(None)  # noqa: E721
            ]
            sortable_args.sort(reverse=True)
            return [arg for (order, arg) in sortable_args]
        return [type_info.annotation]

    def parse_property(self, field_type: type, prop: ParsedProperty) -> Any:
        """Parse an individual field value from a ParsedProperty as the specified types."""
        field_types = self.get_ordered_field_types(field_type)
        _LOGGER.debug(
            "Parsing field '%s' with value '%s' as types %s",
            prop.name,
            prop.value,
            field_types,
        )
        errors = []
        for sub_type in field_types:
            try:
                return self._parse_single_property(sub_type, prop)
            except ParameterValueError as err:
                _LOGGER.debug("Invalid property value of type %s: %s", sub_type, err)
                raise err
            except ValueError as err:
                _LOGGER.debug(
                    "Unable to parse property value as type %s: %s", sub_type, err
                )
                errors.append(str(err))
                continue
        raise ValueError(
            f"Failed to validate: {prop.value} as {' or '.join(sub_type.__name__ for sub_type in field_types)}, due to: ({errors})"
        )

    def _parse_single_property(self, field_type: type, prop: ParsedProperty) -> Any:
        """Parse an individual field as a single type."""
        if (
            value_type := prop.get_parameter_value("VALUE")
        ) and field_type not in self._disable_value_param:
            # Property parameter specified a strong type
            if func := self._parse_parameter_by_name.get(value_type):
                _LOGGER.debug("Parsing %s as value type '%s'", prop.name, value_type)
                return func(prop)

            # Graceful degradation: fall back to TEXT parsing for unknown VALUE types
            _LOGGER.debug(
                "Property '%s' has unsupported VALUE type '%s', falling back to TEXT",
                prop.name,
                value_type,
            )
            # We assume TextEncoder is already registered in Registry
            if func := self._parse_parameter_by_name.get("TEXT"):
                return func(prop)

        if decoder := self._parse_property_value.get(field_type):
            _LOGGER.debug("Decoding '%s' as type '%s'", prop.name, field_type)
            return decoder(prop)

        _LOGGER.debug("Using '%s' bare property value '%s'", prop.name, prop.value)
        return prop.value

    def encode_property(self, key: str, field_type: type, value: Any) -> ParsedProperty:
        """Encode an individual property for the specified field."""
        # A property field may have multiple possible types, like for
        # a Union. Pick the first type that is able to encode the value.
        errors = []
        prop = None
        for sub_type in self.get_ordered_field_types(field_type):
            if encoder := self._encode_property.get(sub_type):
                try:
                    if prop := encoder(value):
                        break
                    # Encoder returned None, meaning it couldn't encode this value.
                    # We continue to the fallback below or the next sub_type.
                except ValueError as err:
                    _LOGGER.debug(
                        "Encoding failed for property type %s: %s", sub_type, err
                    )
                    errors.append(str(err))
                    continue

            if value is not None and not encoder:
                prop = ParsedProperty(name=key, value=value)
                break

        if prop is None:
            raise ValueError(f"Unable to encode property: {value}, errors: {errors}")

        if not prop.name:
            prop.name = key

        return prop

    def parse_field(
        self,
        field: FieldInfo,
        name: str,
        items: list[ParsedProperty],
    ) -> Any:
        """Parse a list of ParsedProperty items for a specific model field."""
        type_info = get_field_type_info(field.annotation)
        if not type_info.annotation:
            raise ValueError(f"Unable to determine field type for field: {name}")
        if len(items) > 1 and not type_info.is_repeated:
            raise ValueError(f"Expected one value for field: {name}")

        if name in EXPAND_REPEATED_VALUES:
            items = _expand_repeated_property(items)

        validated = [self.parse_property(type_info.annotation, prop) for prop in items]
        return (
            validated
            if type_info.is_repeated
            else (validated[0] if validated else None)
        )

    def register(
        self,
        name: str | None = None,
        disable_value_param: bool = False,
        parse_order: int | None = None,
    ) -> Callable[[T_TYPE], T_TYPE]:
        """Return decorator to register a type.

        The name when specified is the Property Data Type value name.
        """

        def decorator(func: T_TYPE) -> T_TYPE:
            """Register decorated function."""
            if name:
                self._items[name] = func
            data_type = func
            if data_type_func := getattr(func, "__property_type__", None):
                data_type = data_type_func()
            if name:
                self._type_names[data_type] = name
            if parse_property_value := getattr(func, "__parse_property_value__", None):
                self._parse_property_value[data_type] = parse_property_value
                if name:
                    self._parse_parameter_by_name[name] = parse_property_value
            if parse_jcal_value := getattr(func, "__parse_jcal_value__", None):
                self._parse_jcal_value[data_type] = parse_jcal_value
                if name:
                    self._parse_jcal_parameter_by_name[name] = parse_jcal_value
            if encode_property := getattr(func, "__encode_property__", None):
                self._encode_property[data_type] = encode_property
            if encode_property_json := getattr(func, "__encode_property_json__", None):
                self._encode_property_json[data_type] = encode_property_json
            if encode_jcal_value := getattr(func, "__encode_jcal_value__", None):
                self._encode_jcal_value[data_type] = encode_jcal_value
            if disable_value_param:
                self._disable_value_param |= set({data_type})
            if parse_order:
                self._parse_order[data_type] = parse_order
            return func

        return decorator

    def parse_jcal_single_value(
        self,
        field_type: type,
        value: Any,
        params: dict[str, Any],
        type_name: str | None = None,
    ) -> Any:
        """Parse an individual jCal value as the specified field type."""
        field_types = self.get_ordered_field_types(field_type)
        errors = []

        if type_name:
            upper_name = type_name.upper()
            matching = [
                st for st in field_types if self._type_names.get(st) == upper_name
            ]
            non_matching = [
                st for st in field_types if self._type_names.get(st) != upper_name
            ]
            search_types = matching + non_matching
        else:
            search_types = field_types

        for sub_type in search_types:
            if decoder := self._parse_jcal_value.get(sub_type):
                try:
                    try:
                        return decoder(value, params, type_name=type_name)
                    except TypeError:
                        return decoder(value, params)
                except (ValueError, TypeError) as err:
                    _LOGGER.debug(
                        "Unable to parse jCal value as type %s: %s", sub_type, err
                    )
                    errors.append(str(err))
                    continue
            if isinstance(sub_type, type):
                if issubclass(sub_type, (str, int, float, bool)):
                    try:
                        return sub_type(value)
                    except (ValueError, TypeError) as err:
                        errors.append(str(err))
                        continue
                if issubclass(sub_type, BaseModel) and isinstance(value, dict):
                    try:
                        return sub_type.model_validate(value)
                    except (ValueError, TypeError) as err:
                        errors.append(str(err))
                        continue

        if (
            type_name
            and (func := self._parse_jcal_parameter_by_name.get(type_name.upper()))
            and field_type not in self._disable_value_param
        ):
            try:
                return func(value, params)
            except (ValueError, TypeError) as err:
                _LOGGER.debug(
                    "Parsing jCal value '%s' with type name '%s' failed: %s",
                    value,
                    type_name,
                    err,
                )
                errors.append(str(err))

        if value is not None and not errors:
            return value

        type_names = " or ".join(getattr(st, "__name__", str(st)) for st in field_types)
        raise ValueError(
            f"Failed to validate jCal value: {value} as {type_names}, due to: ({errors})"
        )

    def parse_jcal_field(
        self,
        field: FieldInfo,
        name: str,
        props: list[list[Any]],
    ) -> Any:
        """Parse a list of jCal property items for a specific model field."""
        type_info = get_field_type_info(field.annotation)
        if not type_info.annotation:
            raise ValueError(f"Unable to determine field type for field: {name}")

        def _extract_meta(p: list[Any]) -> tuple[dict[str, Any], str | None]:
            params = p[1] if len(p) > 1 and isinstance(p[1], dict) else {}
            type_name = str(p[2]) if len(p) > 2 else None
            return params, type_name

        if type_info.is_repeated:
            if name.lower() in EXPAND_REPEATED_VALUES:
                return [
                    self.parse_jcal_single_value(
                        type_info.annotation, val, params, type_name
                    )
                    for p in props
                    for params, type_name in [_extract_meta(p)]
                    for val in p[3:]
                ]
            return [
                self.parse_jcal_single_value(
                    type_info.annotation,
                    p[3] if len(p) > 3 else "",
                    params,
                    type_name,
                )
                for p in props
                for params, type_name in [_extract_meta(p)]
            ]

        if len(props) > 1:
            raise ValueError(f"Expected one value for field: {name}")

        p = props[0]
        params, type_name = _extract_meta(p)
        return self.parse_jcal_single_value(
            type_info.annotation,
            p[3] if len(p) > 3 else "",
            params,
            type_name,
        )

    def encode_jcal_property(self, key: str, field_type: type, value: Any) -> list[Any]:
        """Encode an individual property value into a jCal 4-element array."""
        errors = []
        for sub_type in self.get_ordered_field_types(field_type):
            encoder = None
            type_name = None
            if isinstance(sub_type, type):
                for base in sub_type.__mro__:
                    if base in self._encode_jcal_value and encoder is None:
                        encoder = self._encode_jcal_value[base]
                    if base in self._type_names and type_name is None:
                        type_name = self._type_names[base]
                    if encoder and type_name:
                        break

            if encoder is None and type_name is not None:
                encoder = lambda val: EncodedJcalValue(
                    {}, [val.value if hasattr(val, "value") else val]
                )

            if encoder:
                try:
                    if result := encoder(value):
                        resolved_type_name = (
                            result.type_name or type_name or "text"
                        ).lower()
                        prop_name = (
                            value.name.lower()
                            if hasattr(value, "name") and key == "extras"
                            else key
                        )
                        return [
                            prop_name,
                            result.params,
                            resolved_type_name,
                            *result.values,
                        ]
                except (ValueError, TypeError) as err:
                    _LOGGER.debug(
                        "jCal encoding failed for property type %s: %s", sub_type, err
                    )
                    errors.append(str(err))
                    continue

        if hasattr(value, "as_jcal"):
            return value.as_jcal(key)

        raise ValueError(
            f"Unable to encode jCal property for field '{key}': {value}, errors: {errors}"
        )

    @property
    def encode_property_json(self) -> dict[type, Callable[[Any], str | dict[str, str]]]:
        """Registry of encoders run during pydantic json serialization."""
        return self._encode_property_json


DATA_TYPE: Registry = Registry()


def encode_model_property_params(
    fields: dict[str, FieldInfo], model_data: dict[str, Any]
) -> list[ParsedPropertyParameter] | None:
    """Encode a pydantic model's parameters as property params."""
    params = []
    for name, field in fields.items():
        key = field.alias or name
        if key == "value" or (values := model_data.get(key)) is None:
            continue
        type_info = get_field_type_info(field.annotation)
        if not type_info.is_repeated:
            values = [values]
        if type_info.annotation is bool:
            values = [
                DATA_TYPE.encode_property("", bool, value).value for value in values
            ]
        params.append(ParsedPropertyParameter(name=key, values=values))
    return params or None


def serialize_field(self: BaseModel, value: Any, info: SerializationInfo) -> Any:
    if not info.context or not info.context.get("ics"):
        return value
    if isinstance(value, list):
        res = []
        for val in value:
            for base in val.__class__.__mro__[:-1]:
                if (func := DATA_TYPE.encode_property_json.get(base)) is not None:
                    res.append(func(val))
                    break
            else:
                res.append(val)
        return res

    for base in value.__class__.__mro__[:-1]:
        if (func := DATA_TYPE.encode_property_json.get(base)) is not None:
            return func(value)
    return value


def _expand_repeated_property(value: list[ParsedProperty]) -> list[ParsedProperty]:
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


def get_field_type_info(annotation: Any) -> FieldTypeInfo:
    """Get information about the field type."""
    return _get_field_type_info(annotation)


@cache
def _get_field_type_info(annotation: Any) -> FieldTypeInfo:
    """Get information about the field type."""
    is_optional = False
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]

    if get_origin(annotation) is Union:
        union_args = get_args(annotation)
        # Filter None out of the Union
        valid_args = [arg for arg in union_args if arg is not NoneType]
        if len(valid_args) < len(union_args):
            is_optional = True
        if len(valid_args) == 1:
            annotation = valid_args[0]
        elif is_optional:
            annotation = Union[tuple(valid_args)]

    is_repeated = get_origin(annotation) is list
    if is_repeated:
        if not (list_args := get_args(annotation)):
            raise ValueError(f"Unable to determine args of type: {annotation}")
        annotation = list_args[0]

    # Handle the case where the list item type is also Optional or Annotated
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]

    if get_origin(annotation) is Union:
        union_args = get_args(annotation)
        valid_args = [arg for arg in union_args if arg is not NoneType]
        if len(valid_args) < len(union_args):
            is_optional = True
        if not valid_args:
            raise ValueError(f"Unable to determine args of type: {annotation}")
        if len(valid_args) == 1:
            annotation = valid_args[0]
        elif is_optional:
            annotation = Union[tuple(valid_args)]

    return FieldTypeInfo(
        annotation=annotation,
        is_repeated=is_repeated,
        is_optional=is_optional,
    )
