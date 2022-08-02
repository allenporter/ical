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
- Encoded timezones e.g.
        - DTSTART;TZID=America/Los_Angeles:20220802T090000
        - DTEND;TZID=America/Los_Angeles:20220802T093000
        + DTSTART:20220802T090000Z
        + DTEND:20220802T093000Z
- Repeated property serialization e.g. 'resources.yaml'. Multi-line vs repeated, and preserving property parameters
- Property parameters for attendee, organizer fields
- Recurrence
  - Verify start date format is the same as the event
  - Verify daylight saving time in until and start is the same
- Recurrence timezone formattings
- Recurrence datetime field encoded properly
- Ignore and preserve unsupported Recurrence rules

- Components
  - Event
    ---- once
    - seq
    - transp
    - url
    - recurid
    -- multiple
    - attach
    - categories
    - contact
    - related
  - todo
  - journal
  - free/busy
  - time zone
  - alarm

- Component properties
  - attachment
  - categories
  - classification
  - comment
  - description
  - geographic position
  - location
  - percent complete
  - priority
  - resources
  - status
  - summary

- Recurrence
  - rdate
  - rstatus
  - exdate
