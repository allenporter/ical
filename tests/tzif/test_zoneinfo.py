"""Tests for the tzif library."""

import zoneinfo

import pytest

from ical.tzif import timezoneinfo


@pytest.mark.parametrize("key", timezoneinfo.read_timezones())
def test_all_tzdata(key: str) -> None:
    """Verify that all available timezones in the system have valid tzdata."""
    result = timezoneinfo.read(key)
    assert result.rule or result.transitions or result.leap_seconds


@pytest.mark.parametrize("key", zoneinfo.available_timezones())
def test_all_zoneinfo(key: str) -> None:
    """Verify that all available timezones in the system have valid tzdata."""
    if key.startswith("System") or key == "localtime":
        return
    result = timezoneinfo.read(key)
    assert result.rule or result.transitions or result.leap_seconds
