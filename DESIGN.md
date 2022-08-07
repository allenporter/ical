# Design

## Data Model

The calendar data model is described using [pydantic](https://github.com/samuelcolvin/pydantic)
models. Pydantic allows expressing effectively a dataclass with types
and validation rules, which are reused across components. The data model
mirrors the rfc5545 spec with a separate object for each type of component
e.g. a calendar, event, todo, etc.

## Parsing and Encoding

The rfc5545 spec defines a text file format, and the overall structure defines
a series of components (e.g. a calendar, an event, a todo) and properties (e.g.
a summary, start date and time, due date, category). Properties may additionally
have parameters such as a timezone or alternative text display. Components
have a hierarchy (e.g. a calendar component has an event sub-component).

The ical library uses [pyparsing](https://github.com/pyparsing/pyparsing) to
create a very simple gammar for rfc5545, converting the individual lines of an
ics file (called "contentlines") into a structured `ParseResult` object which
has a dictionary of fields. The library then iterates through each line to
build a stack to manage components and subcomponents, parses individual
properties and parameters associated with the active component, then returns
a `ParsedComponent` which contains other components and properties. At this
point we have a tree of components and properties, but have not yet interpreted
the meaning.

The data model is parsed using [pydantic](https://github.com/samuelcolvin/pydantic)
and has parsing and validation rules for each type of data. That is, the library
has a bridge between strongly typed rfc5545 properties (e.g. `DATE`, `DATE-TIME`) and
python types (e.g. `datetime.date`, `datetime.datetime`). Where possible, the
built in pydantic encoding and decoding is used, however ical makes heavy use of
custom root validators to perform a lot of the type mapping. Additionally, we want
to be able to support parsing the calendar data model from the output of the parser
as well as parsing values supplied by the user when creating objects manually.

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
