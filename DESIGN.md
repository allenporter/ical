# Design

## Overall Design

TODO: Replace with overall design

## Recurrence

The design for recurrence was based on the [design guidance](https://github.com/bmoeskau/Extensible/blob/master/recurrence-overview.md) from Calendar Pro.

### Application Goals

The motivation is to support most simple use cases (e.g. home and small
business applications) that require repeating events such as daily, weekly,
monthly. The other lesser used aspects of the rfc5545 recurrence format
like secondly, minutely, hourly or yearly are not needed for these types
of use cases.

There are performance implications based on possible event storage and
event generation trade-offs. The initial approach will be to design for
simplicity first, targeting smaller calendars (e.g. tens of recurring
events, not thousands) and may layer in performance optimizations such
as caching later, under the existing APIs.

### Recurrence Format

Like other components in this library, the recurrence format is parsed into
a data object using pydantic. This library has no additional internal
storage. An rrule is stored as a column of an event.

### Event Generation

The `Timeline` interface is used to iterate over events, and can also work
to abstract away the details of recurring events. Recurring events may
repeat indefinitely, imply the existing iterator only based may need careful
consideration e.g. it can't serialize all events into the sorted heapq.

The python library `dateutil` has an [rrule](https://dateutil.readthedocs.io/en/stable/rrule.html)
module with a lightweight and complete implementation of recurrence rules.

Events are generated using a timeline fed by bunch of iterators. There is
one iterator for all non-recurring events, then a separate iterator for
each recurring event. A merged iterator peeks into the input of each
iterator to decide which one to pull from when determinig the next item
in the iterator.

### Recurrence Editing

WIP
