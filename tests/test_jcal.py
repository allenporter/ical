import datetime
import json
from typing import Any
import pytest

from ical.alarm import Action, Alarm
from ical.calendar import Calendar
from ical.calendar_stream import CalendarStream, JcalCalendarStream
from ical.event import Event, EventStatus
from ical.freebusy import FreeBusy
from ical.journal import Journal, JournalStatus
from ical.timezone import Timezone
from ical.todo import Todo, TodoStatus
from ical.exceptions import CalendarParseError
from ical.types import (
    Attachment,
    CalAddress,
    Conference,
    Frequency,
    Geo,
    Image,
    Period,
    Priority,
    Range,
    Recur,
    RecurrenceId,
    RelatedTo,
    RequestStatus,
)
from ical.types.image import Display
from ical.types.period import FreeBusyType
from ical.types.uri import Uri

FIXED_DTSTAMP = datetime.datetime(2026, 8, 24, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.mark.parametrize(
    ("calendar", "expected_jcal"),
    [
        # 1. Minimal Calendar envelope
        (
            Calendar(prodid="-//Example Corp.//EN", version="2.0"),
            [
                "vcalendar",
                [
                    ["prodid", {}, "text", "-//Example Corp.//EN"],
                    ["version", {}, "text", "2.0"],
                ],
                [],
            ],
        ),
        # 2. Calendar with Event (text, date-time, and integer properties)
        (
            Calendar(
                prodid="-//Example Corp.//EN",
                version="2.0",
                vevent=[
                    Event(
                        dtstamp=FIXED_DTSTAMP,
                        uid="event-123",
                        summary="Architecture Review",
                        description="Review jCal design with team",
                        sequence=1,
                    )
                ],
            ),
            [
                "vcalendar",
                [
                    ["prodid", {}, "text", "-//Example Corp.//EN"],
                    ["version", {}, "text", "2.0"],
                ],
                [
                    [
                        "vevent",
                        [
                            ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                            ["uid", {}, "text", "event-123"],
                            ["summary", {}, "text", "Architecture Review"],
                            ["description", {}, "text", "Review jCal design with team"],
                            ["sequence", {}, "integer", 1],
                        ],
                        [],
                    ]
                ],
            ],
        ),
        # 3. Calendar with Todo and multi-valued text categories
        (
            Calendar(
                prodid="-//Example Corp.//EN",
                version="2.0",
                vtodo=[
                    Todo(
                        dtstamp=FIXED_DTSTAMP,
                        uid="todo-456",
                        summary="Write tests",
                        categories=["Work", "Python"],
                    )
                ],
            ),
            [
                "vcalendar",
                [
                    ["prodid", {}, "text", "-//Example Corp.//EN"],
                    ["version", {}, "text", "2.0"],
                ],
                [
                    [
                        "vtodo",
                        [
                            ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                            ["uid", {}, "text", "todo-456"],
                            ["categories", {}, "text", "Work", "Python"],
                            ["summary", {}, "text", "Write tests"],
                        ],
                        [],
                    ]
                ],
            ],
        ),
    ],
    ids=[
        "minimal_calendar",
        "calendar_with_event",
        "calendar_with_todo_and_categories",
    ],
)
def test_calendar_as_jcal(calendar: Calendar, expected_jcal: list[Any]) -> None:
    """Test serializing Calendar model instances to jCal format."""
    assert calendar.as_jcal() == expected_jcal


def test_jcal_stream_roundtrip() -> None:
    """Test parsing jCal into Calendar model and re-encoding."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-123"],
                    ["summary", {}, "text", "Architecture Review"],
                    ["description", {}, "text", "Review jCal design with team"],
                    ["sequence", {}, "integer", 1],
                ],
                [],
            ]
        ],
    ]

    cal = JcalCalendarStream.calendar_from_jcal(jcal_input)
    assert cal.prodid == "-//Example Corp.//EN"
    assert cal.version == "2.0"
    assert len(cal.events) == 1
    assert cal.events[0].dtstamp == FIXED_DTSTAMP
    assert cal.events[0].uid == "event-123"
    assert cal.events[0].summary == "Architecture Review"
    assert cal.events[0].description == "Review jCal design with team"
    assert cal.events[0].sequence == 1

    # Re-encode to jCal
    assert JcalCalendarStream.calendar_to_jcal(cal) == jcal_input


def test_ics_to_jcal_model_bridge() -> None:
    """Test reading ICS content and generating jCal output via CalendarStream."""
    ics_content = (
        "BEGIN:VCALENDAR\n"
        "PRODID:-//Example Corp.//EN\n"
        "VERSION:2.0\n"
        "BEGIN:VEVENT\n"
        "DTSTAMP:20260824T120000Z\n"
        "UID:event-123\n"
        "SUMMARY:Meeting with Fred\n"
        "END:VEVENT\n"
        "END:VCALENDAR"
    )

    stream = CalendarStream.from_ics(ics_content)
    jcal_output = stream.jcal()

    assert jcal_output == [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-123"],
                    ["summary", {}, "text", "Meeting with Fred"],
                ],
                [],
            ]
        ],
    ]


def test_jcal_date_and_extra_properties() -> None:
    """Test parsing and serialization of jCal DATE and extra/extension properties."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-123"],
                    ["dtstart", {}, "date", "2026-08-24"],
                    ["x-coffee-data", {"origin": "Guinea"}, "unknown", "Stenophylla"],
                ],
                [],
            ]
        ],
    ]

    cal = Calendar.from_jcal(jcal_input)
    assert len(cal.events) == 1
    event = cal.events[0]
    assert event.dtstart == datetime.date(2026, 8, 24)
    assert len(event.extras) == 1
    assert event.extras[0].name == "x-coffee-data"
    assert event.extras[0].value == "Stenophylla"
    assert event.extras[0].params is not None
    assert event.extras[0].params[0].name == "ORIGIN"
    assert event.extras[0].params[0].values == ["Guinea"]

    # Re-encode to jCal
    assert cal.as_jcal() == jcal_input


@pytest.mark.parametrize(
    ("invalid_input", "error_match"),
    [
        ([], "Invalid jCal data"),
        (["vevent", []], "Invalid jCal component structure"),
        (["vevent", "not-a-list", []], "Invalid jCal component properties"),
        (["vevent", [], "not-a-list"], "Invalid jCal component properties"),
        (["vevent", [["summary"]], []], "Invalid jCal property structure"),
    ],
    ids=[
        "empty_stream",
        "missing_subcomponents",
        "properties_not_a_list",
        "subcomponents_not_a_list",
        "property_too_short",
    ],
)
def test_jcal_invalid_structures(invalid_input: list[Any], error_match: str) -> None:
    """Test validation and error handling on malformed jCal structures."""
    with pytest.raises(CalendarParseError, match=error_match):
        CalendarStream.from_jcal(invalid_input)


def test_jcal_duration_property() -> None:
    """Test parsing and serialization of jCal DURATION properties."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-dur-1"],
                    ["dtstart", {}, "date-time", "2026-08-24T09:00:00Z"],
                    ["duration", {}, "duration", "PT1H30M"],
                ],
                [],
            ]
        ],
    ]

    cal = Calendar.from_jcal(jcal_input)
    assert len(cal.events) == 1
    event = cal.events[0]
    assert event.duration == datetime.timedelta(hours=1, minutes=30)
    assert cal.as_jcal() == jcal_input


def test_jcal_timezone_and_tzid() -> None:
    """Test parsing and serialization of jCal DATE-TIME with TZID parameter."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-tz-1"],
                    [
                        "dtstart",
                        {"tzid": "America/New_York"},
                        "date-time",
                        "2026-08-24T09:00:00",
                    ],
                ],
                [],
            ]
        ],
    ]

    cal = Calendar.from_jcal(jcal_input)
    assert len(cal.events) == 1
    event = cal.events[0]
    assert isinstance(event.dtstart, datetime.datetime)
    assert str(event.dtstart.tzinfo) == "America/New_York"
    assert event.dtstart.hour == 9

    assert cal.as_jcal() == jcal_input


def test_jcal_multi_calendar_stream() -> None:
    """Test multi-calendar stream parsing and encoding."""
    multi_jcal = [
        [
            "vcalendar",
            [
                ["prodid", {}, "text", "-//First//EN"],
                ["version", {}, "text", "2.0"],
            ],
            [],
        ],
        [
            "vcalendar",
            [
                ["prodid", {}, "text", "-//Second//EN"],
                ["version", {}, "text", "2.0"],
            ],
            [],
        ],
    ]

    stream = CalendarStream.from_jcal(multi_jcal)
    assert len(stream.calendars) == 2
    assert stream.calendars[0].prodid == "-//First//EN"
    assert stream.calendars[1].prodid == "-//Second//EN"
    assert stream.jcal() == multi_jcal


def test_jcal_recurrence_rule_complex() -> None:
    """Test parsing and serialization of complex jCal recurrence rules."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-rrule-complex"],
                    ["dtstart", {}, "date-time", "2026-08-24T09:00:00Z"],
                    [
                        "rrule",
                        {},
                        "recur",
                        {
                            "freq": "MONTHLY",
                            "byday": ["1SU", "-1SU"],
                            "bymonth": [4],
                            "count": 10,
                            "interval": 2,
                        },
                    ],
                ],
                [],
            ]
        ],
    ]

    cal = Calendar.from_jcal(jcal_input)
    assert len(cal.events) == 1
    event = cal.events[0]
    assert event.rrule is not None
    assert event.rrule.freq.value == "MONTHLY"
    assert event.rrule.count == 10
    assert event.rrule.interval == 2
    assert len(event.rrule.by_weekday) == 2
    assert event.rrule.by_weekday[0].occurrence == 1
    assert event.rrule.by_weekday[0].weekday.value == "SU"
    assert event.rrule.by_weekday[1].occurrence == -1
    assert event.rrule.by_weekday[1].weekday.value == "SU"
    assert event.rrule.by_month == [4]

    assert cal.as_jcal() == jcal_input


def test_jcal_rich_components_and_types() -> None:
    """Test jCal support for CalAddress, Geo, RelatedTo, Attachment, Conference, and Image."""
    cal = Calendar(
        prodid="-//Example Corp.//EN",
        version="2.0",
        events=[
            Event(
                dtstamp=FIXED_DTSTAMP,
                uid="event-rich-1",
                summary="Rich Event",
                attendees=[
                    CalAddress(
                        uri=Uri("mailto:alice@example.com"),
                        common_name="Alice Smith",
                        status="ACCEPTED",
                    )
                ],
                geo=Geo(lat=37.386013, lng=-122.082932),
                related_to=[RelatedTo(uid="parent-event-999")],
                attach=[
                    Attachment(
                        uri=Uri("https://example.com/spec.pdf"),
                        fmttype="application/pdf",
                    )
                ],
                conference=[
                    Conference(
                        uri=Uri("https://meet.example.com/room-1"),
                        label="Project Meeting",
                    )
                ],
                image=[
                    Image(
                        uri=Uri("https://example.com/badge.png"),
                        format_type="image/png",
                    )
                ],
            )
        ],
    )

    jcal_data = cal.as_jcal()
    # Confirm it serializes to valid JSON without error
    json_str = json.dumps(jcal_data)
    assert "alice@example.com" in json_str
    assert "37.386013" in json_str

    cal_reparsed = Calendar.from_jcal(jcal_data)
    assert len(cal_reparsed.events) == 1
    event = cal_reparsed.events[0]
    assert event.summary == "Rich Event"
    assert len(event.attendees) == 1
    assert str(event.attendees[0].uri) == "mailto:alice@example.com"
    assert event.attendees[0].common_name == "Alice Smith"
    assert event.attendees[0].status == "ACCEPTED"
    assert event.geo is not None
    assert event.geo.lat == 37.386013
    assert event.geo.lng == -122.082932
    assert len(event.related_to) == 1
    assert event.related_to[0].uid == "parent-event-999"
    assert len(event.attach) == 1
    assert str(event.attach[0].uri) == "https://example.com/spec.pdf"
    assert len(event.conference) == 1
    assert str(event.conference[0].uri) == "https://meet.example.com/room-1"
    assert len(event.image) == 1
    assert str(event.image[0].uri) == "https://example.com/badge.png"


def test_jcal_vtimezone_and_observance() -> None:
    """Test jCal parsing and encoding of VTIMEZONE and standard/daylight observances."""
    jcal_tz = [
        "vtimezone",
        [["tzid", {}, "text", "America/New_York"]],
        [
            [
                "standard",
                [
                    ["dtstart", {}, "date-time", "2007-11-04T02:00:00"],
                    ["tzoffsetto", {}, "utc-offset", "-05:00"],
                    ["tzoffsetfrom", {}, "utc-offset", "-04:00"],
                    [
                        "rrule",
                        {},
                        "recur",
                        {
                            "freq": "YEARLY",
                            "byday": ["1SU"],
                            "bymonth": [11],
                        },
                    ],
                    ["tzname", {}, "text", "EST"],
                ],
                [],
            ]
        ],
    ]

    tz = Timezone.from_jcal(jcal_tz)
    assert tz.tz_id == "America/New_York"
    assert len(tz.standard) == 1
    std = tz.standard[0]
    assert std.tz_name == ["EST"]
    assert std.tz_offset_from.offset == datetime.timedelta(hours=-4)
    assert std.tz_offset_to.offset == datetime.timedelta(hours=-5)
    assert std.rrule is not None
    assert std.rrule.freq.value == "YEARLY"

    assert tz.as_jcal() == jcal_tz


def test_jcal_recur_until_formats() -> None:
    """Test jCal recurrence UNTIL parameter formatted as date and date-time."""
    # Until as date
    r_date = Recur(freq=Frequency.DAILY, until=datetime.date(2026, 8, 30))
    event1 = Event(
        dtstamp=FIXED_DTSTAMP,
        uid="recur-until-date",
        dtstart=datetime.date(2026, 8, 24),
        rrule=r_date,
    )
    jcal1 = event1.as_jcal()
    assert json.dumps(jcal1)
    rrule_prop1 = [p for p in jcal1[1] if p[0] == "rrule"][0]
    assert rrule_prop1[3]["until"] == "2026-08-30"

    event1_reparsed = Event.from_jcal(jcal1)
    assert event1_reparsed.rrule is not None
    assert event1_reparsed.rrule.until == datetime.date(2026, 8, 30)

    # Until as date-time
    r_dt = Recur(
        freq=Frequency.DAILY,
        until=datetime.datetime(2026, 8, 30, 12, 0, 0, tzinfo=datetime.timezone.utc),
    )
    event2 = Event(
        dtstamp=FIXED_DTSTAMP,
        uid="recur-until-dt",
        dtstart=datetime.datetime(2026, 8, 24, 9, 0, 0, tzinfo=datetime.timezone.utc),
        rrule=r_dt,
    )
    jcal2 = event2.as_jcal()
    assert json.dumps(jcal2)
    rrule_prop2 = [p for p in jcal2[1] if p[0] == "rrule"][0]
    assert rrule_prop2[3]["until"] == "2026-08-30T12:00:00Z"

    event2_reparsed = Event.from_jcal(jcal2)
    assert event2_reparsed.rrule is not None
    assert event2_reparsed.rrule.until == datetime.datetime(
        2026, 8, 30, 12, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_jcal_recurrence_id_handling() -> None:
    """Test jCal recurrence-id roundtrip and to_value conversions."""
    rec_id = RecurrenceId(
        "20260824T090000",
        tzinfo=datetime.timezone.utc,
        range=Range.THIS_AND_FUTURE,
    )
    event = Event(
        dtstamp=FIXED_DTSTAMP,
        uid="event-rec-id",
        dtstart=datetime.datetime(2026, 8, 24, 9, 0, 0, tzinfo=datetime.timezone.utc),
        recurrence_id=rec_id,
    )
    jcal_data = event.as_jcal()
    assert json.dumps(jcal_data)

    rec_prop = [p for p in jcal_data[1] if p[0] == "recurrence-id"][0]
    assert rec_prop[1] == {"range": "THISANDFUTURE"}
    assert rec_prop[3] == "2026-08-24T09:00:00Z"

    reparsed = Event.from_jcal(jcal_data)
    assert reparsed.recurrence_id is not None
    assert reparsed.recurrence_id.range == Range.THIS_AND_FUTURE
    assert RecurrenceId.to_value(reparsed.recurrence_id) == datetime.datetime(
        2026, 8, 24, 9, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_jcal_multi_value_and_enums() -> None:
    """Test exdate, rdate with period, request-status, and enums."""
    p1 = Period(
        start=datetime.datetime(2026, 8, 24, 9, 0, tzinfo=datetime.timezone.utc),
        duration=datetime.timedelta(hours=1),
    )
    event = Event(
        dtstamp=FIXED_DTSTAMP,
        uid="event-mv-1",
        dtstart=datetime.datetime(2026, 8, 24, 9, 0, tzinfo=datetime.timezone.utc),
        status=EventStatus.CONFIRMED,
        priority=Priority(1),
        exdate=[
            datetime.date(2026, 8, 25),
            datetime.date(2026, 8, 26),
        ],
        rdate=[p1],
        request_status=[RequestStatus(statcode=2.0, statdesc="Success")],
    )

    jcal_event = event.as_jcal()
    assert json.dumps(jcal_event)

    reparsed_event = Event.from_jcal(jcal_event)
    assert reparsed_event.status == EventStatus.CONFIRMED
    assert reparsed_event.priority == 1
    assert reparsed_event.exdate == [
        datetime.date(2026, 8, 25),
        datetime.date(2026, 8, 26),
    ]
    assert len(reparsed_event.rdate) == 1
    assert isinstance(reparsed_event.rdate[0], Period)
    assert reparsed_event.rdate[0].duration == datetime.timedelta(hours=1)
    assert len(reparsed_event.request_status) == 1
    assert reparsed_event.request_status[0].statcode == 2.0
    assert reparsed_event.request_status[0].statdesc == "Success"

    # Test Todo and Journal
    todo = Todo(
        dtstamp=FIXED_DTSTAMP,
        uid="todo-1",
        summary="Task",
        status=TodoStatus.COMPLETED,
        percent=75,
    )
    jcal_todo = todo.as_jcal()
    assert json.dumps(jcal_todo)
    reparsed_todo = Todo.from_jcal(jcal_todo)
    assert reparsed_todo.status == TodoStatus.COMPLETED
    assert reparsed_todo.percent == 75

    journal = Journal(
        dtstamp=FIXED_DTSTAMP,
        uid="journal-1",
        summary="Note",
        status=JournalStatus.FINAL,
    )
    jcal_journal = journal.as_jcal()
    assert json.dumps(jcal_journal)
    reparsed_journal = Journal.from_jcal(jcal_journal)
    assert reparsed_journal.status == JournalStatus.FINAL


def test_jcal_binary_attachment_and_image() -> None:
    """Test binary content encoding and decoding for Attachment and Image."""
    att = Attachment(content=b"hello binary attachment", fmttype="text/plain")
    img = Image(
        content=b"\x89PNG\r\n\x1a\nfakeimage",
        format_type="image/png",
        display=Display.BADGE,
    )
    event = Event(
        dtstamp=FIXED_DTSTAMP,
        uid="event-binary-1",
        summary="Binary Event",
        attach=[att],
        image=[img],
    )
    jcal = event.as_jcal()
    assert json.dumps(jcal)

    # Verify property types are binary in jCal
    attach_prop = [p for p in jcal[1] if p[0] == "attach"][0]
    assert attach_prop[2] == "binary"
    assert attach_prop[1] == {"fmttype": "text/plain"}

    image_prop = [p for p in jcal[1] if p[0] == "image"][0]
    assert image_prop[2] == "binary"
    assert image_prop[1] == {"fmttype": "image/png", "display": "BADGE"}

    # Reparse and verify content bytes
    reparsed = Event.from_jcal(jcal)
    assert len(reparsed.attach) == 1
    assert reparsed.attach[0].content == b"hello binary attachment"
    assert reparsed.attach[0].fmttype == "text/plain"

    assert len(reparsed.image) == 1
    assert reparsed.image[0].content == b"\x89PNG\r\n\x1a\nfakeimage"
    assert reparsed.image[0].format_type == "image/png"
    assert reparsed.image[0].display == Display.BADGE


def test_jcal_caladdress_and_conference_scalar_params() -> None:
    """Test CalAddress and Conference parameter handling from jCal dicts."""
    jcal_input = [
        "vevent",
        [
            ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
            ["uid", {}, "text", "event-params-1"],
            ["summary", {}, "text", "Params Event"],
            [
                "attendee",
                {"delegated-from": "mailto:boss@example.com", "cn": "Alice"},
                "cal-address",
                "mailto:alice@example.com",
            ],
            [
                "conference",
                {"feature": "AUDIO", "label": "Call Link"},
                "uri",
                "https://meet.example.com/room",
            ],
        ],
        [],
    ]

    event = Event.from_jcal(jcal_input)
    assert len(event.attendees) == 1
    assert event.attendees[0].common_name == "Alice"
    assert event.attendees[0].delegator == [Uri("mailto:boss@example.com")]

    assert len(event.conference) == 1
    assert event.conference[0].label == "Call Link"
    assert event.conference[0].feature is not None
    assert event.conference[0].feature[0].value == "AUDIO"


def test_jcal_period_variations_and_freebusy() -> None:
    """Test Period parsing from slash strings and FreeBusy components."""
    # Test Period from slash string
    p1 = Period.__parse_jcal_value__(
        "2026-08-24T09:00:00Z/2026-08-24T10:00:00Z",
        {"fbtype": "busy"},
    )
    assert p1.start == datetime.datetime(
        2026, 8, 24, 9, 0, tzinfo=datetime.timezone.utc
    )
    assert p1.end == datetime.datetime(2026, 8, 24, 10, 0, tzinfo=datetime.timezone.utc)
    assert p1.free_busy_type == FreeBusyType.BUSY

    p2 = Period(
        start=datetime.datetime(2026, 8, 24, 13, 0, tzinfo=datetime.timezone.utc),
        duration=datetime.timedelta(hours=2),
        FBTYPE=FreeBusyType.BUSY_TENTATIVE,
    )

    fb = FreeBusy(
        dtstart=datetime.datetime(2026, 8, 24, 9, 0, tzinfo=datetime.timezone.utc),
        dtend=datetime.datetime(2026, 8, 24, 17, 0, tzinfo=datetime.timezone.utc),
        freebusy=[p1, p2],
    )
    cal = Calendar(freebusy=[fb])
    jcal = cal.as_jcal()
    assert json.dumps(jcal)

    cal_reparsed = Calendar.from_jcal(jcal)
    assert len(cal_reparsed.freebusy) == 1
    assert len(cal_reparsed.freebusy[0].freebusy) == 2


def test_jcal_alarm_subcomponents() -> None:
    """Test relative and absolute VALARM subcomponents in jCal."""
    alarm_rel = Alarm(
        action=Action.DISPLAY,
        description="Meeting soon",
        trigger=-datetime.timedelta(minutes=15),
    )
    alarm_abs = Alarm(
        action=Action.DISPLAY,
        description="Meeting now",
        trigger=datetime.datetime(2026, 8, 24, 8, 45, tzinfo=datetime.timezone.utc),
    )
    event = Event(
        dtstamp=FIXED_DTSTAMP,
        uid="event-alarms",
        summary="Event with Alarms",
        alarm=[alarm_rel, alarm_abs],
    )

    jcal = event.as_jcal()
    assert json.dumps(jcal)
    assert len(jcal[2]) == 2
    assert jcal[2][0][0] == "valarm"
    assert jcal[2][1][0] == "valarm"

    reparsed = Event.from_jcal(jcal)
    assert len(reparsed.alarm) == 2
    assert reparsed.alarm[0].trigger == -datetime.timedelta(minutes=15)
    assert reparsed.alarm[0].description == "Meeting soon"
    assert reparsed.alarm[1].trigger == datetime.datetime(
        2026, 8, 24, 8, 45, tzinfo=datetime.timezone.utc
    )
