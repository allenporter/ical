"""Properties that can appear within various calendar components.

This file contains properties that may appear in multiple components.
"""

from __future__ import annotations

import enum
from typing import Callable, Generator

from .property_values import Integer


class EventStatus(str, enum.Enum):
    """Status or confirmation of the event."""

    CONFIRMED = "CONFIRMED"
    TENTATIVE = "TENTATIVE"
    CANCELLED = "CANCELLED"


class TodoStatus(str, enum.Enum):
    """Status or confirmation of the to-do."""

    NEEDS_ACTION = "NEEDS-ACTION"
    COMPLETED = "COMPLETED"
    IN_PROCESS = "IN-PROCESS"
    CANCELLED = "CANCELLED"


class Priority(Integer):
    """Defines relative priority for a calendar component."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield from super().__get_validators__()
        yield cls.parse_priority

    @classmethod
    def parse_priority(cls, priority: int) -> int:
        """Parse a rfc5545 into a text value."""
        if priority < 0 or priority > 9:
            raise ValueError("Expected priority between 0-9")
        return priority
