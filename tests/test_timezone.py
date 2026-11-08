"""Tests for Free/Busy component."""

from __future__ import annotations

from collections.abc import Generator
import copy
import datetime
import inspect
import zoneinfo
from typing import Any

import pytest
from freezegun import freeze_time

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.exceptions import CalendarParseError
from ical.timezone import IcsTimezoneInfo, Observance, Timezone
from ical.types import UtcOffset
from ical.types.recur import Frequency, Recur, Weekday, WeekdayValue
from ical.tzif.timezoneinfo import TimezoneInfoError

TEST_RECUR = Recur(
    freq=Frequency.YEARLY,
    bymonth=[10],
    byday=[WeekdayValue(Weekday.SUNDAY, occurrence=-1)],
    until=datetime.datetime(2006, 10, 29, 6, 0, 0),
)


def test_requires_subcompnent() -> None:
    """Test Timezone constructor."""
    with pytest.raises(
        CalendarParseError, match=r"At least one standard or daylight.*"
    ):
        Timezone(tzid="America/New_York")


def test_daylight() -> None:
    """Test a Timezone object with a daylight observance."""
    timezone = Timezone(
        tzid="America/New_York",
        last_modified=datetime.datetime(2005, 8, 9, 5),
        daylight=[
            Observance(
                start=datetime.datetime(1967, 10, 29, 2, 0, 0, 0),
                tz_offset_to=UtcOffset(datetime.timedelta(hours=-4)),
                tz_offset_from=UtcOffset(datetime.timedelta(hours=-5)),
                tz_name=["edt"],
                rrule=TEST_RECUR,
            ),
        ],
    )
    assert len(timezone.daylight) == 1
    assert timezone.daylight[0].tz_name == ["edt"]

    tz_info = IcsTimezoneInfo.from_timezone(timezone)

    value = datetime.datetime(1967, 10, 29, 1, 59, 0, 0, tzinfo=tz_info)
    assert not tz_info.tzname(value)
    assert not tz_info.utcoffset(value)
    assert not tz_info.dst(value)

    value = datetime.datetime(1967, 10, 29, 2, 00, 0, 0, tzinfo=tz_info)
    assert tz_info.tzname(value) == "edt"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-4)
    assert tz_info.dst(value) == datetime.timedelta(hours=1)


def test_timezone_observence_start_time_validation() -> None:
    """Verify that a start time must be in local time."""
    with pytest.raises(
        CalendarParseError, match=r".*Start time must be in local time format*"
    ):
        Observance(
            start=datetime.datetime(1967, 10, 29, 2, tzinfo=datetime.timezone.utc),
            tz_offset_to=UtcOffset(datetime.timedelta(hours=-5)),
            tz_offset_from=UtcOffset(datetime.timedelta(hours=-4)),
            tz_name=["est"],
            rrule=TEST_RECUR,
        )


@freeze_time("2022-08-22 12:30:00")
def test_from_tzif_timezoneinfo_with_dst(
    mock_prodid: Generator[None, None, None],
) -> None:
    """Verify a timezone created from a tzif timezone info with DST information."""

    timezone = Timezone.from_tzif("America/New_York")

    calendar = Calendar()
    calendar.timezones.append(timezone)

    stream = IcsCalendarStream(vcalendar=[calendar])
    assert stream.ics() == inspect.cleandoc(
        """
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       TZID:America/New_York
       BEGIN:STANDARD
       DTSTART:20101107T020000
       TZOFFSETTO:-0500
       TZOFFSETFROM:-0400
       RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11
       TZNAME:EST
       END:STANDARD
       BEGIN:DAYLIGHT
       DTSTART:20100314T020000
       TZOFFSETTO:-0400
       TZOFFSETFROM:-0500
       RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3
       TZNAME:EDT
       END:DAYLIGHT
       END:VTIMEZONE
       END:VCALENDAR
    """
    )

    tz_info = IcsTimezoneInfo.from_timezone(timezone)

    value = datetime.datetime(2010, 11, 7, 1, 59, 0)
    assert tz_info.tzname(value) == "EDT"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-4)
    assert tz_info.dst(value) == datetime.timedelta(hours=1)

    value = datetime.datetime(2010, 11, 7, 2, 0, 0)
    assert tz_info.tzname(value) == "EST"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-5)
    assert tz_info.dst(value) == datetime.timedelta(hours=0)

    value = datetime.datetime(2011, 3, 13, 1, 59, 0)
    assert tz_info.tzname(value) == "EST"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-5)
    assert tz_info.dst(value) == datetime.timedelta(hours=0)

    value = datetime.datetime(2011, 3, 14, 2, 0, 0)
    assert tz_info.tzname(value) == "EDT"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-4)
    assert tz_info.dst(value) == datetime.timedelta(hours=1)


@freeze_time("2022-08-22 12:30:00")
def test_from_tzif_timezoneinfo_fixed_offset(
    mock_prodid: Generator[None, None, None],
) -> None:
    """Verify a timezone created from a tzif timezone info with a fixed offset"""

    timezone = Timezone.from_tzif("Asia/Tokyo")

    calendar = Calendar()
    calendar.timezones.append(timezone)

    stream = IcsCalendarStream(vcalendar=[calendar])
    assert stream.ics() == inspect.cleandoc(
        """
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       TZID:Asia/Tokyo
       BEGIN:STANDARD
       DTSTART:20100101T000000
       TZOFFSETTO:+0900
       TZOFFSETFROM:+0900
       TZNAME:JST
       END:STANDARD
       END:VTIMEZONE
       END:VCALENDAR
    """
    )


def test_invalid_tzif_key() -> None:
    """Test creating a timezone object from tzif data that does not exist."""

    with pytest.raises(TimezoneInfoError, match=r"Unable to find timezone"):
        Timezone.from_tzif("invalid")


@freeze_time("2022-08-22 12:30:00")
def test_clear_old_dtstamp(mock_prodid: Generator[None, None, None]) -> None:
    """Verify a timezone created from a tzif timezone info with a fixed offset"""

    stream = IcsCalendarStream.from_ics(
        inspect.cleandoc("""
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       DTSTAMP:20220822T123000
       TZID:Asia/Tokyo
       BEGIN:STANDARD
       DTSTART:20100101T000000
       TZOFFSETTO:+0900
       TZOFFSETFROM:+0900
       TZNAME:JST
       END:STANDARD
       END:VTIMEZONE
       END:VCALENDAR
    """)
    )
    # DTSTAMP is omitted from the output
    assert stream.ics() == inspect.cleandoc("""
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       TZID:Asia/Tokyo
       DTSTAMP:20220822T123000
       BEGIN:STANDARD
       DTSTART:20100101T000000
       TZOFFSETTO:+0900
       TZOFFSETFROM:+0900
       TZNAME:JST
       END:STANDARD
       END:VTIMEZONE
       END:VCALENDAR
    """)


def _customized_timezone() -> Timezone:
    """Build a Microsoft "Customized Time Zone" style embedded VTIMEZONE.

    These are emitted by Office 365/Exchange with the observance ``DTSTART`` in
    year 1601 and an unbounded ``YEARLY`` recurrence. They are kept as an
    embedded timezone (rather than mapped to a named ``TzInfo``), so offsets are
    resolved through ``Timezone.get_observance``.
    """
    last_sunday = [WeekdayValue(Weekday.SUNDAY, occurrence=-1)]
    return Timezone(
        tzid="Customized Time Zone",
        standard=[
            Observance(
                start=datetime.datetime(1601, 1, 1, 3, 0, 0),
                tz_offset_to=UtcOffset(datetime.timedelta(hours=1)),
                tz_offset_from=UtcOffset(datetime.timedelta(hours=2)),
                rrule=Recur(freq=Frequency.YEARLY, bymonth=[10], byday=last_sunday),
            ),
        ],
        daylight=[
            Observance(
                start=datetime.datetime(1601, 1, 1, 2, 0, 0),
                tz_offset_to=UtcOffset(datetime.timedelta(hours=2)),
                tz_offset_from=UtcOffset(datetime.timedelta(hours=1)),
                rrule=Recur(freq=Frequency.YEARLY, bymonth=[3], byday=last_sunday),
            ),
        ],
    )


def test_customized_timezone_observance_offsets() -> None:
    """Resolve offsets for a "Customized Time Zone" across repeated lookups.

    The observance recurrence starts in year 1601 with an unbounded yearly rule,
    so a single timezone is queried for many datetimes spanning multiple years
    (the Office 365 scenario behind allenporter/ical#593). Each lookup must
    return the correct observance: +02:00 in summer, +01:00 in winter.
    """
    timezone = _customized_timezone()

    for year in range(2020, 2027):
        summer = timezone.get_observance(datetime.datetime(year, 7, 15, 12, 0, 0))
        winter = timezone.get_observance(datetime.datetime(year, 1, 15, 12, 0, 0))
        assert summer is not None
        assert summer.observance.tz_offset_to.offset == datetime.timedelta(hours=2)
        assert winter is not None
        assert winter.observance.tz_offset_to.offset == datetime.timedelta(hours=1)


@pytest.mark.benchmark(min_rounds=1, warmup=False)
def test_benchmark_get_observance_repeated_calls(benchmark: Any) -> None:
    """Benchmark get_observance on a "Customized Time Zone" embedded VTIMEZONE.

    With the observance cache, repeated lookups are O(log n) over the cached
    transitions instead of re-expanding the (year 1601) recurrence each call.
    """
    timezone = _customized_timezone()
    dts = [
        datetime.datetime(2024 + (i % 2), 1 + (i % 12), 1 + (i % 28), 12, 0, 0)
        for i in range(1000)
    ]

    def lookup() -> int:
        for dt in dts:
            timezone.get_observance(dt)
        return len(dts)

    result = benchmark(lookup)
    assert result == len(dts)


def test_calendar_deepcopy() -> None:
    """Verify that a calendar can be deepcopied cleanly through the public API."""

    ics_content = """BEGIN:VCALENDAR
PRODID:-//Example Corp//Cal//EN
VERSION:2.0
BEGIN:VTIMEZONE
TZID:Custom Time Zone
BEGIN:STANDARD
DTSTART:16010101T020000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:event-1
SUMMARY:Test Event
DTSTART;TZID=Custom Time Zone:20241025T090000
DTEND;TZID=Custom Time Zone:20241025T100000
END:VEVENT
END:VCALENDAR"""

    calendar = IcsCalendarStream.calendar_from_ics(ics_content)
    # Trigger timeline/observance cache initialization
    events = list(calendar.timeline)
    assert len(events) == 1
    assert isinstance(events[0].dtstart, datetime.datetime)
    assert events[0].dtstart.tzinfo is not None

    # Deepcopy the calendar (which deepcopies the custom TzInfo and Timezone components)
    copied_calendar = copy.deepcopy(calendar)

    # Verify the copied calendar operates identically
    copied_events = list(copied_calendar.timeline)
    assert len(copied_events) == 1
    assert copied_events[0].summary == "Test Event"
    assert copied_events[0].dtstart == events[0].dtstart
    # Verify that the tzinfo of the copied event still works correctly
    assert isinstance(copied_events[0].dtstart, datetime.datetime)
    assert copied_events[0].dtstart.tzname() == events[0].dtstart.tzname()
    assert copied_events[0].dtstart.utcoffset() == events[0].dtstart.utcoffset()


@pytest.mark.parametrize(
    "key,spring_utc,fall_utc",
    [
        (
            "America/Los_Angeles",
            datetime.datetime(2023, 3, 12, 9, 0, tzinfo=datetime.UTC),
            datetime.datetime(2023, 11, 5, 8, 0, tzinfo=datetime.UTC),
        ),
        (
            "Australia/Sydney",
            datetime.datetime(2024, 10, 5, 15, 0, tzinfo=datetime.UTC),
            datetime.datetime(2024, 4, 6, 15, 0, tzinfo=datetime.UTC),
        ),
        (
            "Asia/Tokyo",
            datetime.datetime(2023, 3, 12, 0, 0, tzinfo=datetime.UTC),
            datetime.datetime(2023, 11, 5, 0, 0, tzinfo=datetime.UTC),
        ),
    ],
)
def test_ics_timezone_info_pep495_parity_with_zoneinfo(
    key: str,
    spring_utc: datetime.datetime,
    fall_utc: datetime.datetime,
) -> None:
    """Verify IcsTimezoneInfo matches ZoneInfo across folds, gaps, and fromutc()."""
    ics_tz = IcsTimezoneInfo.from_timezone(Timezone.from_tzif(key))
    zi = zoneinfo.ZoneInfo(key)

    for base_utc in (spring_utc, fall_utc):
        for step in range(16):
            u = base_utc + datetime.timedelta(minutes=15 * step)
            local_ics = u.astimezone(ics_tz)
            local_zi = u.astimezone(zi)
            assert local_ics.replace(tzinfo=None) == local_zi.replace(tzinfo=None)
            assert local_ics.fold == local_zi.fold
            assert local_ics.utcoffset() == local_zi.utcoffset()
            assert local_ics.dst() == local_zi.dst()
            assert local_ics.tzname() == local_zi.tzname()
            assert local_ics.astimezone(datetime.UTC) == u

            for fold in (0, 1):
                wall_naive = (
                    base_utc.replace(tzinfo=None)
                    + (local_zi.utcoffset() or datetime.timedelta(0))
                    + datetime.timedelta(minutes=15 * step - 60)
                )
                d_ics = wall_naive.replace(tzinfo=ics_tz, fold=fold)
                d_zi = wall_naive.replace(tzinfo=zi, fold=fold)
                assert d_ics.utcoffset() == d_zi.utcoffset()
                assert d_ics.dst() == d_zi.dst()
                assert d_ics.tzname() == d_zi.tzname()


def test_ics_timezone_info_first_transition_gap_and_fromutc_errors() -> None:
    """Verify pre-transition, first-transition gap/fold, duplicate onset, and fromutc validation."""
    ics_tz = IcsTimezoneInfo.from_timezone(Timezone.from_tzif("America/New_York"))
    # Before first transition (2010-03-14 02:00 EST -> 03:00 EDT), EST (-05:00) applies
    pre_utc = datetime.datetime(2010, 3, 14, 6, 30, tzinfo=datetime.UTC)
    pre_local = pre_utc.astimezone(ics_tz)
    assert pre_local.replace(tzinfo=None) == datetime.datetime(2010, 3, 14, 1, 30)
    assert pre_local.fold == 0
    assert pre_local.utcoffset() == datetime.timedelta(hours=-5)
    assert pre_local.astimezone(datetime.UTC) == pre_utc

    gap_fold0 = datetime.datetime(2010, 3, 14, 2, 30, tzinfo=ics_tz, fold=0)
    gap_fold1 = datetime.datetime(2010, 3, 14, 2, 30, tzinfo=ics_tz, fold=1)
    assert gap_fold0.utcoffset() == datetime.timedelta(hours=-5)
    assert gap_fold0.tzname() == "EST"
    assert gap_fold1.utcoffset() == datetime.timedelta(hours=-4)
    assert gap_fold1.tzname() == "EDT"

    # Southern Hemisphere first transition (2010-04-04 03:00 AEDT -> 02:00 AEST fall-back)
    syd_tz = IcsTimezoneInfo.from_timezone(Timezone.from_tzif("Australia/Sydney"))
    u0 = datetime.datetime(2010, 4, 3, 15, 30, tzinfo=datetime.UTC)
    u1 = datetime.datetime(2010, 4, 3, 16, 30, tzinfo=datetime.UTC)
    l0 = u0.astimezone(syd_tz)
    l1 = u1.astimezone(syd_tz)
    assert (l0.fold, l0.utcoffset()) == (0, datetime.timedelta(hours=11))
    assert (l1.fold, l1.utcoffset()) == (1, datetime.timedelta(hours=10))
    assert l0.astimezone(datetime.UTC) == u0
    assert l1.astimezone(datetime.UTC) == u1

    # Observance with RDATE only (no RRULE) and duplicate onset tie-breaking
    dup_tz = IcsTimezoneInfo.from_timezone(
        Timezone(
            tzid="Custom/RDate",
            standard=[
                Observance(
                    start=datetime.datetime(2023, 1, 1, 0, 0),
                    tz_offset_from=UtcOffset(datetime.timedelta(hours=1)),
                    tz_offset_to=UtcOffset(datetime.timedelta(hours=1)),
                    rdate=[datetime.datetime(2023, 10, 29, 3, 0)],
                ),
            ],
            daylight=[
                Observance(
                    start=datetime.datetime(2023, 1, 1, 0, 0),
                    tz_offset_from=UtcOffset(datetime.timedelta(hours=1)),
                    tz_offset_to=UtcOffset(datetime.timedelta(hours=2)),
                    rdate=[datetime.datetime(2023, 3, 26, 2, 0)],
                ),
            ],
        )
    )
    summer = datetime.datetime(2023, 7, 1, 10, 0, tzinfo=datetime.UTC).astimezone(
        dup_tz
    )
    winter = datetime.datetime(2023, 11, 1, 10, 0, tzinfo=datetime.UTC).astimezone(
        dup_tz
    )
    assert summer.utcoffset() == datetime.timedelta(hours=2)
    assert winter.utcoffset() == datetime.timedelta(hours=1)

    with pytest.raises(TypeError, match="datetime argument"):
        ics_tz.fromutc("2023-11-05")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="dt.tzinfo is not self"):
        ics_tz.fromutc(datetime.datetime(2023, 11, 5, 9, 0, tzinfo=datetime.UTC))


def test_custom_vtimezone_timeline_across_dst_fallback() -> None:
    """Verify Timeline & Timespan order fold=0/fold=1 events under an embedded custom VTIMEZONE."""
    ics_tz = IcsTimezoneInfo.from_timezone(_customized_timezone())
    # 2023-10-29 in Customized Time Zone: 03:00+02:00 falls back to 02:00+01:00
    ev_first = Event(
        summary="First (02:45+02)",
        start=datetime.datetime(2023, 10, 29, 2, 45, tzinfo=ics_tz, fold=0),
        end=datetime.datetime(2023, 10, 29, 2, 55, tzinfo=ics_tz, fold=0),
    )
    ev_second = Event(
        summary="Second (02:15+01)",
        start=datetime.datetime(2023, 10, 29, 2, 15, tzinfo=ics_tz, fold=1),
        end=datetime.datetime(2023, 10, 29, 2, 30, tzinfo=ics_tz, fold=1),
    )
    cal = Calendar(events=[ev_second, ev_first])
    tl = cal.timeline_tz(ics_tz)
    assert [e.summary for e in tl.on_date(datetime.date(2023, 10, 29))] == [
        "First (02:45+02)",
        "Second (02:15+01)",
    ]
    # Round-trip from UTC via IcsTimezoneInfo.fromutc sets fold=1 and queries accurately
    probe = datetime.datetime(2023, 10, 29, 1, 20, tzinfo=datetime.UTC).astimezone(
        ics_tz
    )
    assert probe.fold == 1
    assert [e.summary for e in tl.at_instant(probe)] == ["Second (02:15+01)"]
