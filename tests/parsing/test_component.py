"""Tests for parsing raw components."""

import json
import pathlib
from typing import Any

import pytest
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarParseError
from ical.parsing.component import encode_content, parse_content

TESTDATA_PATH = pathlib.Path("tests/parsing/testdata/valid/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.ics"))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]

INVALID_TESTDATA_PATH = pathlib.Path("tests/parsing/testdata/invalid/")
INVALID_TESTDATA_FILES = list(INVALID_TESTDATA_PATH.glob("*.ics"))
INVALID_TESTDATA_IDS = [x.stem for x in INVALID_TESTDATA_FILES]


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse_contentlines(
    filename: pathlib.Path, snapshot: SnapshotAssertion, json_encoder: json.JSONEncoder
) -> None:
    """Fixture to read golden file and compare to golden output."""
    values = parse_content(filename.read_text(encoding="utf-8"))
    values = json.loads(json_encoder.encode(values))
    assert values == snapshot


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_encode_contentlines(
    filename: pathlib.Path, snapshot: SnapshotAssertion
) -> None:
    """Fixture to read golden file and serialize back to same format."""
    values = parse_content(filename.read_text(encoding="utf-8"))
    ics = encode_content(values)
    assert ics == snapshot


@pytest.mark.parametrize("filename", INVALID_TESTDATA_FILES, ids=INVALID_TESTDATA_IDS)
def test_invalid_contentlines(
    filename: pathlib.Path, snapshot: SnapshotAssertion, json_encoder: json.JSONEncoder
) -> None:
    """Fixture to read file inputs that should fail parsing."""
    with pytest.raises(CalendarParseError) as exc_info:
        parse_content(filename.read_text(encoding="utf-8"))
    assert (str(exc_info.value), exc_info.value.detailed_error) == snapshot


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse_contentlines_benchmark(
    filename: pathlib.Path, json_encoder: json.JSONEncoder, benchmark: Any
) -> None:
    """Benchmark to measure the speed of parsing."""

    def parse() -> None:
        values = parse_content(filename.read_text(encoding="utf-8"))
        json.loads(json_encoder.encode(values))

    benchmark(parse)


def _build_large_ics(num_events: int = 500) -> str:
    """Build a multi-event ICS string with parameters and folded lines."""
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//example//1.2.3",
        "VERSION:2.0",
    ]
    for i in range(num_events):
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:event-{i}@example.com",
                f"SUMMARY:Event {i} with a short summary",
                "DTSTART;TZID=America/New_York:20250101T090000",
                "DTEND;TZID=America/New_York:20250101T100000",
                "ATTENDEE;CN=Jane Doe;PARTSTAT=ACCEPTED;RSVP=TRUE:mailto:jane@example.com",
                f"DESCRIPTION:Event {i} has a longer description that exceeds the seventy-five character folding limit in RFC 5545.",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\n".join(lines)


def test_parse_large_component_benchmark(benchmark: Any) -> None:
    """Benchmark parsing a 500-event ICS payload into ParsedComponents."""
    ics = _build_large_ics(500)
    components = benchmark(parse_content, ics)
    assert len(components[0].components) == 500


def test_encode_large_component_benchmark(benchmark: Any) -> None:
    """Benchmark encoding a 500-event ParsedComponent tree back to ICS."""
    ics = _build_large_ics(500)
    components = parse_content(ics)
    encoded = benchmark(encode_content, components)
    assert encoded.startswith("BEGIN:VCALENDAR\n")


def test_unfold_preserves_leading_pipe() -> None:
    """Test that a newline followed by '|' is not treated as a fold."""
    ics = "BEGIN:VEVENT\nSUMMARY:Line1\n|Line2\nEND:VEVENT"
    with pytest.raises(CalendarParseError):
        parse_content(ics)


@pytest.mark.parametrize(
    "invalid_ics",
    [
        "END:STREAM",
        "END:VCALENDAR",
        "BEGIN:VCALENDAR\nEND:VEVENT",
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nEND:VEVENT",
    ],
)
def test_unbalanced_components_raise_parse_error(invalid_ics: str) -> None:
    """Test that unmatched END or unclosed BEGIN raises CalendarParseError."""
    with pytest.raises(CalendarParseError):
        parse_content(invalid_ics)
