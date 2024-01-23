"""Test fixtures."""

from collections.abc import Generator
import dataclasses
import json
from typing import Any
from unittest.mock import patch

import pytest

try:
    from pydantic.v1.json import pydantic_encoder
except ImportError:
    from pydantic.json import pydantic_encoder  # type: ignore[no-redef]


PRODID = "-//example//1.2.3"


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


@pytest.fixture
def mock_prodid() -> Generator[None, None, None]:
    """Mock out the prodid used in tests."""
    with patch("ical.calendar.prodid_factory", return_value=PRODID):
        yield
