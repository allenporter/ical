"""Test fixtures."""

from collections.abc import Generator
import dataclasses
import json
from typing import Any
from unittest.mock import patch

import pytest
from pydantic.json import pydantic_encoder


FAKE_VERSION = "1.2.3"


class DataclassEncoder(json.JSONEncoder):
    """Class that can dump data classes as dict for comparison to golden."""

    def default(self, o: Any) -> Any:
        if dataclasses.is_dataclass(o):
            # Omit empty
            return {k: v for (k, v) in dataclasses.asdict(o).items() if v}
        if isinstance(o, dict):
            return {k: v for (k, v) in o.items() if v}
        return pydantic_encoder(o)


@pytest.fixture
def json_encoder() -> json.JSONEncoder:
    """Fixture that creates a json encoder."""
    return DataclassEncoder()


@pytest.fixture(autouse=True)
def mock_version() -> Generator[None, None, None]:
    """Mock out the version used in tests."""
    with patch("ical.calendar.version_factory", return_value=FAKE_VERSION):
        yield
