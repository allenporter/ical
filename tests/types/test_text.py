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


def test_text_control_characters() -> None:
    """Test that control characters are stripped from text values."""
    model = Model.model_validate({"text_value": "some\x01value"})
    assert model.__encode_component_root__() == ParsedComponent(
        name="Model",
        properties=[
            ParsedProperty(
                name="text_value",
                value="somevalue",
            )
        ],
    )


def test_text_escaping_combinations() -> None:
    """Test parsing and encoding of various escaped characters."""
    # Test rfc5545 escaped characters: \\n, \\N, \\;, \\,, \\\\
    component = ParsedComponent(name="text-model")
    component.properties.append(
        ParsedProperty(
            name="text_value",
            value=r"old\\new and a\;b and c\,d and e\\f and g\nh and i\Nj",
        )
    )
    model = Model.model_validate(component.as_dict())
    assert model.text_value == "old\\new and a;b and c,d and e\\f and g\nh and i\nj"

    # Test round trip encoding
    encoded = model.__encode_component_root__()
    assert encoded == ParsedComponent(
        name="Model",
        properties=[
            ParsedProperty(
                name="text_value",
                value=r"old\\new and a\;b and c\,d and e\\f and g\nh and i\nj",
            )
        ],
    )


def test_text_literal_escaped_characters() -> None:
    """Test that literal backslashes followed by delimiter characters are parsed correctly."""
    # Input has escaped backslash followed by ;, ,, n
    component = ParsedComponent(name="text-model")
    component.properties.append(
        ParsedProperty(
            name="text_value",
            value=r"path\\name and delim\\; and comma\\, and double\\\\slash",
        )
    )
    model = Model.model_validate(component.as_dict())
    assert model.text_value == r"path\name and delim\; and comma\, and double\\slash"

    # When encoded, the literal backslashes and delimiters are properly escaped
    encoded = model.__encode_component_root__()
    assert encoded == ParsedComponent(
        name="Model",
        properties=[
            ParsedProperty(
                name="text_value",
                value=r"path\\name and delim\\\; and comma\\\, and double\\\\slash",
            )
        ],
    )

    # When decoded again, we get the exact same text_value back
    reparsed = Model.model_validate(encoded.as_dict())
    assert reparsed.text_value == model.text_value
