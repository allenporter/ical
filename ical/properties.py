"""Properties that can appear within various calendar components.

This file contains properties that may appear in multiple components.
"""

from __future__ import annotations

import enum


class EventStatus(str, enum.Enum):
    """Status or confirmation of the event."""

    CONFIRMED = "CONFIRMED"
    TENTATIVE = "TENTATIVE"
    CANCELLED = "CANCELLED"
