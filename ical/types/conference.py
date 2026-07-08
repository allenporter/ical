"""Library for parsing and encoding CONFERENCE values."""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

import enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ical.parsing.property import ParsedProperty

from .const import ExtensibleEnum
from .data_types import DATA_TYPE, encode_model_property_params
from .parsing import parse_parameter_values
from .uri import Uri


class Feature(ExtensibleEnum):
    """The feature parameter for a conference."""

    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    CHAT = "CHAT"
    SCREEN = "SCREEN"
    MORE = "MORE"


@DATA_TYPE.register("CONFERENCE")
class Conference(BaseModel):
    """A value type for a property that contains conference information."""

    uri: Uri = Field(alias="value")
    """The conference URI."""

    feature: Optional[list[Feature]] = Field(alias="FEATURE", default=None)
    """The features of the conference."""

    label: Optional[str] = Field(alias="LABEL", default=None)
    """The user-friendly label for the conference."""

    language: Optional[str] = Field(alias="LANGUAGE", default=None)
    """The language parameter."""

    _parse_parameter_values = model_validator(mode="before")(parse_parameter_values)

    __parse_property_value__ = dataclasses.asdict

    @classmethod
    def __encode_property__(cls, model_data: dict[str, Any]) -> ParsedProperty:
        """Encode the property."""
        return ParsedProperty(
            name="",
            value=str(model_data.pop("value")),
            params=encode_model_property_params(cls.model_fields, model_data),
        )

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)
