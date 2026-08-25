"""Library for parsing and encoding ExtraProperty."""

from dataclasses import dataclass
from typing import Any

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types.data_types import DATA_TYPE, EncodedJcalValue


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


@DATA_TYPE.register(name="UNKNOWN", disable_value_param=True)
class ExtraPropertyEncoder:
    """Encoder for ExtraProperty."""

    @classmethod
    def __property_type__(cls) -> type:
        return ExtraProperty

    @classmethod
    def __encode_property__(cls, value: Any) -> ParsedProperty:
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
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode as jCal parameters and value list."""
        if isinstance(value, ExtraProperty):
            params_dict: dict[str, Any] = {}
            if value.params:
                for p in value.params:
                    params_dict[p.name.lower()] = (
                        p.values[0] if len(p.values) == 1 else p.values
                    )
            return EncodedJcalValue(params_dict, [value.value])
        if isinstance(value, dict):
            params_dict = {}
            for p in value.get("params", []):
                params_dict[p["name"].lower()] = (
                    p["values"][0] if len(p["values"]) == 1 else p["values"]
                )
            return EncodedJcalValue(params_dict, [value["value"]])
        return None

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
                    values=[v for v in param.values if isinstance(v, str)],
                )
                for param in prop.params
            ]
            if prop.params
            else None,
        )

    @classmethod
    def __parse_jcal_value__(
        cls, value: Any, params: dict[str, Any], name: str = ""
    ) -> ExtraProperty:
        """Parse an RFC 7265 jCal property into an ExtraProperty."""
        params_list = (
            [
                ExtraPropertyParameter(
                    name=k.upper(),
                    values=[v] if isinstance(v, str) else [str(x) for x in v],
                )
                for k, v in params.items()
            ]
            if params
            else None
        )
        return ExtraProperty(name=name, value=value, params=params_list)
