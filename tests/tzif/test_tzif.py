"""Tests for the tzif library."""

from ical.tzif import tzif

V1_HEADER = [
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


def test_header() -> None:
    """Tests for tzif header parsing."""
    header = tzif.Header.from_bytes(b"".join(V1_HEADER))
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
