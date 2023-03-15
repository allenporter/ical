"""Tests for diagnostics."""

import yaml
import pytest

from ical.diagnostics import redact_ics


DATETIME_TIMEZONE = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:***
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:***
DTSTART;TZID=America/New_York:19970714T133000
DTEND;TZID=America/New_York:19970714T140000
SUMMARY:***
END:VEVENT
END:VCALENDAR"""

DESCRIPTION_ALTREP = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:***
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:***
DTSTART:19970714T170000Z
DTEND:19970715T040000Z
SUMMARY:***
DESCRIPTION:***
***
END:VEVENT
END:VCALENDAR"""


def test_empty() -> None:
    """Test redaction of an empty ics file."""
    assert list(redact_ics("")) == []
    assert list(redact_ics("\n")) == []


@pytest.mark.parametrize(
    ("filename", "output"),
    [
        ("tests/testdata/datetime_timezone.yaml", DATETIME_TIMEZONE),
        ("tests/testdata/description_altrep.yaml", DESCRIPTION_ALTREP),
    ],
    ids=("datetime_timezone", "description_altrep"),
)
def test_redact_date_timezone(filename: str, output: str) -> None:
    """Test redaction of an empty ics file."""

    with open(filename) as f:
        doc = yaml.load(f, Loader=yaml.CLoader)
    ics = doc["input"]
    assert "\n".join(list(redact_ics(ics))) == output
