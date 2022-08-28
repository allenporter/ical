"""Tests for INTEGER data types."""

import pytest
from pydantic import ValidationError

from ical._types import ComponentModel
from ical.parsing.property import ParsedProperty


class FakeModel(ComponentModel):
    """Model under test."""

    example: list[int]


def test_integer() -> None:
    """Test for int fields."""

    model = FakeModel.parse_obj(
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
        FakeModel.parse_obj({"example": [ParsedProperty(name="example", value="a")]})
