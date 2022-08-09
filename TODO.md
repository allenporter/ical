# Unsupported

This captures known parts of rfc5545 that are currently missing, mostly as a
TODO tracker so they are not forgotten. This is not meant to be fully exhaustive.

- Testing example (e.g. using shared fixtures)
- Reduce visibility of internal parsers (e.g. contentlines)
- Unknown components (fix extra field parsing)
- Accessing non-formatting property parameters
- Serializing property parameters
- Serializing extra properties
- Encoded timezones e.g.
        - DTSTART;TZID=America/Los_Angeles:20220802T090000
        - DTEND;TZID=America/Los_Angeles:20220802T093000
        + DTSTART:20220802T090000Z
        + DTEND:20220802T093000Z
- Repeated property serialization e.g. 'resources.yaml'. Multi-line vs repeated, and preserving property parameters
- Repeated property parameters. Are these allowed and should be supported? Or just over-write?
- Recurrence
  - Verify start date format is the same as the event
  - Verify daylight saving time in until and start is the same
- Recurrence timezone formattings
- Recurrence datetime field encoded properly
- Ignore and preserve unsupported Recurrence rules
- Attendee parameters, e.g.
    ATTENDEE;PARTSTAT=ACCEPTED:mailto:jqpublic@example.com
    ATTENDEE:mailto:jqpublic@example.com

- Related TO:
    - VTODO can be related to VTODO or VEVENT

- Components
  - Event
    -- multiple
    - attach
    - related
  - journal
  - free/busy
  - time zone
  - alarm

- Component properties
  - attachment
  - comment
  - description
  - percent complete
  - priority
  - resources
  - status
  - summary
