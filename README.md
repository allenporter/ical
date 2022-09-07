This is an iCalendar rfc 5545 implementation in python. The goal of this
project is to offer a calendar library with the relevant and practical
features needed for building a calendar application (e.g. recurring
events).

ical's main focus is on simplicity, and the internal implementation
is based on existing parsing libraries, where possible, making it
easy to support as much as possible of rfc5545. It is not a goal to
support everything exhaustively, however, the simplicity of the
implementation makes it easy to do so.

See [documentation](https://allenporter.github.io/ical/) for full quickstart and API reference.

# Quickstart

The example below creates a Calendar, then adds an all day event to
the calendar, then iterates over all events on the calendar.

```python
from datetime import date

from ical.calendar import Calendar
from ical.event import Event

calendar = Calendar()
calendar.events.append(
    Event(summary="Event summary", start=date(2022, 7, 3), end=date(2022, 7, 4)),
)
for event in calendar.timeline:
    print(event.summary)
```

# Reading ics files

This example parses an .ics file from disk and creates a `ical.calendar.Calendar` object, then
prints out the events in order:

```python
from pathlib import Path
from ical.calendar_stream import IcsCalendarStream

filename = Path("example/calendar.ics")
with filename.open() as ics_file:
    calendar = IcsCalendarStream.calendar_from_ics(ics_file.read())

print([event.summary for event in calendar.timeline])
```

# Writing ics files

This example writes a calendar object to an ics output file:

```python
from pathlib import Path
from ical.calendar_stream import IcsCalendarStream

filename = Path("example/output.ics")
with filename.open() as ics_file:
    ics_file.write(IcsCalendarStream.calendar_to_ics(calendar))
```

# Recurring events

A calendar event may be recurring (e.g. weekly, monthly, etc). Recurring events
are represented in a `ical.calendar.Calendar` with a single `ical.event.Event` object, however
when observed through a `ical.timeline.Timeline` will be expanded based on the recurrence rule.
See the `rrule`, `rdate`, and `exdate` fields on the `ical.event.Event` for more details.

# Related Work

There are other python rfc5545 implementations that are more mature, and having
been around for many years, are still active, and served as reference
implementations for this project:
  - Ics.py - [github](https://github.com/ics-py/ics-py) [docs](https://icspy.readthedocs.io/en/stable/) - Since 2013
  - icalendar [github](https://github.com/collective/icalendar) [docs](https://icalendar.readthedocs.io/) - Since 2005
