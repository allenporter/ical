"""Tests for UTC-OFFSET data types."""

import datetime

import pytest
from pydantic import ValidationError

from ical._types import ComponentModel
from ical.parsing.property import ParsedProperty
from ical.types import UtcOffset


class FakeModel(ComponentModel):
    """Model under test."""

    example: UtcOffset


def test_utc_offset() -> None:
    """Test for UTC offset fields."""

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="-0400")]}
    )
    assert model.example.offset == datetime.timedelta(hours=-4)

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="0500")]}
    )
    assert model.example.offset == datetime.timedelta(hours=5)

    model = FakeModel(example=UtcOffset(offset=datetime.timedelta(hours=5)))
    assert model.example.offset == datetime.timedelta(hours=5)

    with pytest.raises(ValidationError, match=r".*match UTC-OFFSET pattern.*"):
        FakeModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="abcdef")]},
        )
