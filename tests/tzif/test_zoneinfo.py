"""Tests for the tzif library."""

import zoneinfo

import pytest

from ical.tzif import timezoneinfo


def test_invalid_zoneinfo() -> None:
    """Verify exception handling for an invalid timezone."""

    with pytest.raises(timezoneinfo.TimezoneInfoError, match="Unable to find timezone"):
        timezoneinfo.read("invalid")


@pytest.mark.parametrize("key", zoneinfo.available_timezones())
def test_all_zoneinfo(key: str) -> None:
    """Verify that all available timezones in the system have valid tzdata."""
    if key.startswith("System") or key == "localtime":
        return
    result = timezoneinfo.read(key)
    assert result.rule or result.transitions or result.leap_seconds
