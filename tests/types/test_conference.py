"""Tests for Conference data type."""

from __future__ import annotations

from ical.types import Conference, Feature, Uri


def test_conference_properties() -> None:
    """Test programmatic validation of Conference parameters."""
    conf = Conference.model_validate(
        {
            "value": "https://zoom.us/j/123",
            "FEATURE": ["AUDIO"],
            "LABEL": "My Zoom",
            "LANGUAGE": "en-US",
        }
    )
    assert conf.uri == Uri("https://zoom.us/j/123")
    assert conf.feature == [Feature.AUDIO]
    assert conf.label == "My Zoom"
    assert conf.language == "en-US"


def test_feature_enum() -> None:
    """Test Feature enum validation and fallback handling."""
    assert Feature("AUDIO") == Feature.AUDIO
    assert Feature("audio") == Feature.AUDIO  # case insensitive fallback lookup
    assert Feature("x-custom") == "x-custom"  # custom token fallback
    assert Feature._missing_(None) is None
