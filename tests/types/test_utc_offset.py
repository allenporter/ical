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

    model = FakeModel.model_validate(
        {"example": [ParsedProperty(name="example", value="-0400")]}
    )
    assert model.example.offset == datetime.timedelta(hours=-4)

    model = FakeModel.model_validate(
        {"example": [ParsedProperty(name="example", value="0500")]}
    )
    assert model.example.offset == datetime.timedelta(hours=5)

    model = FakeModel(example=UtcOffset(offset=datetime.timedelta(hours=5)))
    assert model.example.offset == datetime.timedelta(hours=5)

    with pytest.raises(CalendarParseError, match=r".*match UTC-OFFSET pattern.*"):
        FakeModel.model_validate(
            {"example": [ParsedProperty(name="example", value="abcdef")]},
        )


def test_optional_seconds() -> None:
    """Test for UTC offset fields with optional seconds."""
    model = FakeModel.model_validate(
        {"example": [ParsedProperty(name="example", value="+0019")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=19)

    model = FakeModel.model_validate(
        {"example": [ParsedProperty(name="example", value="+001932")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=19, seconds=32)

    model = FakeModel.model_validate(
        {"example": [ParsedProperty(name="example", value="-0019")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=-19)

    model = FakeModel.model_validate(
        {"example": [ParsedProperty(name="example", value="-001932")]}
    )
    assert model.example.offset == datetime.timedelta(minutes=-19, seconds=-32)
    assert UtcOffset.__encode_property_json__(model.example) == "-001932"
    assert (
        UtcOffset.__encode_property_json__(
            UtcOffset(datetime.timedelta(minutes=19, seconds=32))
        )
        == "+001932"
    )
    assert (
        UtcOffset.__encode_property_json__(UtcOffset(datetime.timedelta(hours=-5)))
        == "-0500"
    )


def test_utc_offset_out_of_range() -> None:
    """Test that out-of-range hours, minutes, or seconds are rejected."""
    for invalid in ("+2400", "-2500", "+0060", "+000060"):
        with pytest.raises(CalendarParseError, match="UTC-OFFSET out of range"):
            FakeModel.model_validate(
                {"example": [ParsedProperty(name="example", value=invalid)]}
            )
