"""The Calendar component."""

from __future__ import annotations

import datetime
import itertools
import logging
from typing import Optional, Any
import zoneinfo

try:
    from pydantic.v1 import Field, root_validator
except ImportError:
    from pydantic import Field, root_validator  # type: ignore[no-redef, assignment]

from .component import ComponentModel
from .event import Event
from .freebusy import FreeBusy
from .journal import Journal
from .types.date_time import TZID
from .parsing.property import ParsedProperty
from .timeline import Timeline, calendar_timeline
from .timezone import Timezone, TimezoneModel, IcsTimezoneInfo
from .todo import Todo
from .util import local_timezone, prodid_factory


_LOGGER = logging.getLogger(__name__)

_VERSION = "2.0"

# Components that may contain TZID objects
_TZID_COMPONENTS = ["vevent", "vtodo", "vjournal", "vfreebusy"]


class Calendar(ComponentModel):
    """A sequence of calendar properties and calendar components."""

    calscale: Optional[str] = None
    method: Optional[str] = None
    prodid: str = Field(default_factory=lambda: prodid_factory())
    version: str = Field(default_factory=lambda: _VERSION)

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
    extras: list[ParsedProperty] = Field(default_factory=list)

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar.

        All day events are returned as if the attendee is viewing from UTC time.
        """
        return self.timeline_tz()

    def timeline_tz(self, tzinfo: datetime.tzinfo | None = None) -> Timeline:
        """Return a timeline view of events on the calendar.

        All events are returned as if the attendee is viewing from the
        specified timezone. For example, this affects the order that All Day
        events are returned.
        """
        return calendar_timeline(self.events, tzinfo=tzinfo or local_timezone())

    @root_validator(pre=True)
    def _propagate_timezones(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Propagate timezone information down to date-time objects.

        This results in parsing the timezones twice: Once here, then once again
        in the calendar itself. This does imply that if a vtimezone object is
        changed live, the DATE-TIME objects are not updated.

        We first update the timezone objects using another pydantic model just
        for parsing and propagaint here (TimezoneModel). We then walk through
        all DATE-TIME objects referenced by components and lookup any TZID
        property parameters, converting them to a datetime.tzinfo object. The
        DATE-TIME parser will use this instead of the TZID string. We prefer
        to use any python timezones when present.
        """
        # Run only when initially parsing a VTIMEZONE
        if "vtimezone" not in values:
            return values

        # First parse the timezones out of the calendar, ignoring everything else
        timezone_model = TimezoneModel.parse_obj(values)
        system_tzids = zoneinfo.available_timezones()
        tzinfos: dict[str, datetime.tzinfo] = {
            timezone.tz_id: IcsTimezoneInfo.from_timezone(timezone)
            for timezone in timezone_model.timezones
            if timezone.tz_id not in system_tzids
        }
        if not timezone_model.timezones:
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
                    if (
                        not (tzid_param := value.get_parameter(TZID))
                        or not tzid_param.values
                    ):
                        continue
                    if isinstance(tzid_param.values[0], str) and (
                        tzinfo := tzinfos.get(tzid_param.values[0])
                    ):
                        tzid_param.values = [tzinfo]
        return values
