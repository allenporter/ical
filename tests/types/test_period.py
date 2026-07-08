"""Tests for DURATION data types."""

import datetime

from pydantic import field_serializer
import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty
from ical.types import Period
from ical.types.period import FreeBusyType
from ical.types.data_types import serialize_field


class FakeModel(ComponentModel):
    """Model under test."""

    example: Period

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]


def test_period() -> None:
    """Test for period fields."""

    # Time period with end date
    model = FakeModel.model_validate(
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
    model = FakeModel.model_validate(
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

    with pytest.raises(CalendarParseError):
        FakeModel.model_validate(
            {"example": [ParsedProperty(name="example", value="a")]}
        )

    with pytest.raises(CalendarParseError):
        FakeModel.model_validate(
            {"example": [ParsedProperty(name="example", value="19970101T180000Z/a")]}
        )

    with pytest.raises(CalendarParseError):
        FakeModel.model_validate(
            {"example": [ParsedProperty(name="example", value="a/19970102T070000Z")]}
        )

    with pytest.raises(CalendarParseError):
        FakeModel.model_validate(
            {"example": [ParsedProperty(name="example", value="a/PT5H30M")]}
        )


def test_encode_period() -> None:
    """Test encoded period."""

    model = FakeModel(
        example=Period(
            start=datetime.datetime(2022, 8, 7, 6, 0, 0),
            end=datetime.datetime(2022, 8, 7, 6, 30, 0),
        )
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[
            ParsedProperty(name="example", value="20220807T060000/20220807T063000")
        ],
    )

    model = FakeModel(
        example=Period(
            start=datetime.datetime(2022, 8, 7, 6, 0, 0),
            duration=datetime.timedelta(hours=5, minutes=30),
        )
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[ParsedProperty(name="example", value="20220807T060000/PT5H30M")],
    )


def test_free_busy_type_parse() -> None:
    """Test FreeBusyType parsing."""
    assert (
        FreeBusyType.__parse_property_value__(
            ParsedProperty(name="FBTYPE", value="BUSY-UNAVAILABLE")
        )
        == FreeBusyType.BUSY_UNAVAILABLE
    )
    assert (
        FreeBusyType.__parse_property_value__(
            ParsedProperty(name="FBTYPE", value="INVALID")
        )
        is None
    )


def test_period_missing_end_and_duration() -> None:
    """Test period end_value raises ValueError when end and duration are missing."""
    p = Period.model_construct(start=datetime.datetime.now())
    with pytest.raises(
        ValueError, match="Invalid period missing both end and duration"
    ):
        _ = p.end_value


def test_period_invalid_part_count() -> None:
    """Test period validation fails with invalid part count."""
    with pytest.raises(CalendarParseError, match="Period did not have two time values"):
        FakeModel.model_validate(
            {"example": [ParsedProperty(name="example", value="a/b/c")]}
        )


def test_encode_period_errors() -> None:
    """Test period encoding error cases."""
    # 1. Non-dict input
    assert Period.__encode_property__("not a dict") is None

    # 2. Missing start
    with pytest.raises(ValueError, match="Invalid period object missing start"):
        Period.__encode_property__({"end": "20220808T120000"})

    # 3. Missing both end and duration
    with pytest.raises(
        ValueError, match="Invalid period missing both end and duration"
    ):
        Period.__encode_property__({"start": "20220808T100000"})
