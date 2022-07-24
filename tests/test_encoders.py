"""Tests for encoders."""

import datetime
import json
from typing import Optional

from pydantic import BaseModel

from ical.contentlines import ParsedComponent, ParsedProperty
from ical.encoders import encode_component
from ical.property_values import DateTime


class OtherComponent(BaseModel):
    """Model used as a sub-component."""

    other_value: str
    second_value: Optional[str] = None


class TextModel(BaseModel):
    """Model with a Text value."""

    text_value: str
    repeated_text_value: list[str]
    some_component: list[OtherComponent]
    single_component: OtherComponent
    dt: DateTime

    class Config:
        """Configuration for TextModel pydantic model."""

        json_encoders = {
            datetime.datetime: DateTime.ics,
        }


def test_encode_component() -> None:
    """Test for a text property value."""
    model = TextModel.parse_obj(
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
        "TextModel", json.loads(model.json(exclude_unset=True))
    )
    assert component.name == "TextModel"
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
