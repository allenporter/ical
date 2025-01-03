"""Tests for handling rfc5545 properties and parameters.

This reuses the test data made for testing full components, but also exercises
the same lower level components.
"""

from dataclasses import asdict
import pathlib

import pytest
from syrupy import SnapshotAssertion

from ical.parsing.property import (
    ParsedProperty,
    ParsedPropertyParameter,
    parse_basic_ics_properties,
)
from ical.parsing.component import unfolded_lines


TESTDATA_PATH = pathlib.Path("tests/parsing/testdata/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.ics"))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_from_ics(filename: str, snapshot: SnapshotAssertion) -> None:
    """Fixture to read golden file and compare to golden output."""
    properties = list(parse_basic_ics_properties(unfolded_lines(filename.read_text())))
    assert properties == snapshot

@pytest.mark.parametrize(
    "ics",
    [
        "PROP-VALUE",
        "PROP;:VALUE",
        "PROP;PARAM:VALUE",
        ";VALUE",
        ";:VALUE",
    ]
)
def test_invalid_format(ics: str) -> None:
    """Test parsing invalid property format."""
    with pytest.raises(ValueError):
        r = list(parse_basic_ics_properties([ics]))
        assert r == 'a'
