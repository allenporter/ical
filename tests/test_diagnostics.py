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
    ics = pathlib.Path(filename).read_text()
    assert "\n".join(list(redact_ics(ics))) == snapshot
