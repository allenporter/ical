"""Implementation of the RELATED-TO property."""

import enum
from dataclasses import dataclass
from typing import Any, Self
import logging

from pydantic import model_validator

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

from .data_types import DATA_TYPE
from .parsing import parse_parameter_values


@DATA_TYPE.register("RELATIONSHIP-TYPE")
class RelationshipType(str, enum.Enum):
    """Type of hierarchical relationship associated with the calendar component."""

    PARENT = "PARENT"
    """Parent relationship - Default."""

    CHILD = "CHILD"
    """Child relationship."""

    SIBBLING = "SIBBLING"
    """Sibling relationship."""

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> Self | None:
        """Parse value into enum."""
        try:
            return cls(prop.value)
        except ValueError:
            return None


@DATA_TYPE.register("RELATED-TO")
@dataclass
class RelatedTo:
    """Used to represent a relationship or reference between one calendar component and another."""

    uid: str
    """The value of the related-to property is the persistent, globally unique identifier of another calendar component."""

    reltype: RelationshipType = RelationshipType.PARENT
    """Indicate the type of hierarchical relationship associated with the calendar component specified by the uid."""

    @classmethod
    def __parse_property_value__(cls, prop: Any) -> dict[str, Any]:
        """Parse a rfc5545 int value."""
        logging.info("prop=%s", prop)
        if isinstance(prop, ParsedProperty):
            data: dict[str, Any] = {"uid": prop.value}
            for param in prop.params or ():
                if len(param.values) > 1:
                    raise ValueError("Expected only one value for RELATED-TO parameter")
                data[param.name] = param.values[0]
            return data
        return {"uid": prop}

    _parse_parameter_values = model_validator(mode="before")(parse_parameter_values)

    @classmethod
    def __encode_property_value__(cls, model_data: dict[str, str]) -> str | None:
        return model_data.pop("uid")

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        if "reltype" not in model_data:
            return []
        return [ParsedPropertyParameter(name="RELTYPE", values=[model_data["reltype"]])]
