"""Tests for Image data type."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ical.types import Image, Display, Uri


def test_image_edge_cases() -> None:
    """Test edge cases in Image parsing and encoding to cover missing paths."""

    # 1. Non-dict input to parse_image (Line 49)
    with pytest.raises(ValidationError):
        Image.model_validate("not-a-dict")

    # 2. Binary image needing base64 padding (Line 68)
    # "aGVsbG8" is "hello" without padding (7 chars). Remainder 3.
    img_padded = Image.model_validate(
        {"value": "aGVsbG8", "VALUE": "BINARY", "ENCODING": "BASE64"}
    )
    assert img_padded.content == b"hello"

    # 3. Invalid base64 (Lines 70-71)
    with pytest.raises(ValidationError, match="Failed to decode base64 binary image"):
        Image.model_validate(
            {"value": "invalid-base64-!!!", "VALUE": "BINARY", "ENCODING": "BASE64"}
        )

    # 4. Empty image serialization (Line 101)
    encoded = Image.__encode_property__({})
    assert encoded.value == ""

    # 5. Raw bytes passed to __encode_property__ (Line 93)
    encoded_bytes = Image.__encode_property__({"content": b"hello"})
    assert encoded_bytes.value == "aGVsbG8="

    # 6. None value to serialize_content (Line 80)
    assert Image().serialize_content(None) is None

    # 7. ALTREP parameter validation
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
