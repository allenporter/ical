"""Tests for RELATED-TO data types."""

from pydantic import field_serializer
import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types import CalAddress, CalendarUserType, ParticipationStatus, Role
from ical.types.data_types import serialize_field


class FakeModel(ComponentModel):
    """Model under test."""

    example: CalAddress

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]


def test_caladdress_role() -> None:
    """Test for no explicit reltype specified."""
    model = FakeModel.model_validate(
        {
            "example": [
                ParsedProperty(
                    name="attendee",
                    value="mailto:mrbig@example.com",
                    params=[
                        ParsedPropertyParameter(name="ROLE", values=["CHAIR"]),
                        ParsedPropertyParameter(name="CUTYPE", values=["INDIVIDUAL"]),
                    ],
                )
            ]
        },
    )
    assert model.example
    assert model.example.uri == "mailto:mrbig@example.com"
    assert model.example.role == Role.CHAIR
    assert model.example.user_type == "INDIVIDUAL"


def test_caladdress_role_parse_failure() -> None:
    """Test for no explicit reltype specified."""
    model = FakeModel.model_validate(
        {
            "example": [
                ParsedProperty(
                    name="attendee",
                    value="mailto:mrbig@example.com",
                    params=[
                        ParsedPropertyParameter(name="ROLE", values=["OTHER-ROLE"]),
                        ParsedPropertyParameter(name="CUTYPE", values=["OTHER-CUTYPE"]),
                    ],
                )
            ]
        },
    )
    assert model.example
    assert model.example.uri == "mailto:mrbig@example.com"
    assert model.example.role == "OTHER-ROLE"
    assert model.example.user_type == "OTHER-CUTYPE"


def test_caladdress_enums_case_insensitive() -> None:
    """Test case-insensitive lookup on CalendarUserType, ParticipationStatus, and Role."""
    assert CalendarUserType("individual") == CalendarUserType.INDIVIDUAL
    assert CalendarUserType("Group") == CalendarUserType.GROUP
    assert ParticipationStatus("needs-action") == ParticipationStatus.NEEDS_ACTION
    assert ParticipationStatus("Accepted") == ParticipationStatus.ACCEPTED
    assert Role("req-participant") == Role.REQUIRED
    assert Role("Chair") == Role.CHAIR
