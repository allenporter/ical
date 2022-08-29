"""Tests for DURATION data types."""

import datetime

import pytest
from pydantic import ValidationError

from ical._types import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty
from ical.types import Period
from ical.types.data_types import DATA_TYPE


class FakeModel(ComponentModel):
    """Model under test."""

    example: Period

    class Config:
        """Pydantic model configuration."""

        json_encoders = DATA_TYPE.encode_property_json


def test_period() -> None:
    """Test for period fields."""

    # Time period with end date
    model = FakeModel.parse_obj(
        {
            "example": [
                ParsedProperty(
                    name="example", value="19970101T180000Z/19970102T070000Z"
                )
            ]
        },
    )
    assert model.example.start == datetime.datetime(
        1997, 1, 1, 18, 0, 0, tzinfo=datetime.timezone.utc
    )
    assert model.example.end
    assert not model.example.duration
    assert model.example.end_value == datetime.datetime(
        1997, 1, 2, 7, 0, 0, tzinfo=datetime.timezone.utc
    )

    # Time period with duration
    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="19970101T180000Z/PT5H30M")]},
    )
    assert model.example.start == datetime.datetime(
        1997, 1, 1, 18, 0, 0, tzinfo=datetime.timezone.utc
    )

    assert not model.example.end
    assert model.example.duration
    assert model.example.end_value == datetime.datetime(
        1997, 1, 1, 23, 30, 0, tzinfo=datetime.timezone.utc
    )

    with pytest.raises(ValidationError):
        FakeModel.parse_obj({"example": [ParsedProperty(name="example", value="a")]})

    with pytest.raises(ValidationError):
        FakeModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="19970101T180000Z/a")]}
        )

    with pytest.raises(ValidationError):
        FakeModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="a/19970102T070000Z")]}
        )

    with pytest.raises(ValidationError):
        FakeModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="a/PT5H30M")]}
        )


def test_encode_period() -> None:
    """Test encoded period."""

    model = FakeModel(
        example=Period(
            start=datetime.datetime(2022, 8, 7, 6, 0, 0),
            end=datetime.datetime(2022, 8, 7, 6, 30, 0),
        )
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[
            ParsedProperty(name="example", value="20220807T060000/20220807T063000")
        ],
    )

    model = FakeModel(
        example=Period(
            start=datetime.datetime(2022, 8, 7, 6, 0, 0),
            duration=datetime.timedelta(hours=5, minutes=30),
        )
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[ParsedProperty(name="example", value="20220807T060000/PT5H30M")],
    )
