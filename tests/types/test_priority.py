"""Tests for PRIORITY types."""

import pytest
from ical.exceptions import CalendarParseError

from ical.component import ComponentModel
from ical.parsing.property import ParsedProperty
from ical.types import Priority


class FakeModel(ComponentModel):
    """Model under test."""

    pri: Priority


def test_priority() -> None:
    """Test for priority fields."""

    model = FakeModel.parse_obj({"pri": [ParsedProperty(name="dt", value="1")]})
    assert model.pri == 1

    model = FakeModel.parse_obj({"pri": [ParsedProperty(name="dt", value="9")]})
    assert model.pri == 9

    with pytest.raises(CalendarParseError):
        FakeModel.parse_obj({"pri": [ParsedProperty(name="dt", value="-1")]})

    with pytest.raises(CalendarParseError):
        FakeModel.parse_obj({"pri": [ParsedProperty(name="dt", value="10")]})
