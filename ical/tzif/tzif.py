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

rfc8536
"""

# pylint: disable=too-many-locals

import io
import struct
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Optional, Sequence

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
        return set(zones_file.readlines())


def iana_key_to_resource(key: str) -> tuple[str, str]:
    """Returns the package and resource file for the specified timezone."""
    package_loc, resource = key.rsplit("/", 1)
    package = "tzdata.zoneinfo." + package_loc.replace("/", ".")
    return package, resource


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
    V1 = b"\x00"
    V2 = b"2"
    V3 = b"3"

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


@dataclass
class Transition:
    """An individual item in the Datablock."""

    transition_time: int
    """A transition time at which the rules for computing local time may change."""

    utoff: int
    """Number of seconds added to UTC to determine local time."""

    dst: bool
    """Determines if local time is Daylight Savings Time (else Standard time)."""

    isstdcnt: bool
    """Determines if the transition time is standard time (else, wall clock time)."""

    isutccnt: bool
    """Determines if the transition time is UCT time, else is a local time."""

    designation: str
    """A designation string."""


@dataclass
class LeapSecond:
    """A correction that needs to be applied to UTC in order to determine TAI."""

    occurrence: int
    """The time at which the leap-second correction occurs."""

    correction: int
    """The value of LEAPCORR on or after the occurrence (1 or -1)."""


@dataclass
class Result:
    """The results of parsing the TZif file."""

    transitions: list[Transition]
    """Local time changes."""

    leap_seconds: list[LeapSecond]

    rule: Optional[str] = None
    """A rule for computing local time changes after the last transition."""


@dataclass
class DatablockReader:
    """A series of items made up of variable length elements."""

    def __init__(self, header: Header, time_size: int, time_size_format: str) -> None:
        """Initialize Datablock."""
        self._header = header
        self._time_size = time_size
        self._time_size_format = time_size_format

    @classmethod
    def for_header(cls, header: Header, version: bytes) -> "DatablockReader":
        """Create a new DatablockReader for the specified header and version."""
        if version == Header.V1:
            return cls(header, 4, "l")  # 32-bit in v1
        return cls(header, 8, "q")  # 64-bit in v2+

    def read(self, buf: io.BytesIO) -> tuple[list[Transition], list[LeapSecond]]:
        """Read records from the buffer."""
        # A series of leap-time values in sorted order
        transition_times = struct.unpack(
            f">{self._header.timecnt}{self._time_size_format}",
            buf.read(self._header.timecnt * self._time_size),
        )

        # A series of integers specifying the type of local time of the corresponding
        # transition time. These are zero-based indices into the array of local
        # time type records. (from 0 to typecnt-1)
        transition_types: Sequence[int] = []
        if self._header.timecnt > 0:
            transition_types = struct.unpack(
                f">{self._header.timecnt}B", buf.read(self._header.timecnt)
            )

        # A series of records specifying the local time type:
        #  - utoff (4 bytes): Number of seconds to add to UTC to determine local time
        #  - dst (1 byte): Indicates the time is DST (1) or standard (0)
        #  - idx (1 byte):  Offset index into the time zone designiation octets (0-charcnt-1)
        # is the utoff (4 bytes), dst (1 byte), idx (1 byte).
        local_time_types: list[tuple[Any, ...]] = []
        for _ in range(self._header.typecnt):
            local_time_types.append(
                struct.unpack(
                    LOCAL_TIME_TYPE_STRUCT_FORMAT, buf.read(LOCAL_TIME_RECORD_SIZE)
                )
            )

        # An array of NUL-terminated time zone designation strings
        tz_designations = buf.read(self._header.charcnt)

        @cache
        def get_tz_designations(idx: int) -> str:
            """Find the null terminated string starting at the specified index."""
            end = tz_designations.find(b"\x00", idx)
            return tz_designations[idx:end].decode("UTF-8")

        leap_seconds: list[LeapSecond] = []
        for _ in range(self._header.leapcnt):
            leap_second_record = struct.unpack(
                f">{self._time_size_format}l",
                buf.read(self._time_size + 4),  # occur + corr
            )
            leap_seconds.append(
                LeapSecond(leap_second_record[0], leap_second_record[1])
            )

        # Standard/wall indicators determine if the transition times are standard time (1)
        # or wall clock time (0).
        isstdcnt_types: Sequence[bool]
        if self._header.isstdcnt > 0:
            isstdcnt_types = struct.unpack(
                f">{self._header.isstdcnt}?",
                buf.read(self._header.isstdcnt),
            )
        else:
            isstdcnt_types = [False] * self._header.timecnt

        # UTC/local indicators determine if the transition times are UTC (1) or local time (0).
        isutccnt_types: Sequence[bool]
        if self._header.isutccnt > 0:
            isutccnt_types = struct.unpack(
                f">{self._header.isutccnt}?", buf.read(self._header.isutccnt)
            )
        else:
            isutccnt_types = [False] * self._header.timecnt

        transitions = []
        for (transition_time, transition_type, isstdcnt, isutccnt) in zip(
            transition_times,
            transition_types,
            isstdcnt_types,
            isutccnt_types,
        ):
            if transition_type >= len(local_time_types):
                raise ValueError(
                    f"transition_type out of bounds {transition_type} >= {len(local_time_types)}"
                )
            if isutccnt and not isstdcnt:
                raise ValueError("isutccnt was True but isstdcnt was False")
            (utoff, dst, idx) = local_time_types[transition_type]
            transitions.append(
                Transition(
                    transition_time,
                    utoff,
                    dst,
                    isstdcnt,
                    isutccnt,
                    get_tz_designations(idx),
                )
            )
        return (transitions, leap_seconds)


def read(key: str) -> Result:
    """Read the TZif file from the tzdata package and return timezone records."""
    (package, resource) = iana_key_to_resource(key)
    with resources.files(package).joinpath(resource).open("rb") as tzdata_file:
        return read_tzif(tzdata_file.read())


def read_tzif(content: bytes) -> Result:
    """Read the TZif file and parse and return the timezone records."""
    buf = io.BytesIO(content)

    # V1 header and block
    header = Header.from_bytes(buf.read(Header.SIZE))
    if header.version == Header.V1:
        if header.typecnt == 0:
            raise ValueError("Local time records in block is zero")
        if header.charcnt == 0:
            raise ValueError("Total number of octets is zero")
    reader = DatablockReader.for_header(header, Header.V1)
    (transitions, leap_seconds) = reader.read(buf)
    if header.version == Header.V1:
        return Result(transitions, leap_seconds)

    # V2+ header and block
    header = Header.from_bytes(buf.read(Header.SIZE))
    if header.typecnt == 0:
        raise ValueError("Local time records in block is zero")
    if header.charcnt == 0:
        raise ValueError("Total number of octets is zero")

    reader = DatablockReader.for_header(header, Header.V2)
    (transitions, leap_seconds) = reader.read(buf)

    # V2+ footer
    footer = buf.read()
    parts = footer.decode("UTF-8").split("\n")
    if len(parts) != 3:
        raise ValueError("Failed to read TZ footer")
    return Result(transitions, leap_seconds, rule=parts[1])
