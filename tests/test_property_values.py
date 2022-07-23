"""Tests for property values."""

from pydantic import BaseModel

from ical.contentlines import ParsedProperty
from ical.property_values import Text


class TextModel(BaseModel):
    """Model with a Text value."""

    text_value: Text


def test_text() -> None:
    """Test for a text property value."""
    prop = ParsedProperty(
        value="Project XYZ Final Review\\nConference Room - 3B\\nCome Prepared."
    )
    model = TextModel.parse_obj({"text_value": prop})
    assert model == {
        "text_value": "\n".join(
            ["Project XYZ Final Review", "Conference Room - 3B", "Come Prepared."]
        )
    }
