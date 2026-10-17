import pytest
from typing import List, Union, Any, cast
from ical.types import RequestStatus
from ical.types.data_types import Registry
from ical.parsing.property import ParsedProperty


def test_get_ordered_field_types_unsupported_list() -> None:
    """Test get_ordered_field_types with a list that has no arguments."""
    registry = Registry()
    with pytest.raises(ValueError, match="Unable to determine args of type"):
        registry.get_ordered_field_types(cast(Any, List))


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
        match=r"Failed to validate 'val' as FailType: Parsing failed deliberately",
    ):
        registry.parse_property(FailType, prop)


def test_get_ordered_field_types_tie_order() -> None:
    """Test get_ordered_field_types when multiple Union args have the same parse_order."""
    registry = Registry()
    types = registry.get_ordered_field_types(cast(Any, Union[int, str]))
    assert set(types) == {int, str}


def test_request_status_escaping_and_3_level_statcode() -> None:
    """Test RequestStatus parsing and encoding with escaped semicolons and 3-level codes."""
    prop = ParsedProperty(
        name="request-status",
        value=r"2.0.1;Success\, fallback\; ok;KEY=VAL\;OTHER=1",
    )
    rs = RequestStatus.__parse_property_value__(prop)
    assert rs.statcode == "2.0.1"
    assert rs.statdesc == "Success, fallback; ok"
    assert rs.exdata == "KEY=VAL;OTHER=1"

    encoded = RequestStatus.__encode_property_json__(rs)
    assert encoded == r"2.0.1;Success\, fallback\; ok;KEY=VAL\;OTHER=1"

    roundtripped = RequestStatus.__parse_property_value__(
        ParsedProperty(name="request-status", value=encoded)
    )
    assert roundtripped == rs

    # Trailing zero preservation
    rs_trailing = RequestStatus.__parse_property_value__(
        ParsedProperty(name="request-status", value="2.10;Ok")
    )
    assert rs_trailing.statcode == "2.10"

    # Invalid status code
    with pytest.raises(ValueError, match="Invalid Request Status statcode"):
        RequestStatus.__parse_property_value__(
            ParsedProperty(name="request-status", value="abc;Invalid")
        )
