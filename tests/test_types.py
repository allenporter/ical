"""Tests for property values."""

import datetime
import json
from typing import Optional, Union

from pydantic import BaseModel

from ical.contentlines import ParsedComponent, ParsedProperty
from ical.types import ComponentModel, DateTime, encode_component


def test_text() -> None:
    """Test for a text property value."""

    class TextModel(ComponentModel):
        """Model with a Text value."""

        text_value: str

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


def test_encode_component() -> None:
    """Test for a text property value."""

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


def test_datedatime_parser() -> None:
    """Test for a datetime property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: datetime.datetime

    model = TestModel.parse_obj(
        {
            "dt": [ParsedProperty(name="dt", value="20220724T120000")],
        }
    )
    assert model.dt == datetime.datetime(2022, 7, 24, 12, 0, 0)


def test_date_parser() -> None:
    """Test for a date property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        d: datetime.date

    model = TestModel.parse_obj(
        {
            "d": [ParsedProperty(name="d", value="20220724")],
        }
    )
    assert model.d == datetime.date(2022, 7, 24)


def test_union_date_parser() -> None:
    """Test for a union of multiple date property values."""

    class TestModel(ComponentModel):
        """Model under test."""

        d: Union[datetime.datetime, datetime.date]

    model = TestModel.parse_obj(
        {
            "d": [ParsedProperty(name="d", value="20220724")],
        }
    )
    assert model.d == datetime.date(2022, 7, 24)

    model = TestModel.parse_obj(
        {
            "d": [ParsedProperty(name="d", value="20220724T120000")],
        }
    )
    assert model.d == datetime.datetime(2022, 7, 24, 12, 0, 0)


def test_list_parser() -> None:
    """Test for a repeated property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: list[datetime.datetime]

    model = TestModel.parse_obj(
        {
            "dt": [
                ParsedProperty(name="dt", value="20220724T120000"),
                ParsedProperty(name="dt", value="20220725T130000"),
            ],
        }
    )
    assert model.dt == [
        datetime.datetime(2022, 7, 24, 12, 0, 0),
        datetime.datetime(2022, 7, 25, 13, 0, 0),
    ]


def test_list_union_parser() -> None:
    """Test for a repeated union value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: list[Union[datetime.datetime, datetime.date]]

    model = TestModel.parse_obj(
        {
            "dt": [
                ParsedProperty(name="dt", value="20220724T120000"),
                ParsedProperty(name="dt", value="20220725"),
            ],
        }
    )
    assert model.dt == [
        datetime.datetime(2022, 7, 24, 12, 0, 0),
        datetime.date(2022, 7, 25),
    ]


def test_optional_field_parser() -> None:
    """Test for an optional field parser."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: Optional[datetime.datetime] = None

    model = TestModel.parse_obj(
        {"dt": [ParsedProperty(name="dt", value="20220724T120000")]}
    )
    assert model.dt == datetime.datetime(2022, 7, 24, 12, 0, 0)
