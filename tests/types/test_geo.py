"""Library for GEO values."""

import pytest
from pydantic import ValidationError

from ical.component import ComponentModel
from ical.parsing.property import ParsedProperty
from ical.types.geo import Geo


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
