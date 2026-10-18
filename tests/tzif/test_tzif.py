"""Tests for the tzif library."""

import datetime
import struct

import pytest

from ical.tzif import timezoneinfo, tzif

V1_HEADER = b"".join(
    [
        b"\x54\x5a\x69\x66",  # magic
        b"\x00",  # version
        b"\x00\x00\x00\x00",  # pad
        b"\x00\x00\x00\x00",
        b"\x00\x00\x00\x00",
        b"\x00\x00\x00",
        b"\x00\x00\x00\x01"  # isutccnt
        b"\x00\x00\x00\x01"  # isstdcnt
        b"\x00\x00\x00\x1b"  # isleapcnt
        b"\x00\x00\x00\x00"  # timecnt
        b"\x00\x00\x00\x01"  # typecnt
        b"\x00\x00\x00\x04",  # charcnt
    ]
)


@pytest.mark.parametrize(
    "header,match",
    [
        (
            b"\x00" + V1_HEADER[1:],
            "did not contain magic",
        ),
        (
            V1_HEADER[0:23] + b"\x07" + V1_HEADER[24:],
            "UTC/local indicators in datablock mismatched",
        ),
        (
            V1_HEADER[0:27] + b"\x07" + V1_HEADER[28:],
            "standard/wall indicators in datablock mismatched",
        ),
        (
            V1_HEADER[0:23]
            + b"\x00"
            + V1_HEADER[24:27]
            + b"\x00"
            + V1_HEADER[28:39]
            + b"\x00"
            + V1_HEADER[40:],
            "Local time records in block is zero",
        ),
        (
            V1_HEADER[0:43] + b"\x00",
            "octets is zero",
        ),
    ],
)
def test_invalid_header(header: bytes, match: str) -> None:
    """Tests a TZif header with an invalid typecnt."""
    assert len(header) == len(V1_HEADER)
    with pytest.raises(ValueError, match=match):
        tzif.read_tzif(header)


def test_tzif() -> None:
    """Tests for tzif parser."""
    result = timezoneinfo.read("America/Los_Angeles")
    assert len(result.transitions) > 0
    assert result.rule
    assert result.rule.std
    assert result.rule.std.name == "PST"
    assert result.rule.std.offset == datetime.timedelta(hours=-8)
    assert result.rule.dst
    assert result.rule.dst.name == "PDT"
    assert result.rule.dst.offset == datetime.timedelta(hours=-7)


def test_isstdcnt_isutccnt_indexed_by_transition_type() -> None:
    """Verify isstdcnt and isutccnt are indexed by local time type (0..typecnt-1)."""
    # V1 TZif with timecnt=3, typecnt=2, isstdcnt=2, isutccnt=2, charcnt=8
    header = struct.pack(
        ">4sc15x6l",
        b"TZif",
        b"\x00",
        2,  # isutccnt
        2,  # isstdcnt
        0,  # leapcnt
        3,  # timecnt
        2,  # typecnt
        8,  # charcnt
    )
    transition_times = struct.pack(">3l", 100, 200, 300)
    # Transition types: [1, 0, 1]
    transition_types = struct.pack(">3B", 1, 0, 1)
    # Local time types: type 0 ("STD\0"), type 1 ("DST\0")
    local_time_types = struct.pack(">l?B", -18000, False, 0) + struct.pack(
        ">l?B", -14400, True, 4
    )
    designations = b"STD\x00DST\x00"
    # Type 0 has isstd=True, isutc=True; Type 1 has isstd=False, isutc=False
    isstd = struct.pack(">2?", True, False)
    isutc = struct.pack(">2?", True, False)

    info = tzif.read_tzif(
        header
        + transition_times
        + transition_types
        + local_time_types
        + designations
        + isstd
        + isutc
    )
    assert len(info.transitions) == 3
    # Transition 0 uses type 1 -> False, False
    assert info.transitions[0].isstdcnt is False
    assert info.transitions[0].isutccnt is False
    # Transition 1 uses type 0 -> True, True
    assert info.transitions[1].isstdcnt is True
    assert info.transitions[1].isutccnt is True
    # Transition 2 uses type 1 -> False, False
    assert info.transitions[2].isstdcnt is False
    assert info.transitions[2].isutccnt is False
