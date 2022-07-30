# ical

This is an iCalendar rfc 5545 implementation in python. The goal of this
project is to offer a calendar library with the most relevant and
practically needed features when building a calendar application (e.g.
recurring events).

In support of that goal, the development principles include robust and
simple parsing using existing parsing libraries where possible, use of
modern python, and high test coverage. It is not a goal to exhaustively
support all rfc5545 features directly, fully support the grammar and
handle anything unsupported gracefully.

This library is still in early development and as a result, every release
before 1.0 will likely contain breaking changes.

## Example Usage

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

## Related Work

There are other python rfc5545 implementations that are more mature, and having
been around for many years, are still active, and served as reference
implementations for this project:
  - Ics.py - [github](https://github.com/ics-py/ics-py) [docs](https://icspy.readthedocs.io/en/stable/) - Since 2013
  - icalendar [github](https://github.com/collective/icalendar) [docs](https://icalendar.readthedocs.io/) - Since 2005
