"""Tests for property values."""

from ical.component import ComponentModel
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty


class Model(ComponentModel):
    """Model with a Text value."""

    text_value: str


def test_text() -> None:
    """Test for a text property value."""

    component = ParsedComponent(name="text-model")
    component.properties.append(
        ParsedProperty(
            name="text_value",
            value="Project XYZ Final Review\\nConference Room - 3B\\nCome Prepared.",
        )
    )
    model = Model.model_validate(component.as_dict())
    assert model == Model(
        text_value="\n".join(
            ["Project XYZ Final Review", "Conference Room - 3B", "Come Prepared."]
        )
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="Model",
        properties=[
            ParsedProperty(
                name="text_value",
                value="Project XYZ Final Review\\nConference Room - 3B\\nCome Prepared.",
            )
        ],
    )


def test_text_from_obj() -> None:
    """Test text when creating from an object."""
    model = Model.model_validate({"text_value": "some-value"})
    assert model == Model(text_value="some-value")
