import pytest
from typing import List, Union, Any
from ical.types.data_types import Registry
from ical.parsing.property import ParsedProperty


def test_get_ordered_field_types_unsupported_list() -> None:
    """Test get_ordered_field_types with a list that has no arguments."""
    registry = Registry()
    with pytest.raises(ValueError, match="Unable to determine args of type"):
        registry.get_ordered_field_types(List)


def test_encode_property_failed_encoder() -> None:
    """Test encode_property with an encoder that raises ValueError."""
    registry = Registry()

    @registry.register()
    class BadType:
        @classmethod
        def __encode_property__(cls, value: Any) -> ParsedProperty:
            raise ValueError("Encoding failed deliberately")

    with pytest.raises(
        ValueError,
        match=r"Unable to encode property: .*, errors: \['Encoding failed deliberately'\]",
    ):
        registry.encode_property("key", BadType, "some value")


def test_encode_property_no_encoder() -> None:
    """Test encode_property where no encoder is found for a complex type."""
    registry = Registry()

    @registry.register()
    class NoneType:
        @classmethod
        def __encode_property__(cls, value: Any) -> None:
            return None

    with pytest.raises(ValueError, match="Unable to encode property"):
        registry.encode_property("key", NoneType, "some value")


def test_parse_property_failed() -> None:
    """Test parse_property when all parsers fail."""
    registry = Registry()

    @registry.register()
    class FailType:
        @classmethod
        def __parse_property_value__(cls, prop: ParsedProperty) -> Any:
            raise ValueError("Parsing failed deliberately")

    prop = ParsedProperty(name="key", value="val")
    with pytest.raises(
        ValueError,
        match=r"Failed to validate: val as FailType, due to: \(\['Parsing failed deliberately'\]\)",
    ):
        registry.parse_property(FailType, prop)
