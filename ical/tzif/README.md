# tzif

This python library provides time transitions for timezones. This library does
not directly provide time zone data, and instead uses the same sources as
`zoneinfo` which includes the system timezone database or the `tzdata` package.

## Background

iCalendar files are fully specified, and there is no ambiguity with respect
to how times in timezones are interpreted. That is, an iCalendar contains a
VTIMEZONE that has all local time transitions fully specified. That means
that an iCalendar implementation must have a timezone database.

[PEP 615](https://peps.python.org/pep-0615/) adds support for the IANA Time Zone
Database in the base python and describes the datasources used to implement
timezones and the `zoneinfo` package. However, those APIs do not expose all
the underlying timezone transitions.

## Details

This package works similarly to the `zoneinfo` package, exposing the underlying
datasources for use by libraries that need timezone transitions. Timezone data
is stored in the Time Zone Information Format (TZif) described in [rfc8536](https://datatracker.ietf.org/doc/html/rfc8536).

Currently this library just reads the `tzdata` sources.
