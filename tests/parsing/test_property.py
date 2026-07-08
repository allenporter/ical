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
def test_from_ics(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Fixture to read golden file and compare to golden output."""
    properties = list(parse_contentlines(unfolded_lines(filename.read_text("utf-8"))))
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
    assert prop.params is not None
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


def test_parameter_quoting_parsing() -> None:
    """Test parsing and serialization of single quoted and unquoted parameter values."""
    properties = list(parse_contentlines(['PROP;PARAM1=value1;PARAM2="value2":VAL']))
    assert len(properties) == 1
    prop = properties[0]
    assert prop.name == "prop"
    assert prop.value == "VAL"
    assert prop.params == [
        ParsedPropertyParameter(name="PARAM1", values=["value1"]),
        ParsedPropertyParameter(name="PARAM2", values=["value2"]),
    ]
    # Check serialization of safe values (no quotes generated)
    assert prop.ics() == "PROP;PARAM1=value1;PARAM2=value2:VAL"


def test_parameter_quoting_multiple_values() -> None:
    """Test parsing and serialization of multiple parameter values (comma-separated)."""
    properties = list(parse_contentlines(['PROP;PARAM=value1,"value2",value3:VAL']))
    assert len(properties) == 1
    assert properties[0].params == [
        ParsedPropertyParameter(name="PARAM", values=["value1", "value2", "value3"])
    ]
    assert properties[0].ics() == "PROP;PARAM=value1,value2,value3:VAL"


def test_parameter_quoting_unsafe_characters() -> None:
    """Test that parameter values containing unsafe characters are quoted on serialization."""
    properties = list(
        parse_contentlines(
            ['PROP;PARAM1="val,one";PARAM2="val:two";PARAM3="val;three":VAL']
        )
    )
    assert len(properties) == 1
    assert properties[0].params == [
        ParsedPropertyParameter(name="PARAM1", values=["val,one"]),
        ParsedPropertyParameter(name="PARAM2", values=["val:two"]),
        ParsedPropertyParameter(name="PARAM3", values=["val;three"]),
    ]
    # Check serialization preserves quoting for unsafe characters
    assert (
        properties[0].ics()
        == 'PROP;PARAM1="val,one";PARAM2="val:two";PARAM3="val;three":VAL'
    )


@pytest.mark.parametrize(
    "ics",
    [
        'PROP;PARAM="unclosed:VAL',
        'PROP;PARAM="val"quote:VAL',
    ],
)
def test_parameter_quoting_parse_errors(ics: str) -> None:
    """Test error handling during parsing of invalid quoted parameters."""
    with pytest.raises(CalendarParseError):
        list(parse_contentlines([ics]))


def test_rfc6868_ical_parameter_decoding() -> None:
    """Test RFC 6868 Section 3.1 iCalendar parameter decoding."""
    prop = ParsedProperty.from_ics(
        "ATTENDEE;CN=George Herman ^'Babe^' Ruth:mailto:babe@example.com"
    )
    assert prop.name == "attendee"
    assert prop.value == "mailto:babe@example.com"
    assert prop.get_parameter_value("CN") == 'George Herman "Babe" Ruth'


def test_rfc6868_vcard_parameter_decoding() -> None:
    """Test RFC 6868 Section 3.2 vCard parameter decoding."""
    prop = ParsedProperty.from_ics(
        'GEO;X-ADDRESS="Pittsburgh Pirates^n115 Federal St^nPittsburgh, PA 15212":geo:40.446816,-80.00566'
    )
    assert prop.name == "geo"
    assert prop.value == "geo:40.446816,-80.00566"
    assert (
        prop.get_parameter_value("X-ADDRESS")
        == "Pittsburgh Pirates\n115 Federal St\nPittsburgh, PA 15212"
    )


@pytest.mark.parametrize(
    ("ics_line", "expected_value"),
    [
        ("X-TEST;KEY=^^:VALUE", "^"),
        ("X-TEST-2;KEY=^^n:VALUE", "^n"),
        ("X-TEST-3;KEY=a^:VALUE", "a^"),
    ],
)
def test_rfc6868_caret_parameter_decoding(ics_line: str, expected_value: str) -> None:
    """Test RFC 6868 circumflex escaping edge cases during decoding."""
    prop = ParsedProperty.from_ics(ics_line)
    assert prop.get_parameter_value("KEY") == expected_value


def test_rfc6868_ical_parameter_encoding() -> None:
    """Test RFC 6868 Section 3.1 iCalendar parameter encoding."""
    prop = ParsedProperty(
        name="ATTENDEE",
        value="mailto:babe@example.com",
        params=[
            ParsedPropertyParameter(name="CN", values=['George Herman "Babe" Ruth'])
        ],
    )
    assert (
        prop.ics() == "ATTENDEE;CN=George Herman ^'Babe^' Ruth:mailto:babe@example.com"
    )


def test_rfc6868_vcard_parameter_encoding() -> None:
    """Test RFC 6868 Section 3.2 vCard parameter encoding."""
    prop = ParsedProperty(
        name="GEO",
        value="geo:40.446816,-80.00566",
        params=[
            ParsedPropertyParameter(
                name="X-ADDRESS",
                values=["Pittsburgh Pirates\n115 Federal St\nPittsburgh, PA 15212"],
            )
        ],
    )
    assert (
        prop.ics()
        == 'GEO;X-ADDRESS="Pittsburgh Pirates^n115 Federal St^nPittsburgh, PA 15212":geo:40.446816,-80.00566'
    )


@pytest.mark.parametrize(
    ("input_value", "expected_ics"),
    [
        ("^", "X-TEST;KEY=^^:VALUE"),
        ("^n", "X-TEST-2;KEY=^^n:VALUE"),
        ("a^", "X-TEST-3;KEY=a^^:VALUE"),
    ],
)
def test_rfc6868_caret_parameter_encoding(input_value: str, expected_ics: str) -> None:
    """Test RFC 6868 circumflex escaping edge cases during encoding."""
    prop_name = expected_ics.split(";")[0]
    prop = ParsedProperty(
        name=prop_name,
        value="VALUE",
        params=[ParsedPropertyParameter(name="KEY", values=[input_value])],
    )
    assert prop.ics() == expected_ics
