"""Tests for RELATED-TO data types."""


import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types import RelatedTo, RelationshipType
from ical.types.data_types import DATA_TYPE


class FakeModel(ComponentModel):
    """Model under test."""

    example: RelatedTo

    class Config:
        """Pydantic model configuration."""

        json_encoders = DATA_TYPE.encode_property_json


def test_default_reltype() -> None:
    """Test for no explicit reltype specified."""
    model = FakeModel.parse_obj(
        {
            "example": [
                ParsedProperty(
                    name="example",
                    value="example-uid@example.com",
                    params=[ParsedPropertyParameter(name="RELTYPE", values=["PARENT"])],
                )
            ]
        },
    )
    assert model.example
    assert model.example.uid == "example-uid@example.com"
    assert model.example.reltype == "PARENT"


@pytest.mark.parametrize(
    "reltype",
    [
        ("PARENT"),
        ("CHILD"),
        ("SIBBLING"),
    ],
)
def test_reltype(reltype: str) -> None:
    """Test for no explicit reltype specified."""

    model = FakeModel.parse_obj(
        {
            "example": [
                ParsedProperty(
                    name="example",
                    value="example-uid@example.com",
                    params=[ParsedPropertyParameter(name="reltype", values=[reltype])],
                )
            ]
        },
    )
    assert model.example
    assert model.example.uid == "example-uid@example.com"
    assert model.example.reltype == reltype


def test_invalid_reltype() -> None:
    with pytest.raises(CalendarParseError):
        FakeModel.parse_obj(
            {
                "example": [
                    ParsedProperty(
                        name="example",
                        value="example-uid@example.com",
                        params=[
                            ParsedPropertyParameter(
                                name="reltype", values=["invalid-reltype"]
                            )
                        ],
                    )
                ]
            },
        )


def test_too_many_reltype_values() -> None:
    with pytest.raises(CalendarParseError):
        FakeModel.parse_obj(
            {
                "example": [
                    ParsedProperty(
                        name="example",
                        value="example-uid@example.com",
                        params=[
                            ParsedPropertyParameter(
                                name="reltype", values=["PARENT", "SIBBLING"]
                            )
                        ],
                    )
                ]
            },
        )


def test_encode_default_reltype() -> None:
    """Test encoded period."""

    model = FakeModel(example=RelatedTo(uid="example-uid@example.com"))
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[
            ParsedProperty(
                name="example",
                value="example-uid@example.com",
                params=[ParsedPropertyParameter(name="RELTYPE", values=["PARENT"])],
            ),
        ],
    )


def test_encode_reltype() -> None:
    """Test encoded period."""

    model = FakeModel(
        example=RelatedTo(uid="example-uid@example.com", reltype=RelationshipType.CHILD)
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[
            ParsedProperty(
                name="example",
                value="example-uid@example.com",
                params=[ParsedPropertyParameter(name="RELTYPE", values=["CHILD"])],
            ),
        ],
    )
