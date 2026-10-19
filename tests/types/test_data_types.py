import pytest
from typing import List, Any, cast
from ical.types import RequestStatus
from ical.types.data_types import Registry, _expand_repeated_property
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


def test_expand_repeated_property_escaped_commas() -> None:
    """Test _expand_repeated_property only splits on unescaped commas."""
    props = [
        ParsedProperty(name="categories", value=r"Meeting\, Urgent,Project"),
        ParsedProperty(name="categories", value=r"Single\, Category"),
        ParsedProperty(name="categories", value=r"TrailingSlash\\,Next"),
    ]
    expanded = _expand_repeated_property(props)
    assert [p.value for p in expanded] == [
        r"Meeting\, Urgent",
        "Project",
        r"Single\, Category",
        r"TrailingSlash\\",
        "Next",
    ]


def test_request_status_escaped_delimiters() -> None:
    """Test RequestStatus parsing and encoding with escaped semicolons, commas, and backslashes."""
    prop = ParsedProperty(
        name="request-status",
        value=r"2.0;Success\, fallback\; ok;KEY=VAL\;OTHER=1",
    )
    rs = RequestStatus.__parse_property_value__(prop)
    assert rs.statcode == 2.0
    assert rs.statdesc == "Success, fallback; ok"
    assert rs.exdata == "KEY=VAL;OTHER=1"

    encoded = RequestStatus.__encode_property_json__(rs)
    assert encoded == r"2.0;Success\, fallback\; ok;KEY=VAL\;OTHER=1"

    roundtripped = RequestStatus.__parse_property_value__(
        ParsedProperty(name="request-status", value=encoded)
    )
    assert roundtripped == rs
