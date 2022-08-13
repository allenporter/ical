"""Tests for the tzif library."""

import zoneinfo

import pytest

from ical.tzif import tzif


@pytest.mark.parametrize("key", tzif.read_timezones())
def test_all_tzdata(key: str) -> None:
    """Verify that all available timezones in the system have valid tzdata."""
    result = tzif.read(key)
    assert result.rule or result.transitions or result.leap_seconds


@pytest.mark.parametrize("key", zoneinfo.available_timezones())
def test_all_zoneinfo(key: str) -> None:
    """Verify that all available timezones in the system have valid tzdata."""
    if key.startswith("System") or key == "localtime":
        return
    result = tzif.read(key)
    assert result.rule or result.transitions or result.leap_seconds
