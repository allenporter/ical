# Unsupported

This captures known parts of rfc5545 that are currently missing, mostly as a
TODO tracker so they are not forgotten. This is not meant to be fully exhaustive.

- Ignore and preserve x-comp and iana-comp values unrecognized
- Complete todo properties
- Complete vevent properties
- Reduce visibility of internal parsers (e.g. contentlines)
- Encoding escaped characters in property values (e.g. commas)
- Unknown components (fix extra field parsing)
- Accessing non-formatting property parameters
- Serializing property parameters
- Serializing extra properties
- Encoded timezones
- Add Organizer fields
- Encode newlines in description fields properly ('event_multi_day.yaml' test)
