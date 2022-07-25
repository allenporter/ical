"""Tests for property values."""

import datetime
import json
from typing import Optional

from pydantic import BaseModel

from ical.contentlines import ParsedComponent, ParsedProperty
from ical.types import ComponentModel, DateTime, Text, encode_component


class TextModel(ComponentModel):
    """Model with a Text value."""

    text_value: Text


def test_text() -> None:
    """Test for a text property value."""
    component = ParsedComponent(name="text-model")
    component.properties.append(
        ParsedProperty(
            name="text_value",
            value="Project XYZ Final Review\\nConference Room - 3B\\nCome Prepared.",
        )
    )
    model = TextModel.parse_obj(component.as_dict())
    assert model == {
        "text_value": "\n".join(
            ["Project XYZ Final Review", "Conference Room - 3B", "Come Prepared."]
        )
    }


class OtherComponent(BaseModel):
    """Model used as a sub-component."""

    other_value: str
    second_value: Optional[str] = None


class TestModel(BaseModel):
    """Model with a Text value."""

    text_value: str
    repeated_text_value: list[str]
    some_component: list[OtherComponent]
    single_component: OtherComponent
    dt: DateTime

    class Config:
        """Configuration for TestModel pydantic model."""

        json_encoders = {
            datetime.datetime: DateTime.ics,
        }


def test_encode_component() -> None:
    """Test for a text property value."""
    model = TestModel.parse_obj(
        {
            "text_value": "Example text",
            "repeated_text_value": ["a", "b", "c"],
            "some_component": [
                {"other_value": "value1", "second_value": "valuez"},
                {"other_value": "value2"},
            ],
            "single_component": {
                "other_value": "value3",
            },
            "dt": ParsedProperty(name="dt", value="20220724T120000"),
        }
    )
    component = encode_component(
        "TestModel", json.loads(model.json(exclude_unset=True))
    )
    assert component.name == "TestModel"
    assert component.properties == [
        ParsedProperty(name="text_value", value="Example text"),
        ParsedProperty(name="repeated_text_value", value="a"),
        ParsedProperty(name="repeated_text_value", value="b"),
        ParsedProperty(name="repeated_text_value", value="c"),
        ParsedProperty(name="dt", value="20220724T120000"),
    ]
    assert component.components == [
        ParsedComponent(
            name="some_component",
            properties=[
                ParsedProperty(name="other_value", value="value1"),
                ParsedProperty(name="second_value", value="valuez"),
            ],
        ),
        ParsedComponent(
            name="some_component",
            properties=[
                ParsedProperty(name="other_value", value="value2"),
            ],
        ),
        ParsedComponent(
            name="single_component",
            properties=[
                ParsedProperty(name="other_value", value="value3"),
            ],
        ),
    ]
