"""Library for parsing and encoding CAL-ADDRESS values."""

from __future__ import annotations

from collections.abc import Callable, Generator
import dataclasses
import enum
import logging
from typing import Any, Optional

try:
    from pydantic.v1 import BaseModel, Field, root_validator
except ImportError:
    from pydantic import BaseModel, Field, root_validator  # type: ignore[no-redef, assignment]


from ical.parsing.property import ParsedPropertyParameter

from .data_types import DATA_TYPE, encode_model_property_params
from .parsing import parse_parameter_values
from .uri import Uri
from .enum import create_enum_validator

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

    _parse_parameter_values = root_validator(pre=True, allow_reuse=True)(
        parse_parameter_values
    )

    __parse_property_value__ = dataclasses.asdict

    @classmethod
    def __encode_property_value__(cls, model_data: dict[str, str]) -> str | None:
        return model_data.pop("value")

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        return encode_model_property_params(cls.__fields__.values(), model_data)

    class Config:
        """Pyandtic model configuration."""

        allow_population_by_field_name = True
