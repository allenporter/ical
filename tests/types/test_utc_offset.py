"""Tests for UTC-OFFSET data types."""

import datetime

import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
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

    with pytest.raises(CalendarParseError, match=r".*match UTC-OFFSET pattern.*"):
        FakeModel.parse_obj(
            {"example": [ParsedProperty(name="example", value="abcdef")]},
        )


def test_optional_seconds() -> None:
    """Test for UTC offset fields with optional seconds."""
    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="+0019")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=19)

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="+001932")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=19, seconds=32)

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="-0019")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=-19)

    model = FakeModel.parse_obj(
        {"example": [ParsedProperty(name="example", value="-001932")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=-19, seconds=-32)
