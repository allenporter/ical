"""Test fixtures."""

import dataclasses
import json
from typing import Any

import pytest
from pydantic.json import pydantic_encoder


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
