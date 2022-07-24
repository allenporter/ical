"""Tests for property values."""

from ical.contentlines import ParsedComponent, ParsedProperty
from ical.model import ComponentModel
from ical.property_values import Text


class TextModel(ComponentModel):
    """Model with a Text value."""

    text_value: Text

    class Config:
        """Configuration for TextModel."""

        orm_mode = True


def test_text() -> None:
    """Test for a text property value."""
    component = ParsedComponent(name="text-model")
    component.properties.append(
        ParsedProperty(
            name="text_value",
            value="Project XYZ Final Review\\nConference Room - 3B\\nCome Prepared.",
        )
    )
    model = TextModel.parse_obj(component.as_dict())
    assert model == {
        "text_value": "\n".join(
            ["Project XYZ Final Review", "Conference Room - 3B", "Come Prepared."]
        )
    }
