"""Test fixtures."""

import dataclasses
import datetime
import json
from typing import Any

import pytest


class DataclassEncoder(json.JSONEncoder):
    """Class that can dump data classes as dict for comparison to golden."""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime.datetime):
            return str(o)
        if dataclasses.is_dataclass(o):
            # Omit empty
            return {k: v for (k, v) in dataclasses.asdict(o).items() if v}
        if isinstance(o, dict):
            return {k: v for (k, v) in o.items() if v}
        return super().default(o)


@pytest.fixture
def json_encoder() -> json.JSONEncoder:
    """Fixture that creates a json encoder."""
    return DataclassEncoder()
