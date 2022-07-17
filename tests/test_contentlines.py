"""Tests for timeline related calendar eents."""

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.contentlines import parse_content


@pytest.mark.golden_test("testdata/contentlines/*.yaml")
def test_golden_files(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    values = parse_content(golden["input"])
    assert values == golden["output"]
