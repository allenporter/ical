"""Library for iCalendar rfc 2445.

This is an iCalendar rfc 5545 implementation in python. The goal of this
project is to offer a calendar library with the relevant and practical
features needed for building a calendar application (e.g. recurring
events).

ical's main focus is on simplicity, and the internal implementation
is based on existing parsing libraries, where possible, making it
easy to support as much as possible of rfc5545. It is not a goal to
support everything exhaustively, however, the simplicity of the
implementation makes it easy to do so.

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
    print(e.summary)
```
"""

__all__ = [
  "alarm",
  "calendar",
  "calendar_stream",
  "event",
  "freebusy",
  "journal",
  "parsing",
  "timeline",
  "timezone",
  "todo",
  "types",
  "tzif",
  "util",
]
