"""Tests for Conference data type."""

from __future__ import annotations

from ical.calendar_stream import IcsCalendarStream
from ical.types import Conference, Feature, Uri


def test_conference_properties() -> None:
    """Test programmatic validation of Conference parameters."""
    conf = Conference.model_validate(
        {
            "value": "https://zoom.us/j/123",
            "FEATURE": ["AUDIO"],
            "LABEL": "My Zoom",
            "LANGUAGE": "en-US",
        }
    )
    assert conf.uri == Uri("https://zoom.us/j/123")
    assert conf.feature == [Feature.AUDIO]
    assert conf.label == "My Zoom"
    assert conf.language == "en-US"


def test_feature_enum() -> None:
    """Test Feature enum validation and fallback handling."""
    assert Feature("AUDIO") == Feature.AUDIO
    assert Feature("audio") == Feature.AUDIO  # case insensitive fallback lookup
    assert Feature("x-custom") == "x-custom"  # custom token fallback
    assert Feature._missing_(None) is None


def test_conference_value_uri() -> None:
    """Test parsing CONFERENCE property with VALUE=URI parameter (issue #670)."""
    ics = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Example//EN\n"
        "BEGIN:VEVENT\n"
        "UID:test-conference-uri\n"
        "DTSTART:20260805T100000Z\n"
        "DTEND:20260805T110000Z\n"
        "SUMMARY:Meeting with Conference Link\n"
        "CONFERENCE;VALUE=URI:https://zoom.us/j/1234567890\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    calendar = IcsCalendarStream.calendar_from_ics(ics)
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert len(event.conference) == 1
    assert event.conference[0].uri == Uri("https://zoom.us/j/1234567890")


def test_rfc7986_canonical_examples() -> None:
    """Test canonical RFC 7986 Section 5.11 CONFERENCE examples."""
    ics = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Example//EN\n"
        "BEGIN:VEVENT\n"
        "UID:rfc7986-conference-examples\n"
        "DTSTART:20260805T100000Z\n"
        "DTEND:20260805T110000Z\n"
        "SUMMARY:RFC 7986 Conference Test\n"
        "CONFERENCE;VALUE=URI;FEATURE=AUDIO,VIDEO;"
        'LABEL="Web video chat, access code=76543":'
        "https://video-chat.example.com/;group-id=1234\n"
        'CONFERENCE;VALUE=URI;FEATURE=AUDIO;LABEL="Attendee dial-in":'
        "tel:+1-412-555-0123,,,654321#\n"
        "CONFERENCE;VALUE=URI;FEATURE=MODERATOR,AUDIO;"
        'LABEL="Moderator dial-in":tel:+1-412-555-0123,,,987654#\n'
        "CONFERENCE;VALUE=URI;FEATURE=CHAT:"
        "xmpp:room123@chat.example.com?join\n"
        "CONFERENCE;VALUE=URI;FEATURE=AUDIO,VIDEO:sip:user@example.com\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    calendar = IcsCalendarStream.calendar_from_ics(ics)
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert len(event.conference) == 5

    # Web video chat
    assert event.conference[0].uri == Uri(
        "https://video-chat.example.com/;group-id=1234"
    )
    assert event.conference[0].feature == [Feature.AUDIO, Feature.VIDEO]
    assert event.conference[0].label == "Web video chat, access code=76543"

    # Attendee tel: dial-in
    assert event.conference[1].uri == Uri("tel:+1-412-555-0123,,,654321#")
    assert event.conference[1].feature == [Feature.AUDIO]
    assert event.conference[1].label == "Attendee dial-in"

    # Moderator tel: dial-in
    assert event.conference[2].uri == Uri("tel:+1-412-555-0123,,,987654#")
    assert event.conference[2].feature == ["MODERATOR", Feature.AUDIO]
    assert event.conference[2].label == "Moderator dial-in"

    # XMPP chat
    assert event.conference[3].uri == Uri("xmpp:room123@chat.example.com?join")
    assert event.conference[3].feature == [Feature.CHAT]

    # SIP call
    assert event.conference[4].uri == Uri("sip:user@example.com")
    assert event.conference[4].feature == [Feature.AUDIO, Feature.VIDEO]
