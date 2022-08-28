"""Tests for DATE values."""

import datetime
from typing import Union

import pytest
from pydantic import ValidationError

from ical._types import ComponentModel
from ical.parsing.property import ParsedProperty


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

    with pytest.raises(ValidationError):
        TestModel.parse_obj(
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
