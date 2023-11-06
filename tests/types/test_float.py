"""Tests for FLOAT data types."""

import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
from ical.parsing.property import ParsedProperty


class FakeModel(ComponentModel):
    """Model under test."""

    example: list[float]


def test_float() -> None:
    """Test for float fields."""

    model = FakeModel.parse_obj(
        {
            "example": [
                ParsedProperty(name="example", value="45"),
                ParsedProperty(name="example", value="-46.2"),
                ParsedProperty(name="example", value="+47.32"),
            ]
        }
    )
    assert model.example == [45, -46.2, 47.32]

    with pytest.raises(CalendarParseError):
        FakeModel.parse_obj({"example": [ParsedProperty(name="example", value="a")]})

    model = FakeModel(example=[1, -2.2, 3.5])
    assert model.example == [1, -2.2, 3.5]
