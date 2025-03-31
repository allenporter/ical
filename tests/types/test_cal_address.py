"""Tests for RELATED-TO data types."""

import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types import CalAddress, Role
from ical.types.data_types import DATA_TYPE


class FakeModel(ComponentModel):
    """Model under test."""

    example: CalAddress

    class Config:
        """Pydantic model configuration."""

        json_encoders = DATA_TYPE.encode_property_json


def test_caladdress_role() -> None:
    """Test for no explicit reltype specified."""
    model = FakeModel.parse_obj(
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
    model = FakeModel.parse_obj(
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
