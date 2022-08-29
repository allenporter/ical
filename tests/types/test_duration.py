"""Tests for DURATION data types."""

import datetime

import pytest

from ical._types import ComponentModel
from ical.parsing.property import ParsedProperty
from ical.types.data_types import DATA_TYPE


class FakeModel(ComponentModel):
    """Model under test."""

    duration: datetime.timedelta

    class Config:
        """Pydantic model configuration."""

        json_encoders = DATA_TYPE.encode_property_json


@pytest.mark.parametrize(
    "value,duration,encoded_value",
    [
        (
            "P15DT5H0M20S",
            datetime.timedelta(days=15, hours=5, seconds=20),
            "P2W1DT5H20S",
        ),
        ("P7W", datetime.timedelta(days=7 * 7), "P7W"),
        ("-P7W", datetime.timedelta(days=-7 * 7), "-P7W"),
    ],
)
def test_duration(value: str, duration: datetime.timedelta, encoded_value: str) -> None:
    """Test for duration fields."""

    model = FakeModel.parse_obj(
        {"duration": [ParsedProperty(name="duration", value=value)]}
    )
    assert model.duration == duration
    component = model.__encode_component_root__()
    assert component.name == "FakeModel"
    assert component.properties == [
        ParsedProperty(name="duration", value=encoded_value)
    ]


def test_duration_from_object() -> None:
    """Test for a duration field from a native object."""

    model = FakeModel(duration=datetime.timedelta(hours=1))
    assert model.duration == datetime.timedelta(hours=1)

    component = model.__encode_component_root__()
    assert component.name == "FakeModel"
    assert component.properties == [ParsedProperty(name="duration", value="PT1H")]
