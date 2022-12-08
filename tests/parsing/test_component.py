"""Tests for parsing raw components."""

import json
from typing import Any

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.parsing.component import encode_content, parse_content


@pytest.mark.golden_test("testdata/*.yaml")
def test_parse_contentlines(
    golden: GoldenTestFixture, json_encoder: json.JSONEncoder
) -> None:
    """Fixture to read golden file and compare to golden output."""
    values = parse_content(golden["input"])
    values = json.loads(json_encoder.encode(values))
    assert values == golden["output"]


@pytest.mark.golden_test("testdata/*.yaml")
def test_encode_contentlines(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and serialize back to same format."""
    values = parse_content(golden["input"])
    ics = encode_content(values)
    assert ics == golden.get("encoded", golden["input"])


@pytest.mark.golden_test("testdata/*.yaml")
def test_parse_contentlines_benchmark(
    golden: GoldenTestFixture, json_encoder: json.JSONEncoder, benchmark: Any
) -> None:
    """Benchmark to measure the speed of parsing."""

    def parse() -> None:
        values = parse_content(golden["input"])
        values = json.loads(json_encoder.encode(values))
        assert values == golden["output"]

    benchmark(parse)
