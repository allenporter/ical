"""Library for parsing and encoding IMAGE values."""

from __future__ import annotations

import base64
import binascii
import dataclasses
from typing import Any, Optional

import enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from ical.parsing.property import ParsedProperty

from .const import ExtensibleEnum
from .data_types import DATA_TYPE, EncodedJcalValue, encode_model_property_params
from .parsing import parse_parameter_values
from .uri import Uri


class Display(ExtensibleEnum):
    """The display parameter for an image."""

    BADGE = "BADGE"
    THUMBNAIL = "THUMBNAIL"
    FULLSIZE = "FULLSIZE"


@DATA_TYPE.register("IMAGE", disable_value_param=True)
class Image(BaseModel):
    """A value type for a property that contains an image."""

    uri: Optional[Uri] = None
    """The image as a URI."""

    content: Optional[bytes] = None
    """The image as base64-encoded binary data."""

    encoding: Optional[str] = Field(alias="ENCODING", default=None)
    """The encoding parameter."""

    format_type: Optional[str] = Field(alias="FMTTYPE", default=None)
    """The format type parameter."""

    altrep: Optional[Uri] = Field(alias="ALTREP", default=None)
    """The alternate representation parameter."""

    display: Optional[Display] = Field(alias="DISPLAY", default=None)
    """The display parameter (e.g. BADGE, THUMBNAIL, FULLSIZE)."""

    value_attr: Optional[str] = Field(alias="VALUE", default=None)
    """The value parameter."""

    @model_validator(mode="before")
    @classmethod
    def parse_image(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse image values."""
        if not isinstance(values, dict):
            return values

        values = parse_parameter_values(cls, values)

        # Determine if it's binary or URI
        value = values.pop("value", None)
        if (
            value is not None
            and values.get("uri") is None
            and values.get("content") is None
        ):
            value_type = values.get("VALUE")
            encoding = values.get("ENCODING")
            if value_type == "BINARY" or encoding == "BASE64":
                try:
                    # Strip whitespaces/newlines from the base64 content
                    clean_value = "".join(value.split())
                    rem = len(clean_value) % 4
                    if rem > 0:
                        clean_value += "=" * (4 - rem)
                    values["content"] = base64.b64decode(clean_value)
                except binascii.Error as err:
                    raise ValueError(f"Failed to decode base64 binary image: {err}")
            else:
                values["uri"] = Uri(value)
        return values

    @field_serializer("content")
    def serialize_content(self, content: Optional[bytes]) -> Optional[str]:
        """Serialize content to base64 string."""
        if content is None:
            return None
        return base64.b64encode(content).decode("ascii")

    __parse_property_value__ = dataclasses.asdict

    @classmethod
    def __parse_jcal_value__(
        cls, value: Any, params: dict[str, Any], type_name: str | None = None
    ) -> Image:
        """Parse an RFC 7265 jCal image property."""
        if isinstance(value, Image):
            return value
        data: dict[str, Any] = {"value": value, "params": dict(params)}
        if type_name and type_name.upper() == "BINARY":
            data["params"]["VALUE"] = "BINARY"
        return cls.model_validate(data)

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode as jCal parameters and value list."""
        if isinstance(value, Image):
            params: dict[str, Any] = {}
            if value.format_type:
                params["fmttype"] = value.format_type
            if value.display:
                params["display"] = (
                    value.display.value
                    if isinstance(value.display, enum.Enum)
                    else str(value.display)
                )
            if value.altrep:
                params["altrep"] = str(value.altrep)
            if value.content is not None:
                content_str = (
                    base64.b64encode(value.content).decode("ascii")
                    if isinstance(value.content, bytes)
                    else str(value.content)
                )
                return EncodedJcalValue(params, [content_str], type_name="binary")
            return EncodedJcalValue(params, [str(value.uri or "")], type_name="uri")
        return None

    @classmethod
    def __encode_property__(cls, model_data: dict[str, Any]) -> ParsedProperty:
        """Encode the property."""
        content = model_data.pop("content", None)
        uri = model_data.pop("uri", None)

        if content is not None:
            if isinstance(content, bytes):
                value = base64.b64encode(content).decode("ascii")
            else:
                value = content
            model_data["VALUE"] = "BINARY"
            model_data["ENCODING"] = "BASE64"
        elif uri is not None:
            value = str(uri)
        else:
            value = ""

        return ParsedProperty(
            name="",
            value=value,
            params=encode_model_property_params(cls.model_fields, model_data),
        )

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)
