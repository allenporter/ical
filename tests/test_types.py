"""Tests for property values."""

import datetime
from typing import Optional, Union

import pytest
from pydantic import BaseModel, ValidationError

from ical.contentlines import ParsedComponent, ParsedProperty, ParsedPropertyParameter
from ical.types import ICS_ENCODERS, ComponentModel, Geo, Period, Priority, encode_model


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
    assert encode_model("model", model) == ParsedComponent(
        name="model",
        properties=[
            ParsedProperty(
                name="text_value",
                value="Project XYZ Final Review\\nConference Room - 3B\\nCome Prepared.",
            )
        ],
    )


def test_encode_component() -> None:
    """Test for a text property value."""

    class OtherComponent(BaseModel):
        """Model used as a sub-component."""

        other_value: str
        second_value: Optional[str] = None

    class TestModel(ComponentModel):
        """Model with a Text value."""

        text_value: str
        repeated_text_value: list[str]
        some_component: list[OtherComponent]
        single_component: OtherComponent
        dt: datetime.datetime

        class Config:
            """Pydantic model configuration."""

            json_encoders = ICS_ENCODERS

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
            "dt": [ParsedProperty(name="dt", value="20220724T120000")],
        }
    )
    component = encode_model("TestModel", model)
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


def test_datedatime_value_parser() -> None:
    """Test a datetime with a property paramer value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: Union[datetime.datetime, datetime.date]

    model = TestModel.parse_obj(
        {
            "dt": [
                ParsedProperty(
                    name="dt",
                    value="20220724T120000",
                    params=[
                        ParsedPropertyParameter(name="VALUE", values=["DATE-TIME"]),
                    ],
                )
            ],
        }
    )
    assert model.dt == datetime.datetime(2022, 7, 24, 12, 0, 0)
    model = TestModel.parse_obj(
        {
            "dt": [
                ParsedProperty(
                    name="dt",
                    value="20220724",
                    params=[
                        ParsedPropertyParameter(name="VALUE", values=["DATE"]),
                    ],
                )
            ],
        }
    )
    assert model.dt == datetime.date(2022, 7, 24)

    with pytest.raises(ValidationError):
        TestModel.parse_obj(
            {
                "dt": [
                    ParsedProperty(
                        name="dt",
                        value="20220724T120000",
                        params=[
                            ParsedPropertyParameter(name="VALUE", values=["INVALID"]),
                        ],
                    )
                ],
            }
        )

    with pytest.raises(ValidationError):
        TestModel.parse_obj(
            {
                "dt": [
                    ParsedProperty(
                        name="dt",
                        value="20220724",
                        params=[
                            ParsedPropertyParameter(name="VALUE", values=["INVALID"]),
                        ],
                    )
                ],
            }
        )


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


def test_priority() -> None:
    """Test for priority fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        pri: Priority

    model = TestModel.parse_obj({"pri": [ParsedProperty(name="dt", value="1")]})
    assert model.pri == 1

    model = TestModel.parse_obj({"pri": [ParsedProperty(name="dt", value="9")]})
    assert model.pri == 9

    with pytest.raises(ValidationError):
        TestModel.parse_obj({"pri": [ParsedProperty(name="dt", value="-1")]})

    with pytest.raises(ValidationError):
        TestModel.parse_obj({"pri": [ParsedProperty(name="dt", value="10")]})


def test_bool() -> None:
    """Test for boolean fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        example: bool

    model = TestModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="TRUE")]}
    )
    assert model.example

    model = TestModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="FALSE")]}
    )
    assert not model.example

    with pytest.raises(ValidationError):
        TestModel.parse_obj({"example": [ParsedProperty(name="example", value="efd")]})


@pytest.mark.parametrize(
    "value,duration,encoded_value",
    [
        (
            "P15DT5H0M20S",
            datetime.timedelta(days=15, hours=5, seconds=20),
            "P2W1DT5H20S",
        ),
        ("P7W", datetime.timedelta(days=7 * 7), "P7W"),
    ],
)
def test_duration(value: str, duration: datetime.timedelta, encoded_value: str) -> None:
    """Test for duration fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        duration: datetime.timedelta

    model = TestModel.parse_obj(
        {"duration": [ParsedProperty(name="duration", value=value)]}
    )
    assert model.duration == duration
    component = encode_model("TestModel", model)
    assert component.name == "TestModel"
    assert component.properties == [
        ParsedProperty(name="duration", value=encoded_value)
    ]


def test_geo() -> None:
    """Test for geo fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        geo: Geo

    model = TestModel.parse_obj(
        {"geo": [ParsedProperty(name="geo", value="120.0;-30.1")]}
    )
    assert model.geo.lat == 120.0
    assert model.geo.lng == -30.1

    with pytest.raises(ValidationError):
        TestModel.parse_obj({"geo": [ParsedProperty(name="geo", value="10")]})


def test_integer() -> None:
    """Test for int fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        example: list[int]

    model = TestModel.parse_obj(
        {
            "example": [
                ParsedProperty(name="example", value="45"),
                ParsedProperty(name="example", value="-46"),
                ParsedProperty(name="example", value="+47"),
            ]
        }
    )
    assert model.example == [45, -46, 47]

    with pytest.raises(ValidationError):
        TestModel.parse_obj({"example": [ParsedProperty(name="example", value="a")]})


def test_float() -> None:
    """Test for float fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        example: list[float]

    model = TestModel.parse_obj(
        {
            "example": [
                ParsedProperty(name="example", value="45"),
                ParsedProperty(name="example", value="-46.2"),
                ParsedProperty(name="example", value="+47.32"),
            ]
        }
    )
    assert model.example == [45, -46.2, 47.32]

    with pytest.raises(ValidationError):
        TestModel.parse_obj({"example": [ParsedProperty(name="example", value="a")]})


def test_period() -> None:
    """Test for duration fields."""

    class TestModel(ComponentModel):
        """Model under test."""

        example: Period

    # Time period with end date
    model = TestModel.parse_obj(
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
    model = TestModel.parse_obj(
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
        TestModel.parse_obj({"example": [ParsedProperty(name="example", value="a")]})

    with pytest.raises(ValidationError):
        TestModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="19970101T180000Z/a")]}
        )

    with pytest.raises(ValidationError):
        TestModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="a/19970102T070000Z")]}
        )

    with pytest.raises(ValidationError):
        TestModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="a/PT5H30M")]}
        )
