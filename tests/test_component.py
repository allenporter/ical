"""Tests for component encoding and decoding."""

from pydantic import field_serializer
import pytest
import datetime
import logging
import zoneinfo
from typing import Optional, Union

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.component import ComponentModel
from ical.event import Event
from ical.exceptions import CalendarParseError, ParameterValueError
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types import Frequency, Period, Recur
from ical.types.data_types import serialize_field


def test_encode_component() -> None:
    """Test for a text property value."""

    class OtherComponent(ComponentModel):
        """Model used as a sub-component."""

        other_value: str
        second_value: Optional[str] = None

    class TestModel(ComponentModel):
        """Model with a Text value."""

        text_value: str
        repeated_text_value: list[str]
        some_component: list[OtherComponent]
        single_component: OtherComponent
        dt: datetime.datetime

        serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]

    model = TestModel.model_validate(
        {
            "text_value": "Example text",
            "repeated_text_value": ["a", "b", "c"],
            "some_component": [
                {"other_value": "value1", "second_value": "valuez"},
                {"other_value": "value2"},
            ],
            "single_component": {
                "other_value": "value3",
            },
            "dt": [ParsedProperty(name="dt", value="20220724T120000")],
        }
    )
    component = model.__encode_component_root__()
    assert component.name == "TestModel"
    assert component.properties == [
        ParsedProperty(name="text_value", value="Example text"),
        ParsedProperty(name="repeated_text_value", value="a"),
        ParsedProperty(name="repeated_text_value", value="b"),
        ParsedProperty(name="repeated_text_value", value="c"),
        ParsedProperty(name="dt", value="20220724T120000"),
    ]
    assert component.components == [
        ParsedComponent(
            name="some_component",
            properties=[
                ParsedProperty(name="other_value", value="value1"),
                ParsedProperty(name="second_value", value="valuez"),
            ],
        ),
        ParsedComponent(
            name="some_component",
            properties=[
                ParsedProperty(name="other_value", value="value2"),
            ],
        ),
        ParsedComponent(
            name="single_component",
            properties=[
                ParsedProperty(name="other_value", value="value3"),
            ],
        ),
    ]


def test_list_parser() -> None:
    """Test for a repeated property value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: list[datetime.datetime]

    model = TestModel.model_validate(
        {
            "dt": [
                ParsedProperty(name="dt", value="20220724T120000"),
                ParsedProperty(name="dt", value="20220725T130000"),
            ],
        }
    )
    assert model.dt == [
        datetime.datetime(2022, 7, 24, 12, 0, 0),
        datetime.datetime(2022, 7, 25, 13, 0, 0),
    ]


def test_list_union_parser() -> None:
    """Test for a repeated union value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: list[Union[datetime.datetime, datetime.date]]

    model = TestModel.model_validate(
        {
            "dt": [
                ParsedProperty(name="dt", value="20220724T120000"),
                ParsedProperty(name="dt", value="20220725"),
            ],
        }
    )
    assert model.dt == [
        datetime.datetime(2022, 7, 24, 12, 0, 0),
        datetime.date(2022, 7, 25),
    ]


def test_optional_field_parser() -> None:
    """Test for an optional field parser."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: Optional[datetime.datetime] = None

    model = TestModel.model_validate(
        {"dt": [ParsedProperty(name="dt", value="20220724T120000")]}
    )
    assert model.dt == datetime.datetime(2022, 7, 24, 12, 0, 0)


def test_union_parser() -> None:
    """Test for a union value."""

    class TestModel(ComponentModel):
        """Model under test."""

        dt: Union[datetime.datetime, datetime.date]

    with pytest.raises(CalendarParseError, match=".*Expected one value for field: dt"):
        model = TestModel.model_validate(
            {
                "dt": [
                    ParsedProperty(name="dt", value="20220724T120000"),
                    ParsedProperty(name="dt", value="20220725"),
                ],
            },
        )

    model = TestModel.model_validate(
        {
            "dt": [
                ParsedProperty(name="dt", value="20220724T120000"),
            ],
        }
    )
    assert model.dt == datetime.datetime(2022, 7, 24, 12, 0, 0)

    model = TestModel.model_validate(
        {
            "dt": [
                ParsedProperty(name="dt", value="20220725"),
            ],
        }
    )
    assert model.dt == datetime.date(2022, 7, 25)

    model = TestModel.model_validate(
        {
            "dt": [
                ParsedProperty(
                    name="dt",
                    value="20220724T120000",
                    params=[ParsedPropertyParameter("TZID", ["America/New_York"])],
                ),
            ],
        }
    )
    assert model.dt == datetime.datetime(
        2022, 7, 24, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="America/New_York")
    )
    assert model.dt != datetime.datetime(2022, 7, 24, 12, 0, 0)

    with pytest.raises(
        CalendarParseError,
        match="Expected DATE-TIME TZID value 'America/New_Mork' to be valid timezone.*",
    ):
        model = TestModel.model_validate(
            {
                "dt": [
                    ParsedProperty(
                        name="dt",
                        value="20220724T120000",
                        params=[ParsedPropertyParameter("TZID", ["America/New_Mork"])],
                    ),
                ],
            }
        )

    with pytest.raises(
        CalendarParseError,
        match=".*The calendar is not valid: Failed to parse TESTMODEL component: Value error, Failed to validate '2025NotADateOrADateTime' as datetime or date: Expected value to match DATE-TIME pattern: .*Expected value to match DATE pattern: .*",
    ):
        model = TestModel.model_validate(
            {
                "dt": [
                    ParsedProperty(name="dt", value="2025NotADateOrADateTime"),
                ],
            }
        )


def test_unknown_value_type_proton_mail_example() -> None:
    """Test the real-world Proton Mail example from issue #567."""

    class TestModel(ComponentModel):
        """Model under test."""

        summary: str

    # Use the actual failing case from Proton Mail
    model = TestModel.model_validate(
        {
            "summary": [
                ParsedProperty(
                    name="summary",
                    value="IBE150 NAME NAMESON\\n A285\\n",
                    params=[
                        ParsedPropertyParameter(
                            "VALUE", ["IBE150 NAME NAMESON^n A285^n"]
                        )
                    ],
                ),
            ],
        }
    )
    assert model.summary == "IBE150 NAME NAMESON\n A285\n"


def test_multiple_unknown_value_types() -> None:
    """Test handling of multiple properties with unknown VALUE types."""

    class TestModel(ComponentModel):
        """Model under test."""

        summary: str
        description: str

    model = TestModel.model_validate(
        {
            "summary": [
                ParsedProperty(
                    name="summary",
                    value="Test summary",
                    params=[ParsedPropertyParameter("VALUE", ["CUSTOM-TYPE-1"])],
                ),
            ],
            "description": [
                ParsedProperty(
                    name="description",
                    value="Test description",
                    params=[ParsedPropertyParameter("VALUE", ["CUSTOM-TYPE-2"])],
                ),
            ],
        }
    )
    assert model.summary == "Test summary"
    assert model.description == "Test description"


def test_unknown_value_type_text_escaping() -> None:
    """Test that TEXT escape sequences are properly handled in fallback."""

    class TestModel(ComponentModel):
        """Model under test."""

        summary: str

    model = TestModel.model_validate(
        {
            "summary": [
                ParsedProperty(
                    name="summary",
                    value="Line 1\\nLine 2\\;semicolon\\,comma\\\\backslash",
                    params=[ParsedPropertyParameter("VALUE", ["X-CUSTOM"])],
                ),
            ],
        }
    )
    assert model.summary == "Line 1\nLine 2;semicolon,comma\\backslash"


def test_unknown_value_type_warning_logged(caplog) -> None:
    """Test that a warning is logged when encountering unknown VALUE types."""

    class TestModel(ComponentModel):
        """Model under test."""

        summary: str

    with caplog.at_level(logging.DEBUG):
        model = TestModel.model_validate(
            {
                "summary": [
                    ParsedProperty(
                        name="summary",
                        value="Test",
                        params=[ParsedPropertyParameter("VALUE", ["UNKNOWN-TYPE"])],
                    ),
                ],
            }
        )

    assert model.summary == "Test"
    # Check that debug log was logged
    assert any(
        "unsupported VALUE type" in record.message and "UNKNOWN-TYPE" in record.message
        for record in caplog.records
    )
    assert any("falling back to TEXT" in record.message for record in caplog.records)


def test_rdate_tzid_does_not_inject_value_period() -> None:
    """Test that RDATE with a TZID datetime does not inject VALUE=PERIOD on serialization."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    event = Event(
        uid="rdate-tzid-test",
        dtstamp=datetime.datetime(2022, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
        dtstart=datetime.datetime(2022, 1, 1, 9, 0, 0, tzinfo=tz),
        dtend=datetime.datetime(2022, 1, 1, 10, 0, 0, tzinfo=tz),
        summary="Meeting",
        rdate=[datetime.datetime(2022, 1, 5, 9, 0, 0, tzinfo=tz)],
    )
    cal = Calendar(events=[event])
    ics_text = IcsCalendarStream.calendar_to_ics(cal)
    assert "VALUE=PERIOD" not in ics_text
    assert "RDATE;TZID=America/New_York:20220105T090000" in ics_text

    parsed = IcsCalendarStream.calendar_from_ics(ics_text)
    assert parsed.events[0].rdate == [datetime.datetime(2022, 1, 5, 9, 0, 0, tzinfo=tz)]


def test_event_rrule_and_period_rdate_validation() -> None:
    """Test that combining rrule and Period in rdate validates and expands on datetime events, and rejects Period on all-day events."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    p = Period(
        start=datetime.datetime(2022, 1, 5, 14, 0, 0, tzinfo=tz),
        duration=datetime.timedelta(hours=2),
    )
    event = Event(
        dtstart=datetime.datetime(2022, 1, 1, 9, 0, 0, tzinfo=tz),
        dtend=datetime.datetime(2022, 1, 1, 10, 0, 0, tzinfo=tz),
        rrule=Recur.from_rrule("FREQ=DAILY;COUNT=2"),
        rdate=[p, datetime.date(2022, 1, 6)],
    )
    assert event.rdate[0] == p
    assert event.rdate[1] == datetime.datetime(2022, 1, 6, 9, 0, 0, tzinfo=tz)
    rrule_iter = event.as_rrule()
    assert rrule_iter is not None
    assert list(rrule_iter) == [
        datetime.datetime(2022, 1, 1, 9, 0, 0, tzinfo=tz),
        datetime.datetime(2022, 1, 2, 9, 0, 0, tzinfo=tz),
        datetime.datetime(2022, 1, 5, 14, 0, 0, tzinfo=tz),
        datetime.datetime(2022, 1, 6, 9, 0, 0, tzinfo=tz),
    ]

    with pytest.raises(
        CalendarParseError,
        match="RDATE PERIOD values are not supported when DTSTART is a DATE",
    ):
        Event(
            dtstart=datetime.date(2022, 1, 1),
            dtend=datetime.date(2022, 1, 2),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=2"),
            rdate=[p],
        )

    # Even without rrule, Period in rdate on an all-day event is rejected
    with pytest.raises(
        CalendarParseError,
        match="RDATE PERIOD values are not supported when DTSTART is a DATE",
    ):
        Event(
            dtstart=datetime.date(2022, 1, 1),
            dtend=datetime.date(2022, 1, 2),
            rdate=[p],
        )

    # Naive Period in rdate against timezone-aware dtstart is aligned to dtstart.tzinfo
    naive_period = Period(
        start=datetime.datetime(2022, 1, 5, 14, 0, 0),
        end=datetime.datetime(2022, 1, 5, 16, 0, 0),
    )
    aware_event = Event(
        dtstart=datetime.datetime(2022, 1, 1, 9, 0, 0, tzinfo=tz),
        dtend=datetime.datetime(2022, 1, 1, 10, 0, 0, tzinfo=tz),
        rrule=Recur.from_rrule("FREQ=DAILY;COUNT=2"),
        rdate=[naive_period],
    )
    aligned_period = aware_event.rdate[0]
    assert isinstance(aligned_period, Period)
    assert aligned_period.start == datetime.datetime(2022, 1, 5, 14, 0, 0, tzinfo=tz)
    assert aligned_period.end == datetime.datetime(2022, 1, 5, 16, 0, 0, tzinfo=tz)
    aware_iter = aware_event.as_rrule()
    assert aware_iter is not None
    assert list(aware_iter) == [
        datetime.datetime(2022, 1, 1, 9, 0, 0, tzinfo=tz),
        datetime.datetime(2022, 1, 2, 9, 0, 0, tzinfo=tz),
        datetime.datetime(2022, 1, 5, 14, 0, 0, tzinfo=tz),
    ]

    # Without rrule, date in rdate on a datetime event is coerced to datetime
    rdate_only_event = Event(
        dtstart=datetime.datetime(2022, 1, 1, 9, 0, 0, tzinfo=tz),
        dtend=datetime.datetime(2022, 1, 1, 10, 0, 0, tzinfo=tz),
        rdate=[datetime.date(2022, 1, 6)],
    )
    assert rdate_only_event.rdate == [datetime.datetime(2022, 1, 6, 9, 0, 0, tzinfo=tz)]


def test_validate_until_dtstart_does_not_mutate_shared_recur() -> None:
    """Test that validate_until_dtstart copies Recur before adjusting until."""
    shared_rule = Recur(
        freq=Frequency.DAILY,
        until=datetime.datetime(2022, 1, 10, 0, 0, 0, tzinfo=datetime.timezone.utc),
    )
    ev = Event(
        dtstart=datetime.date(2022, 1, 1),
        dtend=datetime.date(2022, 1, 2),
        rrule=shared_rule,
    )
    assert ev.rrule is not None
    assert ev.rrule.until == datetime.date(2022, 1, 10)
    assert isinstance(shared_rule.until, datetime.datetime)


_UTC = datetime.timezone.utc


def _event_ics(dtstart: str, recurrence: str) -> str:
    """Build a calendar holding a single recurring event."""
    return f"""BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:1
{dtstart}
{recurrence}
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
"""


_TODO_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VTODO
DTSTAMP:20250715T100000Z
UID:1
SUMMARY:Water the plants
DTSTART:20250715T140000Z
DUE:20250715T150000Z
RRULE:FREQ=DAILY;UNTIL={until}
END:VTODO
END:VCALENDAR
"""


def _until(calendar: Calendar) -> datetime.datetime | datetime.date:
    """Read UNTIL off the first event, asserting the rule survived parsing."""
    rrule = calendar.events[0].rrule
    assert rrule is not None
    assert rrule.until is not None
    return rrule.until


def _occurrences(calendar: Calendar) -> list[datetime.datetime | datetime.date]:
    """Expand the first month of the calendar."""
    return [
        event.start
        for event in calendar.timeline.included(
            datetime.datetime(2025, 7, 1, tzinfo=_UTC),
            datetime.datetime(2025, 8, 1, tzinfo=_UTC),
        )
    ]


def test_naive_until_against_utc_dtstart() -> None:
    """rfc5545 3.3.10 requires UNTIL in UTC when DTSTART is timezone-aware.

    A naive UNTIL used to validate cleanly and then fail much later, inside
    the recurrence iterator, with an error naming neither event nor rule.
    Under a UTC DTSTART it is read as UTC.
    """
    calendar = IcsCalendarStream.calendar_from_ics(
        _event_ics("DTSTART:20250715T140000Z", "RRULE:FREQ=DAILY;UNTIL=20250718T140000")
    )

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=_UTC)
    assert len(_occurrences(calendar)) == 4


def test_naive_until_against_a_tzid_dtstart() -> None:
    """A floating UNTIL is the same wall-clock time as a TZID DTSTART."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _event_ics(
            "DTSTART;TZID=America/Denver:20250715T140000",
            "RRULE:FREQ=DAILY;UNTIL=20250718T140000",
        )
    )

    # 14:00 in Denver (MDT, UTC-6) is 20:00 UTC; the last day is kept
    assert _until(calendar) == datetime.datetime(2025, 7, 18, 20, 0, tzinfo=_UTC)
    assert len(_occurrences(calendar)) == 4


def test_naive_until_on_a_todo_as_well() -> None:
    """`validate_until_dtstart` is shared by VEVENT, VTODO and VJOURNAL."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _TODO_ICS.format(until="20250718T140000")
    )

    rrule = calendar.todos[0].rrule
    assert rrule is not None
    assert rrule.until == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=_UTC)


def test_a_conforming_until_is_untouched() -> None:
    """The valid case has to keep working, or this trades one break for another."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _event_ics(
            "DTSTART:20250715T140000Z", "RRULE:FREQ=DAILY;UNTIL=20250718T140000Z"
        )
    )

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=_UTC)
    assert len(_occurrences(calendar)) == 4


def test_a_floating_dtstart_still_takes_a_floating_until() -> None:
    """Both naive is the other legal combination, and must not be caught."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _event_ics("DTSTART:20250715T140000", "RRULE:FREQ=DAILY;UNTIL=20250718T140000")
    )

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0)


def _recur_date_calendar(dtstart: str, recur_date: str) -> Calendar:
    return IcsCalendarStream.calendar_from_ics(
        _event_ics(dtstart, f"RRULE:FREQ=DAILY;COUNT=3\n{recur_date}")
    )


def test_a_naive_exdate_against_an_aware_dtstart_still_excludes() -> None:
    """It raised RecurrenceError out of the iterator instead of excluding."""
    calendar = _recur_date_calendar(
        "DTSTART:20250715T140000Z", "EXDATE:20250716T140000"
    )

    assert _occurrences(calendar) == [
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=_UTC),
        datetime.datetime(2025, 7, 17, 14, 0, tzinfo=_UTC),
    ]


def test_a_naive_exdate_against_a_tzid_dtstart() -> None:
    """A TZID reference is aware too, so it hit the same failure."""
    calendar = _recur_date_calendar(
        "DTSTART;TZID=America/Denver:20250715T140000", "EXDATE:20250716T140000"
    )

    denver = zoneinfo.ZoneInfo("America/Denver")
    assert _occurrences(calendar) == [
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=denver),
        datetime.datetime(2025, 7, 17, 14, 0, tzinfo=denver),
    ]


def test_a_naive_rdate_against_an_aware_dtstart_still_adds() -> None:
    """RDATE took the whole expansion down the same way EXDATE did."""
    calendar = _recur_date_calendar("DTSTART:20250715T140000Z", "RDATE:20250720T140000")

    assert datetime.datetime(2025, 7, 20, 14, 0, tzinfo=_UTC) in _occurrences(calendar)


def test_a_conforming_exdate_is_untouched() -> None:
    """Matching awareness must not be rewritten."""
    calendar = _recur_date_calendar(
        "DTSTART:20250715T140000Z", "EXDATE:20250716T140000Z"
    )

    assert _occurrences(calendar) == [
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=_UTC),
        datetime.datetime(2025, 7, 17, 14, 0, tzinfo=_UTC),
    ]


def test_an_exdate_in_another_zone_still_matches_by_instant() -> None:
    """A different TZID is legal and already worked; it compares absolutely."""
    calendar = _recur_date_calendar(
        "DTSTART:20250715T140000Z", "EXDATE;TZID=America/Denver:20250716T080000"
    )

    assert len(_occurrences(calendar)) == 2


def test_an_aware_recurrence_date_against_a_floating_dtstart_keeps_its_offset() -> None:
    """The mirror case already expanded correctly and must not be rewritten.

    Aligning it too would drop the offset, so an EXDATE naming a zone and an
    RDATE in UTC would both come back out as floating times -- a different
    instant than the producer wrote, and a silent change on round trip.
    """
    ics = _event_ics(
        "DTSTART:20250715T140000",
        "RRULE:FREQ=DAILY;COUNT=3\n"
        "EXDATE;TZID=America/Denver:20250716T140000\n"
        "RDATE:20250725T190000Z",
    )

    event = IcsCalendarStream.calendar_from_ics(ics).events[0]
    assert event.exdate == [
        datetime.datetime(
            2025, 7, 16, 14, 0, tzinfo=zoneinfo.ZoneInfo("America/Denver")
        )
    ]
    assert event.rdate == [datetime.datetime(2025, 7, 25, 19, 0, tzinfo=_UTC)]

    output = IcsCalendarStream.calendar_to_ics(IcsCalendarStream.calendar_from_ics(ics))
    assert "EXDATE;TZID=America/Denver:20250716T140000" in output
    assert "RDATE:20250725T190000Z" in output


# Real-world shapes from Home Assistant issues: each producer below writes a
# recurrence that rfc5545 doesn't allow, and each must still expand.


def test_date_until_keeps_the_occurrence_on_that_day() -> None:
    """Google Calendar writes UNTIL as a DATE under a DATE-TIME DTSTART.

    Read as midnight, UNTIL fell before the 14:00 occurrence on the last day
    and silently dropped it.
    """
    calendar = IcsCalendarStream.calendar_from_ics(
        _event_ics("DTSTART:20250715T140000Z", "RRULE:FREQ=DAILY;UNTIL=20250718")
    )

    assert _occurrences(calendar) == [
        datetime.datetime(2025, 7, day, 14, 0, tzinfo=_UTC) for day in range(15, 19)
    ]


def test_date_until_against_a_tzid_dtstart() -> None:
    """The end of the UNTIL day is taken in DTSTART's zone, not in UTC."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _event_ics(
            "DTSTART;TZID=America/Denver:20250715T200000",
            "RRULE:FREQ=DAILY;UNTIL=20250718",
        )
    )

    # 20:00 in Denver is 02:00 UTC the next day: still on the 18th locally
    assert _until(calendar) == datetime.datetime(2025, 7, 19, 5, 59, 59, tzinfo=_UTC)
    assert len(_occurrences(calendar)) == 4


def test_x_wr_timezone_floating_until_and_exdate_list() -> None:
    """Evolution and Thunderbird exports: floating values under X-WR-TIMEZONE.

    DTSTART is promoted to the calendar's zone, while UNTIL (inside RRULE) and
    the second value of an EXDATE list were left floating, so the expansion
    raised instead of returning the series.
    """
    calendar = IcsCalendarStream.calendar_from_ics(
        """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
X-WR-TIMEZONE:America/Denver
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:1
DTSTART:20250715T140000
RRULE:FREQ=DAILY;UNTIL=20250718T140000
EXDATE:20250716T140000,20250717T140000
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
"""
    )

    denver = zoneinfo.ZoneInfo("America/Denver")
    assert _occurrences(calendar) == [
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=denver),
        datetime.datetime(2025, 7, 18, 14, 0, tzinfo=denver),
    ]
