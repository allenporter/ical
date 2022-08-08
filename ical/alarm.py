"""Alarm information for calendar components."""

import datetime
from typing import Any, Optional, Union

from pydantic import Field, root_validator

from .parsing.property import ParsedProperty
from .types import CalAddress, ComponentModel

# Common values for an Alarm action
ACTION_AUDIO = "ACTION"
ACTION_DISPLAY = "DISPLAY"
ACTION_EMAIL = "EMAIL"


class Alarm(ComponentModel):
    """An alarm component for a calendar.

    The action (e.g. "AUDIO", "DISPLAY", "EMAIL" or something else) determine
    which properties are also specified.
    """

    action: str
    """Action to be taken when the alarm is triggered."""

    trigger: Union[datetime.timedelta, datetime.datetime]
    """May be either a relative time or absolute time."""

    duration: Optional[datetime.timedelta] = None
    """A duration in time for the alarm.

    If duration is specified then repeat must also be specified.
    """

    repeat: Optional[int] = None
    """The number of times an alarm should be repeated.

    If repeate is specified then duration must also be specified.
    """

    #
    # Properties for DISPLAY and EMAIL actions
    #

    description: Optional[str] = None
    """A description of the notification or email body."""

    #
    # Properties for EMAIL actions
    #

    summary: Optional[str] = None
    """A summary for the email action."""

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    """Email recipients for the alarm."""

    extras: list[ParsedProperty] = Field(default_factory=list)

    # Future properties:
    # - attach

    @root_validator
    def parse_display_required_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate required fields for display actions."""
        if values.get("action") != ACTION_DISPLAY:
            return values
        if not values.get("description"):
            raise ValueError("Description value is required for action AUDIO")
        return values

    @root_validator
    def parse_email_required_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate required fields for email actions."""
        if values.get("action") != ACTION_EMAIL:
            return values
        if not values.get("description"):
            raise ValueError("Description value is required for action AUDIO")
        if not values.get("summary"):
            raise ValueError("Summary value is required for action AUDIO")
        return values

    @root_validator
    def parse_repeat_duration(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Assert the relationship between repeat and duration."""
        if (values.get("duration") is None) != (values.get("repeat") is None):
            raise ValueError(
                "Duration and Repeat must both be specified or both omitted"
            )
        return values
