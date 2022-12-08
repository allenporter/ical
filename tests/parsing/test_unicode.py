"""Tests for unicode specific handling."""

import pytest

from ical.parsing.unicode import SAFE_CHAR, VALUE_CHAR


def test_safe_char_excludes() -> None:
    """Test that the safe char definition excludes the right set of characters."""
    assert '"' not in SAFE_CHAR
    assert ";" not in SAFE_CHAR
    assert "," not in SAFE_CHAR

    assert "a" in SAFE_CHAR


def test_safe_char() -> None:
    """Test some basic values that should be in safe char."""
    assert "a" in SAFE_CHAR
    assert "-" in SAFE_CHAR
    assert "🎄" in SAFE_CHAR


def test_value_char() -> None:
    """Test some basic values that should be in value char."""
    assert "a" in VALUE_CHAR
    assert "-" in VALUE_CHAR
    assert '"' in VALUE_CHAR
    assert ";" in VALUE_CHAR
    assert "," in VALUE_CHAR
    assert "🎄" in VALUE_CHAR


@pytest.mark.parametrize(
    "word",
    [
        "žmogus",
        "中文",
        "кириллица",
        "Ελληνικά",
        "עִברִית",
        "日本語",
        "한국어",
        "ไทย",
        "देवनागरी",
    ],
)
def test_languages(word: str) -> None:
    """Test basic values in non-english character sets are valid."""
    for char in word:
        assert char in VALUE_CHAR
