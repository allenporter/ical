"""Tests for handling rfc5545 properties and parameters.

This reuses the test data made for testing full components, but also exercises
the same lower level components.
"""

from dataclasses import asdict
import pathlib

import pytest
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarParseError
from ical.parsing.property import (
    ParsedProperty,
    ParsedPropertyParameter,
    parse_contentlines,
)
from ical.parsing.component import unfolded_lines


TESTDATA_PATH = pathlib.Path("tests/parsing/testdata/valid/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.ics"))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_from_ics(filename: str, snapshot: SnapshotAssertion) -> None:
    """Fixture to read golden file and compare to golden output."""
    properties = list(parse_contentlines(unfolded_lines(filename.read_text())))
    assert properties == snapshot


@pytest.mark.parametrize(
    "ics",
    [
        "PROP-VALUE",
        "PROP;:VALUE",
        "PROP;PARAM:VALUE",
        ";VALUE",
        ";:VALUE",
    ],
)
def test_invalid_format(ics: str) -> None:
    """Test parsing invalid property format."""
    with pytest.raises(CalendarParseError):
        list(parse_contentlines([ics]))


@pytest.mark.parametrize(
    "ics",
    [
        "X-TEST-BLANK;VALUE=URI;X-TEST-BLANK-PARAM=:VALUE",
        "X-TEST-BLANK;VALUE=URI;X-TEST-BLANK-PARAM=:VALUE",
        "X-TEST-BLANK;VALUE=URI;X-TEST-BLANK-PARAM=:VALUE",
        "X-TEST-BLANK;VALUE=URI;X-TEST-BLANK-PARAM=:VALUE",
    ],
)
def test_blank_parameters(ics: str) -> None:
    """Test parsing invalid property format."""
    properties = list(parse_contentlines([ics]))
    assert len(properties) == 1
    prop = properties[0]
    assert prop.name == "x-test-blank"
    assert prop.value == "VALUE"
    assert len(prop.params) == 2
    assert prop.params[0].name == "VALUE"
    assert prop.params[0].values == ["URI"]
    assert prop.params[1].name == "X-TEST-BLANK-PARAM"
    assert prop.params[1].values == [""]


@pytest.mark.parametrize(
    "ics",
    [
        "BEGIN:VEVENT",
        "begin:VEVENT",
        "Begin:VEVENT",
        "bEgiN:VEVENT",
    ],
)
def test_mixed_case_property_name(ics: str) -> None:
    """Test property name is case-insensitive."""
    properties = list(parse_contentlines([ics]))
    assert len(properties) == 1
    prop = properties[0]
    assert prop.name == "begin"
    assert prop.value == "VEVENT"
    assert prop.params is None
