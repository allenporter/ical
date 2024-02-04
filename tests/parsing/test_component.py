"""Tests for parsing raw components."""

import json
import pathlib
from typing import Any

import pytest
from syrupy import SnapshotAssertion

from ical.parsing.component import encode_content, parse_content

TESTDATA_PATH = pathlib.Path("tests/parsing/testdata/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.ics"))
TESTDATA_IDS = [ x.stem for x in TESTDATA_FILES ]


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse_contentlines(
    filename: pathlib.Path, snapshot: SnapshotAssertion, json_encoder: json.JSONEncoder
) -> None:
    """Fixture to read golden file and compare to golden output."""
    values = parse_content(filename.read_text())
    values = json.loads(json_encoder.encode(values))
    assert values == snapshot


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_encode_contentlines(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Fixture to read golden file and serialize back to same format."""
    values = parse_content(filename.read_text())
    ics = encode_content(values)
    assert ics == snapshot


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse_contentlines_benchmark(
    filename: pathlib.Path, json_encoder: json.JSONEncoder, benchmark: Any
) -> None:
    """Benchmark to measure the speed of parsing."""

    def parse() -> None:
        values = parse_content(filename.read_text())
        json.loads(json_encoder.encode(values))

    benchmark(parse)
