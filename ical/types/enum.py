"""Utilities for defining and parsing enumerated types."""

from collections.abc import Callable
import enum
from typing import TypeVar, Type

__all__ = ["create_enum_validator"]

T = TypeVar("T", bound=enum.Enum)


def create_enum_validator(enum_type: Type[T]) -> Callable[[str], str | None]:
    """Validate the value against the enum."""

    def validate(value: str) -> str | None:
        if value not in [member.value for member in enum_type]:
            return None
        return value

    return validate
