"""Tests for rfc8536 examples."""

import io
import json
import pathlib
import re

import pytest
from syrupy import SnapshotAssertion

from ical.tzif.tzif import read_tzif

RFC_LINE = re.compile(r"\|(?:[0-9]|\s)+\| (.*?)\s+\| .+ \| .+ \|")

TESTDATA_PATH = pathlib.Path("tests/tzif/testdata/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.txt"))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]


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


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse(
    filename: pathlib.Path, snapshot: SnapshotAssertion, json_encoder: json.JSONEncoder
) -> None:
    """Test that reads RFC examples from golden files."""
    content = rfc_to_binary(filename.read_text())
    print(content)
    result = read_tzif(content)
    obj_data = json.loads(json.dumps(result, default=json_encoder.default))
    assert obj_data == snapshot
