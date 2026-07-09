"""The Calendar component."""

from __future__ import annotations

import datetime
import itertools
import logging
from typing import Optional, Any
import zoneinfo

from pydantic import Field, field_serializer, model_validator

from ical.types.data_types import serialize_field

from .component import ComponentModel
from .event import Event
from .freebusy import FreeBusy
from .journal import Journal
from .types.date_time import TZID, DATETIME_REGEX
from .types import ExtraProperty, Uri, Image
from .parsing.property import ParsedProperty, ParsedPropertyParameter
from .timeline import Timeline, calendar_timeline
from .timezone import Timezone, TimezoneModel, IcsTimezoneInfo
from .todo import Todo
from .util import local_timezone, prodid_factory
from .tzif import timezoneinfo
from .compat import timezone_compat


_LOGGER = logging.getLogger(__name__)

_VERSION = "2.0"

# Components that may contain TZID objects
_TZID_COMPONENTS = ["vevent", "vtodo", "vjournal", "vfreebusy"]

__all__ = ["Calendar"]


class Calendar(ComponentModel):
    """A sequence of calendar properties and calendar components.

    Example usage::

        from datetime import date
        from ical.calendar import Calendar
        from ical.event import Event

        calendar = Calendar()
        calendar.events.append(
            Event(summary="Meeting", start=date(2024, 1, 15), end=date(2024, 1, 16))
        )
        for event in calendar.timeline:
            print(event.summary)
    """

    calscale: Optional[str] = None
    method: Optional[str] = None
    prodid: str = Field(default_factory=lambda: prodid_factory())
    version: str = Field(default_factory=lambda: _VERSION)
    x_wr_timezone: Optional[str] = Field(alias="x-wr-timezone", default=None)
    """Specifies the default timezone for the calendar."""

    # RFC 7986 Section 4 calendar properties
    name: list[str] = Field(default_factory=list)
    """Specifies the user-friendly name of the calendar. Can be specified multiple times in different languages."""

    description: list[str] = Field(default_factory=list)
    """Specifies the description of the calendar. Can be specified multiple times in different languages."""

    uid: Optional[str] = None
    """A globally unique identifier for the calendar component."""

    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    """Specifies the date and time that the calendar metadata was last updated."""

    url: Optional[Uri] = None
    """Specifies a URL where the calendar can be retrieved or viewed."""

    categories: list[str] = Field(default_factory=list)
    """Specifies category keywords/labels associated with the calendar."""

    refresh_interval: Optional[datetime.timedelta] = Field(
        alias="refresh-interval", default=None
    )
    """Specifies a suggested minimum time interval for a client to wait before pulling updates from the calendar source (e.g. PT1H)."""

    source: Optional[Uri] = None
    """Specifies a URL pointing to the original source of the calendar, used for automatically pulling updates."""

    color: Optional[str] = None
    """Specifies a default color to be associated with the calendar and all of its components.

    The value MUST be a case-insensitive color name defined in CSS3-Color (e.g., "blue" or "turquoise")
    or a CSS3 RGB/RGBA color value in hex or functional notation (e.g., "#0000FF").
    """

    image: list[Image] = Field(default_factory=list)
    """Specifies one or more images (e.g. logo or badge) to represent the calendar. Can be links or inline binary data."""

    #
    # Calendar components
    #

    events: list[Event] = Field(alias="vevent", default_factory=list)
    """Events associated with this calendar."""

    todos: list[Todo] = Field(alias="vtodo", default_factory=list)
    """Todos associated with this calendar."""

    journal: list[Journal] = Field(alias="vjournal", default_factory=list)
    """Journals associated with this calendar."""

    freebusy: list[FreeBusy] = Field(alias="vfreebusy", default_factory=list)
    """Free/busy objects associated with this calendar."""

    timezones: list[Timezone] = Field(alias="vtimezone", default_factory=list)
    """Timezones associated with this calendar."""

    # Unknown or unsupported properties
    extras: list[ExtraProperty] = Field(default_factory=list)

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar.

        All day events are returned as if the attendee is viewing from the
        local system timezone. Use :meth:`timeline_tz` to specify a different
        timezone.
        """
        return self.timeline_tz()

    def timeline_tz(self, tzinfo: datetime.tzinfo | None = None) -> Timeline:
        """Return a timeline view of events on the calendar.

        All events are returned as if the attendee is viewing from the
        specified timezone. For example, this affects the order that All Day
        events are returned.
        """
        return calendar_timeline(self.events, tzinfo=tzinfo or local_timezone())

    @model_validator(mode="before")
    @classmethod
    def _propagate_timezones(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Propagate timezone information down to date-time objects.

        This results in parsing the timezones twice: Once here, then once again
        in the calendar itself. This does imply that if a vtimezone object is
        changed live, the DATE-TIME objects are not updated.

        We first update the timezone objects using another pydantic model just
        for parsing and propagating here (TimezoneModel). We then walk through
        all DATE-TIME objects referenced by components and lookup any TZID
        property parameters, converting them to a datetime.tzinfo object. The
        DATE-TIME parser will use this instead of the TZID string. We prefer
        to use any python timezones when present.
        """
        # Run when initially parsing a VTIMEZONE or when X-WR-TIMEZONE is present
        if "vtimezone" not in values and "x-wr-timezone" not in values:
            return values

        # First parse the timezones out of the calendar, ignoring everything else
        timezone_model = TimezoneModel.model_validate(values)
        native_tzids = timezoneinfo.native_timezones()
        system_tzids = timezoneinfo.available_timezones()
        tzinfos: dict[str, datetime.tzinfo] = {}
        for timezone in timezone_model.timezones:
            if timezone.tz_id in native_tzids:
                continue
            if timezone.tz_id in system_tzids:
                try:
                    tzinfos[timezone.tz_id] = timezoneinfo.read_tzinfo(
                        timezone.tz_id, resolved_key_as_name=False
                    )
                except timezoneinfo.TimezoneInfoError:
                    tzinfos[timezone.tz_id] = IcsTimezoneInfo.from_timezone(timezone)
            else:
                tzinfos[timezone.tz_id] = IcsTimezoneInfo.from_timezone(timezone)

        # Resolve X-WR-TIMEZONE if present
        default_tzinfo = cls._resolve_x_wr_timezone(values, tzinfos, timezone_model)

        if not tzinfos:
            return values

        # Replace any TZID objects with a reference to tzinfo from this calendar. The
        # DATE-TIME parser will use that if present.
        _LOGGER.debug("Replacing timezone (num %d) references in events", len(tzinfos))
        components = itertools.chain.from_iterable(
            [values.get(component, []) for component in _TZID_COMPONENTS]
        )
        for event in components:
            for field_values in event.values():
                for value in field_values or []:
                    if not isinstance(value, ParsedProperty):
                        continue

                    if tzid_param := value.get_parameter(TZID):
                        if (
                            tzid_param.values
                            and isinstance(tzid_param.values[0], str)
                            and (tzinfo := tzinfos.get(tzid_param.values[0]))
                        ):
                            tzid_param.values = [tzinfo]

                    elif (
                        default_tzinfo
                        and DATETIME_REGEX.match(value.value)
                        and not value.value.endswith("Z")
                    ):
                        if not value.params:
                            value.params = []
                        value.params.append(
                            ParsedPropertyParameter(name=TZID, values=[default_tzinfo])
                        )
        return values

    @classmethod
    def _resolve_x_wr_timezone(
        cls,
        values: dict[str, Any],
        tzinfos: dict[str, datetime.tzinfo],
        timezone_model: TimezoneModel,
    ) -> datetime.tzinfo | None:
        """Resolve the default timezone from X-WR-TIMEZONE if present."""
        x_wr_timezone_props = values.get("x-wr-timezone")
        if not x_wr_timezone_props or not isinstance(x_wr_timezone_props, list):
            return None

        prop = x_wr_timezone_props[0]
        if not isinstance(prop, ParsedProperty):
            return None

        x_wr_timezone = prop.value
        default_tzinfo: datetime.tzinfo | None = None

        # Check if defined in the calendar's vtimezone
        if x_wr_timezone in tzinfos:
            default_tzinfo = tzinfos[x_wr_timezone]
        else:
            default_tzinfo = timezoneinfo.resolve_tzinfo(
                x_wr_timezone, allow_invalid=True
            )

        # Fallback/Warning if not resolvable
        if not default_tzinfo:
            _LOGGER.warning("Could not resolve X-WR-TIMEZONE: %s", x_wr_timezone)
            return None

        # Auto-inject the corresponding VTIMEZONE component if not already present
        has_vtimezone = any(t.tz_id == x_wr_timezone for t in timezone_model.timezones)
        if not has_vtimezone:
            try:
                new_vtimezone = Timezone.from_tzif(x_wr_timezone)
                if "vtimezone" not in values:
                    values["vtimezone"] = []
                values["vtimezone"].append(new_vtimezone)
                tzinfos[x_wr_timezone] = default_tzinfo
            except (timezoneinfo.TimezoneInfoError, ValueError) as err:
                _LOGGER.warning(
                    "Could not generate VTIMEZONE component for X-WR-TIMEZONE %s: %s",
                    x_wr_timezone,
                    err,
                )

        return default_tzinfo

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]
