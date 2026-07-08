"""Tests for DATE values."""

import datetime
from typing import Union

from pydantic import field_serializer
import pytest

from ical.exceptions import CalendarParseError
from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types.data_types import serialize_field


def test_date_parser() -> None:
    """Test for a date property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        d: datetime.date

    model = TestModel.model_validate(
        {
            "d": [ParsedProperty(name="d", value="20220724")],
        }
    )
    assert model.d == datetime.date(2022, 7, 24)

    with pytest.raises(CalendarParseError):
        TestModel.model_validate(
            {
                "d": [
                    ParsedProperty(
                        name="dt",
                        value="invalid-value",
                    )
                ],
            }
        )

    # Build from an object
    model = TestModel(d=datetime.date(2022, 7, 20))
    assert model.d.isoformat() == "2022-07-20"


def test_union_date_parser() -> None:
    """Test for a union of multiple date property values."""

    class TestModel(ComponentModel):
        """Model under test."""

        d: Union[datetime.datetime, datetime.date]

    model = TestModel.model_validate(
        {
            "d": [ParsedProperty(name="d", value="20220724")],
        }
    )
    assert model.d == datetime.date(2022, 7, 24)

    model = TestModel.model_validate(
        {
            "d": [ParsedProperty(name="d", value="20220724T120000")],
        }
    )
    assert model.d == datetime.datetime(2022, 7, 24, 12, 0, 0)


def test_date_encoder() -> None:
    """Test encoding of date property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        d: datetime.date
        serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]

    model = TestModel(d=datetime.date(2022, 7, 24))
    assert model.__encode_component_root__() == ParsedComponent(
        name="TestModel",
        properties=[
            ParsedProperty(
                name="d",
                value="20220724",
                params=[
                    ParsedPropertyParameter(name="VALUE", values=["DATE"]),
                ],
            )
        ],
    )


def test_date_encoder_fallback() -> None:
    """Test that DateEncoder returns None for values that are not plain date strings."""
    from ical.types.date import DateEncoder

    assert DateEncoder.__encode_property__("20220724T120000") is None
    assert DateEncoder.__encode_property__({"VALUE": "20220724"}) is None
