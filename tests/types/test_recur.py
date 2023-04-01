"""Tests for timeline related calendar eents."""
from __future__ import annotations

import datetime
import zoneinfo

import pytest
from pydantic import ValidationError

from ical.calendar import Calendar
from ical.component import ComponentModel
from ical.event import Event
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.timeline import Timeline
from ical.types.recur import Frequency, Recur, RecurrenceId, Weekday, WeekdayValue


def recur_timeline(event: Event) -> Timeline:
    """Create a timeline for the specified recurring event."""
    calendar = Calendar()
    calendar.events.append(event)
    return calendar.timeline


class FakeModel(ComponentModel):
    """Model under test."""

    recurrence_id: RecurrenceId


def test_recurrence_id_datetime() -> None:
    """Test a recurrence id datetime field."""

    model = FakeModel.parse_obj(
        {
            "recurrence_id": [
                ParsedProperty(name="recurrence_id", value="20220724T120000")
            ]
        }
    )
    assert model.recurrence_id == "20220724T120000"


def test_recurrence_id_date() -> None:
    """Test a recurrence id date field."""

    model = FakeModel.parse_obj(
        {"recurrence_id": [ParsedProperty(name="recurrence_id", value="20220724")]}
    )
    assert model.recurrence_id == "20220724"


def test_recurrence_id_ignore_params() -> None:
    """Test property parameter values are ignored."""

    model = FakeModel.parse_obj(
        {
            "recurrence_id": [
                ParsedProperty(
                    name="recurrence_id",
                    value="20220724T120000",
                    params=[
                        ParsedPropertyParameter(name="RANGE", values=["THISANDFUTURE"]),
                    ],
                )
            ]
        }
    )
    assert model.recurrence_id == "20220724T120000"


def test_invalid_recurrence_id() -> None:
    """Test for a recurrence id that is not a valid DATE or DATE-TIME string."""
    model = FakeModel.parse_obj(
        {"recurrence_id": [ParsedProperty(name="recurrence_id", value="invalid")]}
    )
    assert model.recurrence_id == "invalid"


@pytest.mark.parametrize(
    "start,end,rrule,expected",
    [
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, until=datetime.date(2022, 8, 4)),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 2), datetime.date(2022, 8, 3)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
                (datetime.date(2022, 8, 4), datetime.date(2022, 8, 5)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, until=datetime.date(2022, 8, 4), interval=2),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, count=3),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 2), datetime.date(2022, 8, 3)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, interval=2, count=3),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
                (datetime.date(2022, 8, 5), datetime.date(2022, 8, 6)),
            ],
        ),
        (
            datetime.datetime(2022, 8, 1, 9, 30, 0),
            datetime.datetime(2022, 8, 1, 10, 0, 0),
            Recur(freq=Frequency.DAILY, until=datetime.datetime(2022, 8, 4, 9, 30, 0)),
            [
                (
                    datetime.datetime(2022, 8, 1, 9, 30, 0),
                    datetime.datetime(2022, 8, 1, 10, 0, 0),
                ),
                (
                    datetime.datetime(2022, 8, 2, 9, 30, 0),
                    datetime.datetime(2022, 8, 2, 10, 0, 0),
                ),
                (
                    datetime.datetime(2022, 8, 3, 9, 30, 0),
                    datetime.datetime(2022, 8, 3, 10, 0, 0),
                ),
                (
                    datetime.datetime(2022, 8, 4, 9, 30, 0),
                    datetime.datetime(2022, 8, 4, 10, 0, 0),
                ),
            ],
        ),
    ],
)
def test_day_iteration(
    start: datetime.datetime | datetime.date,
    end: datetime.datetime | datetime.date,
    rrule: Recur,
    expected: list[tuple[datetime.date, datetime.date]],
) -> None:
    """Test recurrence rules for day frequency."""
    event = Event(
        summary="summary",
        start=start,
        end=end,
        rrule=rrule,
    )
    timeline = recur_timeline(event)
    assert [(e.start, e.end) for e in timeline] == expected


@pytest.mark.parametrize(
    "start,end,rrule,expected",
    [
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY,
                until=datetime.date(2022, 9, 6),
                by_weekday=[WeekdayValue(Weekday.MONDAY)],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 8), datetime.date(2022, 8, 9)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
                (datetime.date(2022, 8, 22), datetime.date(2022, 8, 23)),
                (datetime.date(2022, 8, 29), datetime.date(2022, 8, 30)),
                (datetime.date(2022, 9, 5), datetime.date(2022, 9, 6)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY,
                until=datetime.date(2022, 9, 6),
                interval=2,
                by_weekday=[WeekdayValue(Weekday.MONDAY)],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
                (datetime.date(2022, 8, 29), datetime.date(2022, 8, 30)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY,
                count=3,
                by_weekday=[WeekdayValue(Weekday.MONDAY)],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 8), datetime.date(2022, 8, 9)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY,
                interval=2,
                count=3,
                by_weekday=[WeekdayValue(Weekday.MONDAY)],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
                (datetime.date(2022, 8, 29), datetime.date(2022, 8, 30)),
            ],
        ),
    ],
)
def test_weekly_iteration(
    start: datetime.date | datetime.date,
    end: datetime.date | datetime.date,
    rrule: Recur,
    expected: list[tuple[datetime.date, datetime.date]],
) -> None:
    """Test recurrence rules for weekly frequency."""
    event = Event(
        summary="summary",
        start=start,
        end=end,
        rrule=rrule,
    )
    timeline = recur_timeline(event)
    assert [(e.start, e.end) for e in timeline] == expected


@pytest.mark.parametrize(
    "start,end,rrule,expected",
    [
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.MONTHLY,
                until=datetime.date(2023, 1, 1),
                by_month_day=[1],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 9, 1), datetime.date(2022, 9, 2)),
                (datetime.date(2022, 10, 1), datetime.date(2022, 10, 2)),
                (datetime.date(2022, 11, 1), datetime.date(2022, 11, 2)),
                (datetime.date(2022, 12, 1), datetime.date(2022, 12, 2)),
                (datetime.date(2023, 1, 1), datetime.date(2023, 1, 2)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.MONTHLY,
                until=datetime.date(2023, 1, 1),
                interval=2,
                by_month_day=[1],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 10, 1), datetime.date(2022, 10, 2)),
                (datetime.date(2022, 12, 1), datetime.date(2022, 12, 2)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.MONTHLY, count=3, by_month_day=[1]),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 9, 1), datetime.date(2022, 9, 2)),
                (datetime.date(2022, 10, 1), datetime.date(2022, 10, 2)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.MONTHLY,
                interval=2,
                count=3,
                by_month_day=[1],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 10, 1), datetime.date(2022, 10, 2)),
                (datetime.date(2022, 12, 1), datetime.date(2022, 12, 2)),
            ],
        ),
        (
            datetime.datetime(2022, 8, 2, 9, 0, 0),
            datetime.datetime(2022, 8, 2, 9, 30, 0),
            Recur(
                freq=Frequency.MONTHLY,
                until=datetime.datetime(2023, 1, 1, 0, 0, 0),
                by_month_day=[2],
            ),
            [
                (
                    datetime.datetime(2022, 8, 2, 9, 0, 0),
                    datetime.datetime(2022, 8, 2, 9, 30, 0),
                ),
                (
                    datetime.datetime(2022, 9, 2, 9, 0, 0),
                    datetime.datetime(2022, 9, 2, 9, 30, 0),
                ),
                (
                    datetime.datetime(2022, 10, 2, 9, 0, 0),
                    datetime.datetime(2022, 10, 2, 9, 30, 0),
                ),
                (
                    datetime.datetime(2022, 11, 2, 9, 0, 0),
                    datetime.datetime(2022, 11, 2, 9, 30, 0),
                ),
                (
                    datetime.datetime(2022, 12, 2, 9, 0, 0),
                    datetime.datetime(2022, 12, 2, 9, 30, 0),
                ),
            ],
        ),
        (
            datetime.date(2022, 8, 7),
            datetime.date(2022, 8, 8),
            Recur(
                freq=Frequency.MONTHLY,
                interval=2,
                count=3,
                by_weekday=[WeekdayValue(weekday=Weekday.SUNDAY)],
            ),
            [
                (datetime.date(2022, 8, 7), datetime.date(2022, 8, 8)),
                (datetime.date(2022, 10, 2), datetime.date(2022, 10, 3)),
                (datetime.date(2022, 12, 4), datetime.date(2022, 12, 5)),
            ],
        ),
        (
            datetime.date(2022, 8, 7),
            datetime.date(2022, 8, 8),
            Recur(
                freq=Frequency.MONTHLY,
                count=3,
                by_weekday=[WeekdayValue(weekday=Weekday.SUNDAY, occurrence=-1)],
            ),
            [
                (datetime.date(2022, 8, 28), datetime.date(2022, 8, 29)),
                (datetime.date(2022, 9, 25), datetime.date(2022, 9, 26)),
                (datetime.date(2022, 10, 30), datetime.date(2022, 10, 31)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur.from_rrule("FREQ=MONTHLY;INTERVAL=2;COUNT=3;BYMONTHDAY=1"),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 10, 1), datetime.date(2022, 10, 2)),
                (datetime.date(2022, 12, 1), datetime.date(2022, 12, 2)),
            ],
        ),
    ],
)
def test_monthly_iteration(
    start: datetime.date | datetime.date,
    end: datetime.date | datetime.date,
    rrule: Recur,
    expected: list[tuple[datetime.date, datetime.date]],
) -> None:
    """Test recurrency rules for monthly frequency."""
    event = Event(
        summary="summary",
        start=start,
        end=end,
        rrule=rrule,
    )
    timeline = recur_timeline(event)
    assert [(e.start, e.end) for e in timeline] == expected


def test_recur_no_bound() -> None:
    """Test a recurrence rule with no end date."""

    event = Event(
        summary="summary",
        start=datetime.date(2022, 8, 1),
        end=datetime.date(2022, 8, 2),
        rrule=Recur(freq=Frequency.DAILY, interval=2),
    )
    timeline = recur_timeline(event)

    def on_date(day: datetime.date) -> list[datetime.date]:
        return [e.start for e in timeline.on_date(day)]

    assert on_date(datetime.date(2022, 8, 1)) == [datetime.date(2022, 8, 1)]
    assert on_date(datetime.date(2022, 8, 2)) == []
    assert on_date(datetime.date(2022, 8, 3)) == [datetime.date(2022, 8, 3)]

    assert on_date(datetime.date(2025, 1, 1)) == [datetime.date(2025, 1, 1)]
    assert on_date(datetime.date(2025, 1, 2)) == []
    assert on_date(datetime.date(2025, 1, 3)) == [datetime.date(2025, 1, 3)]

    assert on_date(datetime.date(2035, 9, 1)) == []
    assert on_date(datetime.date(2035, 9, 2)) == [datetime.date(2035, 9, 2)]
    assert on_date(datetime.date(2035, 9, 3)) == []


def test_merged_recur_event_timeline() -> None:
    """Test merged recurring and events timeline."""
    calendar = Calendar()
    calendar.events.extend(
        [
            Event(
                summary="Morning exercise",
                start=datetime.datetime(2022, 8, 2, 6, 0, 0),
                end=datetime.datetime(2022, 8, 2, 7, 0, 0),
                rrule=Recur(freq=Frequency.DAILY),
            ),
            Event(
                summary="Meeting",
                start=datetime.datetime(2022, 8, 2, 10, 0, 0),
                end=datetime.datetime(2022, 8, 2, 10, 30, 0),
            ),
            Event(
                summary="Trash day",
                start=datetime.date(2022, 8, 3),
                end=datetime.date(2022, 8, 4),
                rrule=Recur(
                    freq=Frequency.WEEKLY, by_weekday=[WeekdayValue(Weekday.WEDNESDAY)]
                ),
            ),
            Event(
                summary="Appointment",
                start=datetime.datetime(2022, 8, 5, 8, 0, 0),
                end=datetime.datetime(2022, 8, 5, 8, 30, 0),
            ),
            Event(
                summary="Pay day",
                start=datetime.date(2022, 8, 15),
                end=datetime.date(2022, 8, 16),
                rrule=Recur(freq=Frequency.MONTHLY, by_month_day=[15]),
            ),
        ]
    )
    events = calendar.timeline.included(
        datetime.date(2022, 8, 1),
        datetime.date(2022, 9, 2),
    )
    assert [(event.start, event.summary) for event in events] == [
        (datetime.datetime(2022, 8, 2, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 2, 10, 0, 0), "Meeting"),
        (datetime.date(2022, 8, 3), "Trash day"),
        (datetime.datetime(2022, 8, 3, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 4, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 5, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 5, 8, 0, 0), "Appointment"),
        (datetime.datetime(2022, 8, 6, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 7, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 8, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 9, 6, 0, 0), "Morning exercise"),
        (datetime.date(2022, 8, 10), "Trash day"),
        (datetime.datetime(2022, 8, 10, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 11, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 12, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 13, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 14, 6, 0, 0), "Morning exercise"),
        (datetime.date(2022, 8, 15), "Pay day"),
        (datetime.datetime(2022, 8, 15, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 16, 6, 0, 0), "Morning exercise"),
        (datetime.date(2022, 8, 17), "Trash day"),
        (datetime.datetime(2022, 8, 17, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 18, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 19, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 20, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 21, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 22, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 23, 6, 0, 0), "Morning exercise"),
        (datetime.date(2022, 8, 24), "Trash day"),
        (datetime.datetime(2022, 8, 24, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 25, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 26, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 27, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 28, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 29, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 30, 6, 0, 0), "Morning exercise"),
        (datetime.date(2022, 8, 31), "Trash day"),
        (datetime.datetime(2022, 8, 31, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 9, 1, 6, 0, 0), "Morning exercise"),
    ]


def test_exclude_date() -> None:
    """Test recurrence rule with date exclusions."""
    calendar = Calendar()
    calendar.events.extend(
        [
            Event(
                summary="Morning exercise",
                start=datetime.datetime(2022, 8, 2, 6, 0, 0),
                end=datetime.datetime(2022, 8, 2, 7, 0, 0),
                rrule=Recur(
                    freq=Frequency.DAILY, until=datetime.datetime(2022, 8, 10, 6, 0, 0)
                ),
                exdate=[
                    datetime.datetime(2022, 8, 3, 6, 0, 0),
                    datetime.datetime(2022, 8, 4, 6, 0, 0),
                    datetime.datetime(2022, 8, 6, 6, 0, 0),
                    datetime.datetime(2022, 8, 7, 6, 0, 0),
                ],
            ),
        ]
    )
    events = list(calendar.timeline)
    assert [(event.start, event.summary) for event in events] == [
        (datetime.datetime(2022, 8, 2, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 5, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 8, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 9, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 10, 6, 0, 0), "Morning exercise"),
    ]


def test_rdate() -> None:
    """Test recurrence rule with specific dates and exclusions."""
    calendar = Calendar()
    calendar.events.extend(
        [
            Event(
                summary="Morning exercise",
                start=datetime.datetime(2022, 8, 2, 6, 0, 0),
                end=datetime.datetime(2022, 8, 2, 7, 0, 0),
                rdate=[
                    datetime.datetime(2022, 8, 2, 6, 0, 0),
                    datetime.datetime(2022, 8, 3, 6, 0, 0),
                    datetime.datetime(2022, 8, 4, 6, 0, 0),
                    datetime.datetime(2022, 8, 5, 6, 0, 0),
                    datetime.datetime(2022, 8, 6, 6, 0, 0),
                    datetime.datetime(2022, 8, 7, 6, 0, 0),
                    datetime.datetime(2022, 8, 8, 6, 0, 0),
                    datetime.datetime(2022, 8, 9, 6, 0, 0),
                    datetime.datetime(2022, 8, 10, 6, 0, 0),
                ],
                exdate=[
                    datetime.datetime(2022, 8, 3, 6, 0, 0),
                    datetime.datetime(2022, 8, 4, 6, 0, 0),
                    datetime.datetime(2022, 8, 6, 6, 0, 0),
                    datetime.datetime(2022, 8, 7, 6, 0, 0),
                ],
            ),
        ]
    )
    events = list(calendar.timeline)
    assert [(event.start, event.summary) for event in events] == [
        (datetime.datetime(2022, 8, 2, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 5, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 8, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 9, 6, 0, 0), "Morning exercise"),
        (datetime.datetime(2022, 8, 10, 6, 0, 0), "Morning exercise"),
    ]


def test_year_iteration() -> None:
    """Test iteration with a yearly frequency."""
    calendar = Calendar()
    calendar.events.extend(
        [
            Event(
                summary="Bi-annual meeting",
                start=datetime.datetime(2022, 1, 2, 6, 0, 0),
                end=datetime.datetime(2022, 1, 2, 7, 0, 0),
                rrule=Recur(freq=Frequency.YEARLY, by_month=[1, 6], count=4),
            ),
        ]
    )
    events = list(calendar.timeline)
    assert [(event.start, event.summary) for event in events] == [
        (datetime.datetime(2022, 1, 2, 6, 0, 0), "Bi-annual meeting"),
        (datetime.datetime(2022, 6, 2, 6, 0, 0), "Bi-annual meeting"),
        (datetime.datetime(2023, 1, 2, 6, 0, 0), "Bi-annual meeting"),
        (datetime.datetime(2023, 6, 2, 6, 0, 0), "Bi-annual meeting"),
    ]


def test_until_time_mismatch() -> None:
    """Test failure case where until has a different timezone than start."""

    with pytest.raises(
        ValidationError, match="DTSTART is date local but UNTIL was not"
    ):
        Event(
            summary="Bi-annual meeting",
            start=datetime.datetime(2022, 1, 2, 6, 0, 0),
            end=datetime.datetime(2022, 1, 2, 7, 0, 0),
            rrule=Recur(
                freq=Frequency.DAILY,
                until=datetime.datetime(
                    2022, 8, 4, 1, 0, 0, tzinfo=datetime.timezone.utc
                ),
            ),
        )

    with pytest.raises(
        ValidationError, match="DTSTART had UTC or local and UNTIL must be UTC"
    ):
        Event(
            summary="Bi-annual meeting",
            start=datetime.datetime(2022, 1, 2, 6, 0, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 2, 7, 0, 0),
            rrule=Recur(
                freq=Frequency.DAILY,
                until=datetime.datetime(
                    2022, 8, 4, 1, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
                ),
            ),
        )

    with pytest.raises(
        ValidationError, match="DTSTART had UTC or local and UNTIL must be UTC"
    ):
        Event(
            summary="Bi-annual meeting",
            start=datetime.datetime(
                2022, 1, 2, 6, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
            ),
            end=datetime.datetime(2022, 1, 2, 7, 0, 0),
            rrule=Recur(
                freq=Frequency.DAILY,
                until=datetime.datetime(
                    2022, 8, 4, 1, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
                ),
            ),
        )


@pytest.mark.parametrize(
    "recur",
    [
        Recur(freq=Frequency.DAILY, interval=2),
        Recur.from_rrule("FREQ=DAILY;INTERVAL=2"),
    ],
)
def test_recur_as_string(recur: Recur) -> None:
    """Test converting a recurrence rule back to a string."""

    event = Event(
        summary="summary",
        start=datetime.date(2022, 8, 1),
        end=datetime.date(2022, 8, 2),
        rrule=recur,
    )
    assert event.rrule
    assert event.rrule.as_rrule_str() == "FREQ=DAILY;INTERVAL=2"


@pytest.mark.parametrize(
    "recur",
    [
        Recur(freq=Frequency.DAILY, until=datetime.datetime(2022, 8, 10, 6, 0, 0)),
        Recur.from_rrule("FREQ=DAILY;UNTIL=20220810T060000"),
    ],
)
def test_recur_until_as_string(recur: Recur) -> None:
    """Test converting a recurrence rule with a date into a string."""

    event = Event(
        summary="summary",
        start=datetime.datetime(2022, 8, 1, 6, 0, 0),
        end=datetime.datetime(2022, 8, 2, 6, 30, 0),
        rrule=recur,
    )
    assert event.rrule
    assert event.rrule.as_rrule_str() == "FREQ=DAILY;UNTIL=20220810T060000"


@pytest.mark.parametrize(
    "recur",
    [
        Recur(freq=Frequency.WEEKLY, by_weekday=[WeekdayValue(Weekday.TUESDAY)]),
        Recur.from_rrule("FREQ=WEEKLY;BYDAY=TU"),
    ],
)
def test_recur_by_weekday_as_string(recur: Recur) -> None:
    """Test converting a recurrence rule with a weekday repeat into a string."""
    event = Event(
        summary="summary",
        start=datetime.date(2022, 9, 6),
        end=datetime.date(2022, 9, 7),
        rrule=recur,
    )
    assert event.rrule
    assert event.rrule.as_rrule_str() == "FREQ=WEEKLY;BYDAY=TU"


@pytest.mark.parametrize(
    "recur",
    [
        Recur(
            freq=Frequency.MONTHLY, until=datetime.date(2023, 1, 1), by_month_day=[1]
        ),
        Recur.from_rrule("FREQ=MONTHLY;UNTIL=20230101;BYMONTHDAY=1"),
    ],
)
def test_recur_by_monthday_as_string(recur: Recur) -> None:
    """Test converting a recurrence rule with a weekday reepat into a string."""
    event = Event(
        summary="summary",
        start=datetime.date(2022, 9, 6),
        end=datetime.date(2022, 9, 7),
        rrule=recur,
    )
    assert event.rrule
    assert event.rrule.as_rrule_str() == "FREQ=MONTHLY;UNTIL=20230101;BYMONTHDAY=1"


@pytest.mark.parametrize(
    "recur",
    [
        Recur(
            freq=Frequency.MONTHLY,
            by_weekday=[WeekdayValue(weekday=Weekday.TUESDAY, occurrence=-1)],
        ),
        Recur.from_rrule("FREQ=MONTHLY;BYDAY=-1TU"),
    ],
)
def test_recur_by_last_day_as_string(recur: Recur) -> None:
    """Test converting a recurrence rule with a weekday reepat into a string."""
    event = Event(
        summary="summary",
        start=datetime.date(2022, 9, 6),
        end=datetime.date(2022, 9, 7),
        rrule=recur,
    )
    assert event.rrule
    assert event.rrule.as_rrule_str() == "FREQ=MONTHLY;BYDAY=-1TU"


def test_rdate_all_day() -> None:
    """Test how all day events are handled with RDATE."""

    calendar = Calendar()
    calendar.events.extend(
        [
            Event(
                summary="Monthly Event",
                start=datetime.date(2022, 8, 2),
                end=datetime.date(2022, 8, 2),
                rdate=[
                    datetime.date(2022, 8, 3),
                    datetime.date(2022, 8, 4),
                    datetime.date(2022, 10, 3),
                ],
                rrule=Recur.from_rrule("FREQ=MONTHLY;COUNT=3"),
            ),
        ]
    )
    events = list(calendar.timeline)
    assert [(event.start, event.summary) for event in events] == [
        (datetime.date(2022, 8, 2), "Monthly Event"),
        (datetime.date(2022, 8, 3), "Monthly Event"),
        (datetime.date(2022, 8, 4), "Monthly Event"),
        (datetime.date(2022, 9, 2), "Monthly Event"),
        (datetime.date(2022, 10, 2), "Monthly Event"),
        (datetime.date(2022, 10, 3), "Monthly Event"),
    ]
