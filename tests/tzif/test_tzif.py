"""Tests for the tzif library."""

import pytest

from ical.tzif import tzif

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


def test_header() -> None:
    """Tests for tzif header parsing."""
    header = tzif.Header.from_bytes(V1_HEADER)
    assert header.version == b"\x00"
    assert header.isutccnt == 1
    assert header.isstdcnt == 1
    assert header.leapcnt == 27
    assert header.timecnt == 0
    assert header.typecnt == 1
    assert header.charcnt == 4


def test_tzif() -> None:
    """Tests for tzif parser."""
    result = tzif.read("America/Los_Angeles")
    assert len(result.transitions) > 0
    assert result.rule == "PST8PDT,M3.2.0,M11.1.0"
