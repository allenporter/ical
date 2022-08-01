# Design

## Overall Design

TODO: Replace with overall design

## Recurrence

The design for recurrence was based on the [design guidance](https://github.com/bmoeskau/Extensible/blob/master/recurrence-overview.md) from Calendar Pro.

### Application Goals

The motivation is to support most simple use cases (e.g. home and small
business applications) that require repeating events such as daily, weekly,
monthly -- but not all the other lesser used aspects of the rfc5545 recurrence
format like secondly, minutely, hourly or yearly.

### Recurrence Format

Like other components in this library, the recurrence format is parsed into
a data object using pydantic. This library has no additional internal
storage.

### Event Generation

WIP

### Recurrence Editing

WIP
