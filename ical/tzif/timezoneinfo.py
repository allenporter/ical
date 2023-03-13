"""Library for returning details about a timezone.

This package follows the same approach as zoneinfo for loading timezone
data. It first checks the system TZPATH, then falls back to the tzdata
python package.
"""

from __future__ import annotations

import datetime
import logging
import os
import zoneinfo
from dataclasses import dataclass
from functools import cache
from importlib import resources

from .model import TimezoneInfo
from .tz_rule import Rule, RuleDate
from .tzif import read_tzif

_LOGGER = logging.getLogger(__name__)


class TimezoneInfoError(Exception):
    """Raised on error working with timezone information."""


@cache
def _read_system_timezones() -> set[str]:
    """Read and cache the set of system and tzdata timezones."""
    return zoneinfo.available_timezones()


def _find_tzfile(key: str) -> str | None:
    """Retrieve the path to a TZif file from a key."""
    for search_path in zoneinfo.TZPATH:
        filepath = os.path.join(search_path, key)
        if os.path.isfile(filepath):
            return filepath

    return None


@cache
def _read_tzdata_timezones() -> set[str]:
    """Returns the set of valid timezones from tzdata only."""
    try:
        with resources.files("tzdata").joinpath("zones").open(
            "r", encoding="utf-8"
        ) as zones_file:
            return {line.strip() for line in zones_file.readlines()}
    except ModuleNotFoundError:
        return set()


def _iana_key_to_resource(key: str) -> tuple[str, str]:
    """Returns the package and resource file for the specified timezone."""
    if "/" not in key:
        return "tzdata.zoneinfo", key
    package_loc, resource = key.rsplit("/", 1)
    package = "tzdata.zoneinfo." + package_loc.replace("/", ".")
    return package, resource


def read(key: str) -> TimezoneInfo:
    """Read the TZif file from the tzdata package and return timezone records."""
    if key not in _read_system_timezones() and key not in _read_tzdata_timezones():
        raise TimezoneInfoError(f"Unable to find timezone in system timezones: {key}")

    # Prefer tzdata package
    (package, resource) = _iana_key_to_resource(key)
    try:
        with resources.files(package).joinpath(resource).open("rb") as tzdata_file:
            return read_tzif(tzdata_file.read())
    except ModuleNotFoundError:
        # Unexpected given we previously read the list of timezones
        pass
    except FileNotFoundError as err:
        raise TimezoneInfoError(f"Unable to load tzdata module: {key}") from err

    # Fallback to zoneinfo file on local disk
    tzfile = _find_tzfile(key)
    if tzfile is not None:
        with open(tzfile, "rb") as tzfile_file:
            return read_tzif(tzfile_file.read())

    raise TimezoneInfoError(f"Unable to find timezone data for {key}")


_ZERO = datetime.timedelta(0)
_HOUR = datetime.timedelta(hours=1)


@dataclass
class TzInfoResult:
    """Contains timezone information for a specific datetime."""

    utcoffset: datetime.timedelta
    tzname: str | None
    dst: datetime.timedelta | None


class TzInfo(datetime.tzinfo):
    """An implementation of tzinfo based on a TimezoneInfo for current TZ rules.

    This class is not as complete of an implementation of pythons zoneinfo rules as
    it currently ignores historical timezone information. Instead, it uses only the
    posix TZ rules that apply going forward only, but applies them for all time.

    This class uses the default implementation of fromutc.
    """

    def __init__(self, rule: Rule) -> None:
        """Initialize TzInfo."""
        self._rule: Rule = rule

    @classmethod
    def from_timezoneinfo(cls, timezoneinfo: TimezoneInfo) -> TzInfo:
        """Create a new instance of a TzInfo."""
        if not timezoneinfo.rule:
            raise ValueError("Unable to make TzInfo from TimezoneInfo, missing rule")
        return cls(timezoneinfo.rule)

    def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta:
        """Return offset of local time from UTC, as a timedelta object."""
        if not dt:
            return _ZERO
        result = self._rule.std.offset
        if dst_offset := self.dst(dt):
            result += dst_offset
        return result

    def tzname(self, dt: datetime.datetime | None) -> str | None:
        """Return the time zone name for the datetime as a sorting."""
        if dt is None:
            return None
        if self.dst(dt) and self._rule.dst:
            return self._rule.dst.name
        return self._rule.std.name

    def dst(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
        """Return the daylight saving time (DST) adjustment, if applicable."""
        if (
            dt is None
            or not self._rule.dst
            or not isinstance(self._rule.dst_start, RuleDate)
            or not isinstance(self._rule.dst_end, RuleDate)
            or not self._rule.dst.offset
        ):
            return None

        dt_year = datetime.datetime(dt.year, 1, 1)
        dst_start = next(iter(self._rule.dst_start.as_rrule(dt_year)))
        dst_end = next(iter(self._rule.dst_end.as_rrule(dt_year)))
        if dst_start <= dt.replace(tzinfo=None) < dst_end:
            dst_offset = self._rule.dst.offset - self._rule.std.offset
            return dst_offset

        return _ZERO


def read_tzinfo(key: str) -> TzInfo:
    """Create a zoneinfo implementation from raw tzif data."""
    timezoneinfo = read(key)
    try:
        return TzInfo.from_timezoneinfo(timezoneinfo)
    except ValueError as err:
        raise TimezoneInfoError(f"Unable create TzInfo: {key}") from err
