"""Library for reading python tzdata files.

An rfc5545 calendar references timezones in an unambiguous way, defined
by a set of specific transitions. As a result, a calendar must have
complete information about the timezones it references.

Python's zoneinfo package does not expose a full representation of system
supported timezones. It will use the system defined timezone, but then also
may fallback to the tzdata package as a fallback.

This package uses the tzdata package as a definition for timezones, under
the assumption that it should be similar to existing python supported
timezones.

Note: This implementation is more verbose than the zoneinfo implementation
and contains more documentation and references to the file format to serve
as a resource for understanding the format. See rfc8536 for TZif file format.
"""

import enum
import io
import struct
from collections import namedtuple
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Sequence

from .model import LeapSecond, TimezoneInfo, Transition

# Records specifying the local time type
LOCAL_TIME_TYPE_STRUCT_FORMAT = "".join(
    [
        ">",  # Use standard size of packed value bytes
        "l",  # utoff (4 bytes): Number of seconds to add to UTC to determine local time
        "?",  # dst (1 byte): Indicates the time is DST (1) or standard (0)
        "B",  # idx (1 byte): Offset index into the time zone designiation octets (0-charcnt-1)
    ]
)
LOCAL_TIME_RECORD_SIZE = 6


class TzifError(Exception):
    """Thrown when there is an error with Timezone information."""


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


class TZifVersion(enum.Enum):
    """Defines information related to TZifVersions."""

    V1 = (b"\x00", 4, "l")  # 32-bit in v1
    V2 = (b"2", 8, "q")  # 64-bit in v2+
    V3 = (b"3", 8, "q")

    def __init__(self, version: bytes, time_size: int, time_format: str):
        self._version = version
        self._time_size = time_size
        self._time_format = time_format

    @property
    def version(self) -> bytes:
        """Return the version byte string."""
        return self._version

    @property
    def time_size(self) -> int:
        """Return the TIME_SIZE used in the data block parsing."""
        return self._time_size

    @property
    def time_format(self) -> str:
        """Return the struct unpack format string for TIME_SIZE objects."""
        return self._time_format


@dataclass
class Header:
    """TZif Header information."""

    SIZE = 44  # Total size of the header to read
    STRUCT_FORMAT = "".join(
        [
            ">",  # Use standard size of packed value bytes
            "4s",  # magic (4 bytes)
            "c",  # version (1 byte)
            "15x",  # unused
            "6l",  # isutccnt, isstdcnt, leapcnt, timecnt, typecnt, charcnt
        ]
    )
    MAGIC = "TZif".encode()

    version: bytes
    """The version of the files format."""

    isutccnt: int
    """The number of UTC/local indicators in the data block."""

    isstdcnt: int
    """The number of standard/wall indicators in the data block."""

    leapcnt: int
    """The number of leap second records in the data block."""

    timecnt: int
    """The number of time transitions in the data block."""

    typecnt: int
    """The number of local time type records in the data block."""

    charcnt: int
    """The number of characters for time zone designations in the data block."""

    @classmethod
    def from_bytes(cls, header_bytes: bytes) -> "Header":
        """Parse the header bytes into a file."""
        (
            magic,
            version,
            isutccnt,
            isstdcnt,
            leapcnt,
            timecnt,
            typecnt,
            charcnt,
        ) = struct.unpack(Header.STRUCT_FORMAT, header_bytes)
        if magic != Header.MAGIC:
            raise ValueError("zoneinfo file did not contain magic header")
        if isutccnt not in (0, typecnt):
            raise ValueError(
                f"UTC/local indicators in datablock mismatched ({isutccnt}, {typecnt})"
            )
        if isstdcnt not in (0, typecnt):
            raise ValueError(
                f"standard/wall indicators in datablock mismatched ({isutccnt}, {typecnt})"
            )
        return Header(version, isutccnt, isstdcnt, leapcnt, timecnt, typecnt, charcnt)


TransitionBlock = namedtuple(
    "TransitionBlock", ["transition_time", "time_type", "isstdcnt", "isutccnt"]
)

# A series of records specifying the local time type:
#  - utoff (4 bytes): Number of seconds to add to UTC to determine local time
#  - dst (1 byte): Indicates the time is DST (1) or standard (0)
#  - idx (1 byte):  Offset index into the time zone designiation octets (0-charcnt-1)
# is the utoff (4 bytes), dst (1 byte), idx (1 byte).
LocalTimeType = namedtuple("LocalTimeType", ["utoff", "dst", "idx"])


def new_transition(
    transition: TransitionBlock,
    local_time_types: list[LocalTimeType],
    get_tz_designations: Callable[[int], str],
) -> Transition:
    """ddd."""
    if transition.time_type >= len(local_time_types):
        raise ValueError(
            f"transition_type out of bounds {transition.time_type} >= {len(local_time_types)}"
        )
    if transition.isutccnt and not transition.isstdcnt:
        raise ValueError("isutccnt was True but isstdcnt was False")
    (utoff, dst, idx) = local_time_types[transition.time_type]
    return Transition(
        transition.transition_time,
        utoff,
        dst,
        transition.isstdcnt,
        transition.isutccnt,
        get_tz_designations(idx),
    )


def read_datablock(
    header: Header, version: TZifVersion, buf: io.BytesIO
) -> tuple[list[Transition], list[LeapSecond]]:
    """Read records from the buffer."""
    # A series of leap-time values in sorted order
    transition_times = struct.unpack(
        f">{header.timecnt}{version.time_format}",
        buf.read(header.timecnt * version.time_size),
    )

    # A series of integers specifying the type of local time of the corresponding
    # transition time. These are zero-based indices into the array of local
    # time type records. (from 0 to typecnt-1)
    transition_types: Sequence[int] = []
    if header.timecnt > 0:
        transition_types = struct.unpack(
            f">{header.timecnt}B", buf.read(header.timecnt)
        )

    local_time_types: list[LocalTimeType] = [
        LocalTimeType._make(
            struct.unpack(
                LOCAL_TIME_TYPE_STRUCT_FORMAT, buf.read(LOCAL_TIME_RECORD_SIZE)
            )
        )
        for _ in range(header.typecnt)
    ]

    # An array of NUL-terminated time zone designation strings
    tz_designations = buf.read(header.charcnt)

    @cache
    def get_tz_designations(idx: int) -> str:
        """Find the null terminated string starting at the specified index."""
        end = tz_designations.find(b"\x00", idx)
        return tz_designations[idx:end].decode("UTF-8")

    leap_seconds: list[LeapSecond] = [
        LeapSecond._make(
            struct.unpack(
                f">{version.time_format}l",
                buf.read(version.time_size + 4),  # occur + corr
            )
        )
        for _ in range(header.leapcnt)
    ]

    # Standard/wall indicators determine if the transition times are standard time (1)
    # or wall clock time (0).
    isstdcnt_types: Sequence[bool]
    if header.isstdcnt > 0:
        isstdcnt_types = struct.unpack(
            f">{header.isstdcnt}?",
            buf.read(header.isstdcnt),
        )
    else:
        isstdcnt_types = [False] * header.timecnt

    # UTC/local indicators determine if the transition times are UTC (1) or local time (0).
    isutccnt_types: Sequence[bool]
    if header.isutccnt > 0:
        isutccnt_types = struct.unpack(
            f">{header.isutccnt}?", buf.read(header.isutccnt)
        )
    else:
        isutccnt_types = [False] * header.timecnt

    transitions = [
        new_transition(TransitionBlock(*values), local_time_types, get_tz_designations)
        for values in zip(
            transition_times, transition_types, isstdcnt_types, isutccnt_types
        )
    ]

    return (transitions, leap_seconds)


def read(key: str) -> TimezoneInfo:
    """Read the TZif file from the tzdata package and return timezone records."""
    (package, resource) = iana_key_to_resource(key)
    with resources.files(package).joinpath(resource).open("rb") as tzdata_file:
        return read_tzif(tzdata_file.read())


def read_tzif(content: bytes) -> TimezoneInfo:
    """Read the TZif file and parse and return the timezone records."""
    buf = io.BytesIO(content)

    # V1 header and block
    header = Header.from_bytes(buf.read(Header.SIZE))
    if header.version == TZifVersion.V1.version:
        if header.typecnt == 0:
            raise ValueError("Local time records in block is zero")
        if header.charcnt == 0:
            raise ValueError("Total number of octets is zero")
    (transitions, leap_seconds) = read_datablock(header, TZifVersion.V1, buf)
    if header.version == TZifVersion.V1.version:
        return TimezoneInfo(transitions, leap_seconds)

    # V2+ header and block
    header = Header.from_bytes(buf.read(Header.SIZE))
    if header.typecnt == 0:
        raise ValueError("Local time records in block is zero")
    if header.charcnt == 0:
        raise ValueError("Total number of octets is zero")

    (transitions, leap_seconds) = read_datablock(header, TZifVersion.V2, buf)

    # V2+ footer
    footer = buf.read()
    parts = footer.decode("UTF-8").split("\n")
    if len(parts) != 3:
        raise ValueError("Failed to read TZ footer")
    return TimezoneInfo(transitions, leap_seconds, rule=parts[1])
