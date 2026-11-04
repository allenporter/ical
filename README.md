# ical

[![PyPI version](https://img.shields.io/pypi/v/ical.svg)](https://pypi.org/project/ical/)
[![CI](https://github.com/allenporter/ical/actions/workflows/test.yaml/badge.svg)](https://github.com/allenporter/ical/actions/workflows/test.yaml)
[![Documentation](https://img.shields.io/badge/docs-allenporter.github.io%2Fical-blue)](https://allenporter.github.io/ical/)

A modern Python [RFC 5545](https://datatracker.ietf.org/doc/html/rfc5545) iCalendar library with **built-in recurring event support** — no companion libraries needed.

```python
from ical.calendar_stream import IcsCalendarStream

cal = IcsCalendarStream.calendar_from_ics(ics_content)

# Recurring events are automatically expanded — just iterate
for event in cal.timeline:
    print(event.start, event.summary)
```

## Why ical?

Most Python iCalendar libraries require two separate packages to handle recurring events:

```python
# The typical ecosystem approach — two libraries, two APIs
import icalendar
import recurring_ical_events

cal = icalendar.Calendar.from_ical(ics_content)
events = recurring_ical_events.of(cal).between(start, end)
```

`ical` handles this natively with a single, unified [`Timeline`](https://allenporter.github.io/ical/) interface, with a Pythonic API and validated inputs.

| Feature | `ical` | `icalendar` | `ics.py` |
|---|---|---|---|
| Built-in recurrence expansion | ✅ | ❌ needs `recurring-ical-events` | ❌ |
| Incremental recurrence & timezone caching | ✅ | ❌ | ❌ |
| Pythonic attribute access (`event.start`, `event.summary`) | ✅ | ❌ (`event.get('DTSTART').dt`) | ✅ |
| Input validation with clear error messages | ✅ | ❌ | ❌ |
| Full type annotations (`py.typed`) | ✅ strict `ty` | ✅ v7+ | ❌ |
| Application-level store API | ✅ | ❌ | ❌ |
| RFC 7986 / RFC 6868 / RFC 8536 | ✅ | partial | ❌ |
| Active maintenance | ✅ | ✅ | ⚠️ stalled |

## Used By

- [**Home Assistant**](https://www.home-assistant.io/) — powers the [Local Calendar](https://www.home-assistant.io/integrations/local_calendar/), [Remote Calendar](https://www.home-assistant.io/integrations/remote_calendar/), and [Google Calendar](https://www.home-assistant.io/integrations/google/) integrations (including serving locally-synced calendars for performance)

## Installation

```bash
uv add ical
```

Or with pip:

```bash
pip install ical
```

Requires Python 3.11+.

Fetching calendars from a url asynchronously (see below) requires the optional `async` extra, which pulls in [`aiohttp`](https://docs.aiohttp.org/):

```bash
pip install ical[async]
```

## Quickstart

### Reading an .ics file

Parse a calendar file and iterate over events in chronological order, with recurring events automatically expanded:

```python
from pathlib import Path
from ical.calendar_stream import IcsCalendarStream
from ical.exceptions import CalendarParseError

filename = Path("calendar.ics")
with filename.open() as ics_file:
    try:
        cal = IcsCalendarStream.calendar_from_ics(ics_file.read())
    except CalendarParseError as err:
        print(f"Failed to parse '{filename}': {err}")
    else:
        for event in cal.timeline:
            print(event.start, event.summary)
```

### Fetching a remote .ics url

Fetching a remote calendar over HTTP without blocking the event loop requires the optional `ical[async]` extra:

```python
from ical.calendar_stream import IcsCalendarStream

cal = await IcsCalendarStream.calendar_from_url("https://example.com/calendar.ics")
for event in cal.timeline:
    print(event.start, event.summary)
```

An existing `aiohttp.ClientSession` can be passed in via the `session` argument to reuse connection pooling; otherwise a session is created and closed automatically for the request.

### Creating a calendar

```python
from datetime import date
from ical.calendar import Calendar
from ical.event import Event

cal = Calendar()
cal.events.append(
    Event(summary="Team standup", start=date(2024, 1, 15), end=date(2024, 1, 16)),
)
for event in cal.timeline:
    print(event.summary)
```

### Writing an .ics file

```python
from pathlib import Path
from ical.calendar_stream import IcsCalendarStream

with Path("output.ics").open("w") as f:
    f.write(IcsCalendarStream.calendar_to_ics(cal))
```

### Recurring events

Recurring events are stored once in the calendar but automatically expanded by the `Timeline`:

```python
from datetime import date
from ical.calendar import Calendar
from ical.event import Event
from ical.types.recur import Recur

cal = Calendar()
cal.events.append(
    Event(
        summary="Weekly standup",
        start=date(2024, 1, 15),
        end=date(2024, 1, 16),
        rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=10"),
    )
)

# All 10 occurrences are expanded automatically
for event in cal.timeline:
    print(event.start, event.summary)
```

### Application-level API

For managing calendar state in an application (ensuring timezones are set correctly, editing individual instances of recurring events, etc.), use `ical.store`:

```python
from ical.store import EventStore
from ical.event import Event
from datetime import datetime, timezone

store = EventStore()
store.add(Event(summary="Meeting", start=datetime(2024, 1, 15, 9, tzinfo=timezone.utc)))
```

See the [full documentation](https://allenporter.github.io/ical/) for the complete API reference.

## Performance

`ical` is optimized for applications like Home Assistant that repeatedly check a calendar for today's events or the next upcoming event — even when the calendar has thousands of events or recurring rules (like birthdays and weekly meetings) that started years ago:

- **Only builds events you actually read:** Scanning a timeline compares lightweight start/end times and only constructs full `Event` objects for occurrences that match your query.
- **Caches recurring rules and timezone transitions:** Expanding a decades-old recurrence rule takes work the first time, so `ical` caches expanded dates and timezone daylight-saving transitions as you query. Subsequent lookups reuse that cache instead of recalculating from the beginning.
- **Skips past history on range queries:** Methods like `overlapping()`, `on_date()`, and `active_after()` jump directly to your start date rather than walking through years of past occurrences one by one.

| Workload | `ical` | `icalendar` + `recurring-ical-events` |
|---|---:|---:|
| Recurring range query (100 recurring series, cold / first query) | ~252 ms | ~254 ms |
| Recurring range query (100 recurring series, warm) | **~2.4 ms** (~41,000 series/s) | ~254 ms (~390 series/s) |
| Large recurring calendar query (1,000 recurring series, cold / first query) | ~2,370 ms | ~2,320 ms |
| Large recurring calendar query (1,000 recurring series, warm) | **~28 ms** (~35,000 series/s) | ~2,320 ms (~430 series/s) |
| Non-recurring range query (2,000 events with custom `VTIMEZONE`) | **~8.9 ms** (~225,000 events/s) | ~42 ms (~47,000 events/s) |
| `.ics` serialization (500 `VEVENT`s) | **~6.9 ms** (~72,000 events/s) | ~10.6 ms (~47,000 events/s) |
| `.ics` parsing + Pydantic validation (500 `VEVENT`s) | **~29 ms** (~17,000 events/s) | ~18.5 ms (unvalidated AST) |

## Technical Guides

We publish detailed technical guides exploring the library's design:
- [Timezones & Custom TzInfo](https://allenporter.github.io/ical/ical/guides/timezone.html)
- [Recurrence Rules & Event Generation](https://allenporter.github.io/ical/ical/guides/recurrence.html)
- [Calendar Compatibility Layer](https://allenporter.github.io/ical/ical/guides/compatibility.html)

## Supported RFCs

- [RFC 5545](https://datatracker.ietf.org/doc/html/rfc5545) — Internet Calendaring and Scheduling Core Object Specification (iCalendar)
- [RFC 6868](https://datatracker.ietf.org/doc/html/rfc6868) — Parameter Value Encoding in iCalendar and vCard
- [RFC 7986](https://datatracker.ietf.org/doc/html/rfc7986) — New Properties for iCalendar
- [RFC 8536](https://datatracker.ietf.org/doc/html/rfc8536) — The Time Zone Information Format (TZif)

## Comparison with other libraries

`ical` is designed for applications that need a complete, modern solution. You may prefer an alternative if:

- **[`icalendar`](https://github.com/collective/icalendar)** — You need low-level control over raw iCalendar components, jCal (JSON) support, or maximum ecosystem compatibility. You prefer to expand recurring events manually and don't mind a second library ([`recurring-ical-events`](https://github.com/niccokunzmann/python-recurring-ical-events)). You need to support legacy Python versions (3.8+) that `ical` does not target.
- **[`ics.py`](https://github.com/ics-py/ics-py)** — You need a simple read-only script and do not require recurrence support. Note: no stable release since 0.7.2 (August 2021).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and development instructions.
