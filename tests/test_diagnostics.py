"""Tests for diagnostics."""

import pathlib
import pytest

from ical.diagnostics import redact_ics
from syrupy import SnapshotAssertion


def test_empty() -> None:
    """Test redaction of an empty ics file."""
    assert list(redact_ics("")) == []
    assert list(redact_ics("\n")) == []


@pytest.mark.parametrize(
    ("filename"),
    [
        ("tests/testdata/datetime_timezone.ics"),
        ("tests/testdata/description_altrep.ics"),
    ],
    ids=("datetime_timezone", "description_altrep"),
)
def test_redact_date_timezone(filename: str, snapshot: SnapshotAssertion) -> None:
    """Test redaction of an empty ics file."""
    ics = pathlib.Path(filename).read_text(encoding="utf-8")
    assert "\n".join(list(redact_ics(ics))) == snapshot


def test_redact_folded_continuation_with_colon_or_semicolon() -> None:
    """Test that folded continuation lines containing ':' or ';' do not leak sensitive text."""
    ics = (
        "BEGIN:VEVENT\n"
        "DESCRIPTION:Secret meeting\n"
        "  https://secret.example.com:8443/path;token=abc\n"
        "END:VEVENT"
    )
    redacted = list(redact_ics(ics))
    assert redacted == [
        "BEGIN:VEVENT",
        "DESCRIPTION:***",
        "***",
        "END:VEVENT",
    ]


def test_redact_empty_allowlist() -> None:
    """Test that passing an explicit empty allowlist redacts all lines."""
    ics = "BEGIN:VCALENDAR\nPRODID:test\nEND:VCALENDAR"
    assert list(redact_ics(ics, component_allowlist=set())) == [
        "BEGIN:***",
        "PRODID:***",
        "END:***",
    ]
