"""Library for parsing and encoding ExtraProperty."""

from dataclasses import dataclass
from typing import Any

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types.data_types import DATA_TYPE


@dataclass
class ExtraPropertyParameter:
    """An extra rfc5545 property parameter."""

    name: str
    values: list[str]


@dataclass
class ExtraProperty:
    """A property that is not defined in the model."""

    name: str
    value: str
    params: list[ExtraPropertyParameter] | None = None


@DATA_TYPE.register(name="ExtraProperty")
class ExtraPropertyEncoder:
    """Encoder for ExtraProperty."""

    @classmethod
    def __property_type__(cls) -> type:
        return ExtraProperty

    @classmethod
    def __encode_property_value__(cls, value: Any) -> ParsedProperty:
        """Encoded the property from the object model to the ics string value."""
        if not isinstance(value, dict):
            raise ValueError(f"Invalid extra property: {value}")
        return ParsedProperty(
            name=value["name"],
            value=value["value"],
            params=[
                ParsedPropertyParameter(name=param["name"], values=param["values"])
                for param in value["params"]
            ]
            if value.get("params")
            else None,
        )

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> ExtraProperty:
        """Convert a ParsedProperty to an ExtraProperty."""
        return ExtraProperty(
            name=prop.name,
            value=prop.value,
            params=[
                ExtraPropertyParameter(
                    name=param.name,
                    # Ignore timezone hack.
                    values=param.values,  # type: ignore[arg-type]
                )
                for param in prop.params
            ]
            if prop.params
            else None,
        )
