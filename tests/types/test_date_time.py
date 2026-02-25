"""Tests for DATE-TIME values."""

import datetime
from typing import Union

from pydantic import field_serializer
import pytest


from ical.exceptions import CalendarParseError
from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types.data_types import serialize_field
from ical.tzif import timezoneinfo


def test_datedatime_parser() -> None:
    """Test for a datetime property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: datetime.datetime

    model = TestModel.model_validate(
        {
            "dt": [ParsedProperty(name="dt", value="20220724T120000")],
        }
    )
    assert model.dt == datetime.datetime(2022, 7, 24, 12, 0, 0)

    # Build from an object
    model = TestModel(dt=datetime.datetime(2022, 7, 20, 13, 0, 0))
    assert model.dt.isoformat() == "2022-07-20T13:00:00"


def test_datedatime_value_parser() -> None:
    """Test a datetime with a property parameter value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: Union[datetime.datetime, datetime.date]

    model = TestModel.model_validate(
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
    model = TestModel.model_validate(
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

    # Unknown VALUE types fall back to TEXT parsing (RFC 5545 graceful degradation)
    # However, if the resulting TEXT value is invalid for the field type,
    # Pydantic validation should still catch it
    with pytest.raises(CalendarParseError):
        TestModel.model_validate(
            {
                "dt": [
                    ParsedProperty(
                        name="dt",
                        value="not-a-valid-datetime-or-date",
                        params=[
                            ParsedPropertyParameter(name="VALUE", values=["INVALID"]),
                        ],
                    )
                ],
            }
        )


def test_datedatime_parameter_encoder() -> None:
    """Test a datetime with a property parameter encoded in the output."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: datetime.datetime

        serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]

    model = TestModel.model_validate(
        {
            "dt": [
                ParsedProperty(
                    name="dt",
                    value="20220724T120000",
                    params=[
                        ParsedPropertyParameter(
                            name="TZID", values=["America/New_York"]
                        ),
                    ],
                )
            ],
        }
    )
    assert model.dt == datetime.datetime(
        2022, 7, 24, 12, 0, 0, tzinfo=timezoneinfo.read_tzinfo("America/New_York")
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="TestModel",
        properties=[
            ParsedProperty(
                name="dt",
                value="20220724T120000",
                params=[
                    ParsedPropertyParameter(name="TZID", values=["America/New_York"])
                ],
            )
        ],
    )

    with pytest.raises(CalendarParseError, match="valid timezone"):
        TestModel.model_validate(
            {
                "dt": [
                    ParsedProperty(
                        name="dt",
                        value="20220724T120000",
                        params=[
                            ParsedPropertyParameter(
                                name="TZID",
                                values=["Example"],
                            ),
                        ],
                    )
                ],
            }
        )
