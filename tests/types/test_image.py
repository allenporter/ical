"""Tests for Image data type."""

from __future__ import annotations

import pytest
from pydantic import Field, ValidationError, field_serializer

from ical.component import ComponentModel
from ical.types import Image, Display, Uri
from ical.types.data_types import serialize_field


class FakeImageModel(ComponentModel):
    """Model under test for Image."""

    image: list[Image] = Field(default_factory=list)

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]


def test_image_parse_non_dict_error() -> None:
    """Test that passing a non-dict to Image parsing raises a ValidationError."""
    with pytest.raises(ValidationError):
        Image.model_validate("not-a-dict")


def test_image_parse_binary_padding() -> None:
    """Test parsing binary image base64 value requiring padding."""
    # "aGVsbG8" is "hello" without padding (7 chars). Remainder 3.
    img_padded = Image.model_validate(
        {"value": "aGVsbG8", "VALUE": "BINARY", "ENCODING": "BASE64"}
    )
    assert img_padded.content == b"hello"


def test_image_parse_invalid_base64_error() -> None:
    """Test that parsing invalid base64 content raises a ValidationError."""
    with pytest.raises(ValidationError, match="Failed to decode base64 binary image"):
        Image.model_validate(
            {"value": "invalid-base64-!!!", "VALUE": "BINARY", "ENCODING": "BASE64"}
        )


def test_image_encode_empty() -> None:
    """Test that encoding an empty image yields an empty value."""
    encoded = Image.__encode_property__({})
    assert encoded.value == ""


def test_image_encode_raw_bytes() -> None:
    """Test that encoding raw bytes dynamically base64-encodes the content."""
    encoded_bytes = Image.__encode_property__({"content": b"hello"})
    assert encoded_bytes.value == "aGVsbG8="


def test_image_serialize_content_none() -> None:
    """Test that serializing None content returns None."""
    assert Image().serialize_content(None) is None


def test_image_altrep_parameter() -> None:
    """Test parsing of the ALTREP parameter on the Image property."""
    img_altrep = Image.model_validate(
        {
            "value": "http://example.com/logo.png",
            "ALTREP": "http://example.com/logo.svg",
        }
    )
    assert img_altrep.uri == Uri("http://example.com/logo.png")
    assert img_altrep.altrep == Uri("http://example.com/logo.svg")


def test_display_enum() -> None:
    """Test Display enum validation and fallback handling."""
    assert Display("BADGE") == Display.BADGE
    assert Display("badge") == Display.BADGE  # case insensitive fallback lookup
    assert Display("x-custom") == "x-custom"  # custom token fallback
    assert Display._missing_(None) is None


def test_copy_and_validate_binary_image() -> None:
    """Test that copy_and_validate does not double-encode binary image content."""
    raw_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    model = FakeImageModel(
        image=[Image(content=raw_bytes, FMTTYPE="image/png")],
    )
    assert model.image[0].model_dump()["content"] == raw_bytes

    updated = model.copy_and_validate({})
    assert isinstance(updated, FakeImageModel)
    assert updated.image[0].content == raw_bytes

    updated_twice = updated.copy_and_validate({})
    assert isinstance(updated_twice, FakeImageModel)
    assert updated_twice.image[0].content == raw_bytes
