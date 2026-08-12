"""Alarm information for calendar components."""

import datetime
import enum
from typing import Any, Optional, Self, Union

from pydantic import Field, field_serializer, model_validator

from .component import ComponentModel
from .parsing.component import ParsedComponent
from .parsing.property import ParsedProperty, ParsedPropertyParameter
from .types import Attachment, CalAddress, ExtraProperty
from .types.data_types import serialize_field
from .util import normalize_datetime


__all__ = ["Alarm", "Action", "Related"]

_RELATED = "RELATED"


class Action(str, enum.Enum):
    """Type of actioninvoked when alarm is triggered."""

    AUDIO = "AUDIO"
    """An alarm that causes sound to be played to alert the user.

    The attachment is a sound resource, or a fallback is used.
    """

    DISPLAY = "DISPLAY"
    """An alarm that displays the description text to the user."""

    EMAIL = "EMAIL"
    """An email is composed and delivered to the attendees.

    The description is the body of the message, summary is the subject,
    and attachments are email attachments.
    """


class Related(str, enum.Enum):
    """Whether a relative trigger is measured from the start or the end."""

    START = "START"
    """The trigger offset is relative to DTSTART. This is the default."""

    END = "END"
    """The trigger offset is relative to DTEND."""


class Alarm(ComponentModel):
    """An alarm component for a calendar.

    The action (e.g. AUDIO, DISPLAY, EMAIL) determine which properties
    are also specified.
    """

    action: str
    """Action to be taken when the alarm is triggered."""

    trigger: Union[datetime.timedelta, datetime.datetime]
    """May be either a relative time or absolute time."""

    trigger_related: Related = Related.START
    """Whether a relative `trigger` is measured from the start or the end.

    Read from the `RELATED` parameter on `TRIGGER`, and written back out as
    that parameter rather than as a property of its own. Absolute triggers
    ignore it.
    """

    duration: Optional[datetime.timedelta] = None
    """A duration in time for the alarm.

    If duration is specified then repeat must also be specified.
    """

    repeat: Optional[int] = None
    """The number of times an alarm should be repeated.

    If repeat is specified then duration must also be specified.
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

    attach: list[Attachment] = Field(default_factory=list)
    """Associate a document object with the alarm."""

    extras: list[ExtraProperty] = Field(default_factory=list)

    @model_validator(mode="after")
    def parse_display_required_fields(self) -> Self:
        """Validate required fields for display actions."""
        action = self.action
        if action != Action.DISPLAY:
            return self
        if self.description is None:
            raise ValueError(f"Description value is required for action {action}")
        return self

    @model_validator(mode="after")
    def parse_email_required_fields(self) -> Self:
        """Validate required fields for email actions."""
        action = self.action
        if action != Action.EMAIL:
            return self
        if self.description is None:
            raise ValueError(f"Description value is required for action {action}")
        if self.summary is None:
            raise ValueError(f"Summary value is required for action {action}")
        return self

    @model_validator(mode="after")
    def parse_repeat_duration(self) -> Self:
        """Assert the relationship between repeat and duration."""
        if (self.duration is None) != (self.repeat is None):
            raise ValueError(
                "Duration and Repeat must both be specified or both omitted"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _parse_trigger_related(cls, values: Any) -> Any:
        """Lift the RELATED parameter off TRIGGER into its own field."""
        if not isinstance(values, dict):
            return values
        # Only ics parsing puts ParsedProperty here; a directly constructed
        # Alarm passes the resolved value and has nothing to lift.
        trigger = values.get("trigger")
        if not isinstance(trigger, list):
            return values
        for prop in trigger:
            if not isinstance(prop, ParsedProperty):
                continue
            if related := prop.get_parameter_value(_RELATED):
                values["trigger_related"] = related.upper()
        return values

    @classmethod
    def __encode_component__(
        cls, name: str, model_data: dict[str, Any]
    ) -> "ParsedComponent":
        """Write `trigger_related` back as a TRIGGER parameter.

        Left to the default encoder it would be emitted as a property of its
        own, which is not valid ics.
        """
        component = super().__encode_component__(name, model_data)
        related: str | None = None
        properties = []
        for prop in component.properties:
            if prop.name == "trigger_related":
                related = prop.value
                continue
            properties.append(prop)
        component.properties = properties

        if related and related.upper() != Related.START:
            for prop in component.properties:
                if prop.name != "trigger":
                    continue
                params = prop.params or []
                params.append(
                    ParsedPropertyParameter(name=_RELATED, values=[related.upper()])
                )
                prop.params = params
        return component

    def trigger_times(
        self,
        dtstart: datetime.datetime | datetime.date,
        dtend: datetime.datetime | datetime.date | None = None,
    ) -> list[datetime.datetime]:
        """Resolve this alarm's trigger into absolute datetimes.

        A list is returned because `REPEAT` and `DURATION` together produce
        more than one time. It is sorted chronologically.

        `dtstart` and `dtend` accept dates as well as datetimes, so an all day
        event resolves against midnight in the local timezone.

        Raises:
            ValueError: if the trigger is relative to the end and no end was
                given.
        """
        if isinstance(self.trigger, datetime.datetime):
            # rfc5545 requires an absolute trigger to be UTC, but this library
            # is deliberately lenient about what it will read. A naive value
            # here would be uncomparable against the aware times every other
            # branch produces, so callers sorting a mixed list would hit a
            # TypeError. Aware values pass through untouched.
            first = normalize_datetime(self.trigger)
        else:
            if self.trigger_related == Related.END:
                if dtend is None:
                    raise ValueError(
                        "Alarm trigger is relative to the end, but no end was given"
                    )
                anchor = dtend
            else:
                anchor = dtstart
            first = normalize_datetime(anchor) + self.trigger

        times = [first]
        if self.repeat and self.duration:
            times.extend(first + self.duration * (i + 1) for i in range(self.repeat))
        # A negative DURATION is malformed but readable, and would otherwise
        # contradict the ordering promised above.
        times.sort()
        return times

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]
