"""Library for returning details about a timezone."""

from functools import cache
from importlib import resources

from .model import TimezoneInfo
from .tzif import read_tzif


@cache
def read_timezones() -> set[str]:
    """Returns the set of valid timezones."""
    with resources.files("tzdata").joinpath("zones").open(
        "r", encoding="utf-8"
    ) as zones_file:
        return {line.strip() for line in zones_file.readlines()}


def iana_key_to_resource(key: str) -> tuple[str, str]:
    """Returns the package and resource file for the specified timezone."""
    if "/" not in key:
        return "tzdata.zoneinfo", key
    package_loc, resource = key.rsplit("/", 1)
    package = "tzdata.zoneinfo." + package_loc.replace("/", ".")
    return package, resource


def read(key: str) -> TimezoneInfo:
    """Read the TZif file from the tzdata package and return timezone records."""
    (package, resource) = iana_key_to_resource(key)
    with resources.files(package).joinpath(resource).open("rb") as tzdata_file:
        return read_tzif(tzdata_file.read())
