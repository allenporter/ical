"""Tests for timeline related calendar eents."""

import dataclasses
import json
from typing import Any

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.contentlines import parse_content


class DataclassEncoder(json.JSONEncoder):
    """Class that can dump data classes as dict for comparison to golden."""

    def default(self, o: Any) -> Any:
        if not dataclasses.is_dataclass(o):
            return o
        # Omit empty
        return {k: v for (k, v) in dataclasses.asdict(o).items() if v}


@pytest.mark.golden_test("testdata/contentlines/*.yaml")
def test_golden_files(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    values = parse_content(golden["input"])
    values = json.loads(DataclassEncoder().encode(values))
    assert values == golden["output"]
