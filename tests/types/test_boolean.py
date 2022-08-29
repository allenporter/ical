"""Tests for BOOLEAN data types."""

import pytest
from pydantic import ValidationError

from ical.component import ComponentModel
from ical.parsing.property import ParsedProperty


class FakeModel(ComponentModel):
    """Model under test."""

    example: bool


def test_bool() -> None:
    """Test for boolean fields."""

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="TRUE")]}
    )
    assert model.example

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="FALSE")]}
    )
    assert not model.example

    with pytest.raises(ValidationError):
        FakeModel.parse_obj({"example": [ParsedProperty(name="example", value="efd")]})

    # Populate based on bool object
    model = FakeModel(example=True)
    assert model.example
    component = model.__encode_component_root__()
    assert component.properties == [
        ParsedProperty(name="example", value="TRUE"),
    ]

    model = FakeModel(example=False)
    assert not model.example
    component = model.__encode_component_root__()
    assert component.properties == [
        ParsedProperty(name="example", value="FALSE"),
    ]
