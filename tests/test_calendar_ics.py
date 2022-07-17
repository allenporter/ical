"""Tests for timeline related calendar eents."""

import json

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.calendar import IcsStream


@pytest.mark.golden_test("testdata/ics/*.yaml")
def test_golden_files(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = IcsStream.from_content(golden["input"])
    data = json.loads(cal.json(exclude_unset=True))
    assert data == golden["output"]
