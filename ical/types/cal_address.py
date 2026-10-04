"""Library for parsing and encoding CAL-ADDRESS values."""

from __future__ import annotations

import dataclasses
import enum
import logging
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

from .data_types import DATA_TYPE, EncodedJcalValue, encode_model_property_params
from .parsing import parse_parameter_values
from .uri import Uri

_LOGGER = logging.getLogger(__name__)


class CalendarUserType(str, enum.Enum):
    """The type of calendar user."""

    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    RESOURCE = "RESOURCE"
    ROOM = "ROOM"
    UNKNOWN = "UNKNOWN"


class ParticipationStatus(str, enum.Enum):
    """Participation status for a calendar user."""

    NEEDS_ACTION = "NEEDS-ACTION"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    # Additional statuses for Events and Todos
    TENTATIVE = "TENTATIVE"
    DELEGATED = "DELEGATED"
    # Additional status for TODOs
    COMPLETED = "COMPLETED"


class Role(str, enum.Enum):
    """Role for the calendar user."""

    CHAIR = "CHAIR"
    REQUIRED = "REQ-PARTICIPANT"
    OPTIONAL = "OPT-PARTICIPANT"
    NON_PARTICIPANT = "NON-PARTICIPANT"


@DATA_TYPE.register("CAL-ADDRESS")
class CalAddress(BaseModel):
    """A value type for a property that contains a calendar user address."""

    uri: Uri = Field(alias="value")
    """The calendar user address as a uri."""

    common_name: Optional[str] = Field(alias="CN", default=None)
    """The common name associated with the calendar user."""

    user_type: Optional[str] = Field(alias="CUTYPE", default=None)
    """The type of calendar user specified by the property.
    Common values are defined in CalendarUserType, though also supports other
    values not known by this library so it uses a string.
    """

    delegator: Optional[list[Uri]] = Field(alias="DELEGATED-FROM", default=None)
    """The users that have delegated their participation to this user."""

    delegate: Optional[list[Uri]] = Field(alias="DELEGATED-TO", default=None)
    """The users to whom the user has delegated participation."""

    directory_entry: Optional[Uri] = Field(alias="DIR", default=None)
    """Reference to a directory entry associated with the calendar user."""

    member: Optional[list[Uri]] = Field(alias="MEMBER", default=None)
    """The group or list membership of the calendar user."""

    status: Optional[str] = Field(alias="PARTSTAT", default=None)
    """The participation status for the calendar user."""

    role: Optional[str] = Field(alias="ROLE", default=None)
    """The participation role for the calendar user."""

    rsvp: Optional[bool] = Field(alias="RSVP", default=None)
    """Whether there is an expectation of a favor of a reply from the calendar user."""

    sent_by: Optional[Uri] = Field(alias="SENT-BY", default=None)
    """Specifies the calendar user is acting on behalf of another user."""

    language: Optional[str] = Field(alias="LANGUAGE", default=None)

    _parse_parameter_values = model_validator(mode="before")(parse_parameter_values)

    __parse_property_value__ = dataclasses.asdict

    @classmethod
    def __parse_jcal_value__(cls, value: Any, params: dict[str, Any]) -> CalAddress:
        """Parse an RFC 7265 jCal cal-address property."""
        if isinstance(value, CalAddress):
            return value
        return cls.model_validate({"value": value, "params": params})

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode as jCal parameters and value list."""
        if isinstance(value, CalAddress):
            params: dict[str, Any] = {}
            for name, field in cls.model_fields.items():
                if name == "uri" or (val := getattr(value, name)) is None:
                    continue
                key = (field.alias or name).lower()
                if isinstance(val, list):
                    params[key] = [str(x) for x in val]
                elif isinstance(val, enum.Enum):
                    params[key] = val.value
                elif isinstance(val, Uri):
                    params[key] = str(val)
                else:
                    params[key] = val
            return EncodedJcalValue(params, [str(value.uri)])
        if isinstance(value, dict):
            val = value.get("value", "")
            params = {
                p["name"].lower(): (
                    p["values"][0] if len(p["values"]) == 1 else p["values"]
                )
                for p in value.get("params", [])
            }
            return EncodedJcalValue(params, [val])
        return None

    @classmethod
    def __encode_property__(cls, model_data: dict[str, Any]) -> ParsedProperty:
        """Encode the property."""
        return ParsedProperty(
            name="",
            value=model_data.pop("value"),
            params=encode_model_property_params(cls.model_fields, model_data),
        )

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)
