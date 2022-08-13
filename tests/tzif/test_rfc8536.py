"""Tests for rfc8536 examples."""

import dataclasses
import io
import re

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.tzif.tzif import read_tzif

RFC_LINE = re.compile(r"\|(?:[0-9]|\s)+\| (.*?)\s+\| .+ \| .+ \|")


def rfc_to_binary(rfc_text: str) -> bytes:
    """Convert the RFC example text to a binary blob."""
    buf = io.BytesIO()
    for line in rfc_text.split("\n"):
        match = RFC_LINE.match(line)
        if not match:
            continue
        if not (payload := match.group(1)):
            continue
        buf.write(bytearray.fromhex(payload.replace(" ", "")))
    return buf.getvalue()


@pytest.mark.golden_test("testdata/rfc*.yaml")
def test_parse(golden: GoldenTestFixture) -> None:
    """Test that reads RFC examples from golden files."""
    if golden.get("disabled"):
        return

    content = rfc_to_binary(golden["input"])
    result = read_tzif(content)
    assert dataclasses.asdict(result) == golden.out["output"]
