"""Tests for Alarm component."""

from __future__ import annotations

import datetime

import pytest

from ical.alarm import Alarm
from ical.exceptions import CalendarParseError


def test_todo() -> None:
    """Test a valid Alarm."""
    alarm = Alarm(action="AUDIO", trigger=datetime.timedelta(minutes=-5))
    assert alarm.action == "AUDIO"
    assert alarm.trigger == datetime.timedelta(minutes=-5)
    assert not alarm.duration
    assert not alarm.repeat


def test_duration_and_repeat() -> None:
    """Test relationship between the duration and repeat fields."""

    alarm = Alarm(
        action="AUDIO",
        trigger=datetime.timedelta(minutes=-5),
        duration=datetime.timedelta(seconds=30),
        repeat=2,
    )
    assert alarm.action
    assert alarm.trigger
    assert alarm.duration
    assert alarm.repeat == 2

    # Duration but no repeat
    with pytest.raises(CalendarParseError):
        Alarm(
            action="AUDIO",
            trigger=datetime.timedelta(minutes=-5),
            duration=datetime.timedelta(seconds=30),
        )

    # Repeat but no duration
    with pytest.raises(CalendarParseError):
        Alarm(action="AUDIO", trigger=datetime.timedelta(minutes=-5), repeat=2)


def test_display_required_fields() -> None:
    """Test required fields for action DISPLAY."""
    with pytest.raises(CalendarParseError, match="Description value is required for action DISPLAY"):
        Alarm(action="DISPLAY", trigger=datetime.timedelta(minutes=-5))

    alarm = Alarm(
        action="DISPLAY",
        trigger=datetime.timedelta(minutes=-5),
        description="Notification description",
    )
    assert alarm.action == "DISPLAY"
    assert alarm.description == "Notification description"


def test_email_required_fields() -> None:
    """Test required fields for action EMAIL."""
    # Missing multiple fields
    with pytest.raises(CalendarParseError, match="Description value is required for action EMAIL"):
        Alarm(action="EMAIL", trigger=datetime.timedelta(minutes=-5))

    # Missing summary
    with pytest.raises(CalendarParseError):
        Alarm(
            action="EMAIL",
            trigger=datetime.timedelta(minutes=-5),
            description="Email description",
        )

    # Missing description
    with pytest.raises(CalendarParseError):
        Alarm(
            action="EMAIL",
            trigger=datetime.timedelta(minutes=-5),
            summary="Email summary",
        )

    alarm = Alarm(
        action="DISPLAY",
        trigger=datetime.timedelta(minutes=-5),
        description="Email description",
        summary="Email summary",
    )
    assert alarm.action == "DISPLAY"
    assert alarm.summary == "Email summary"
    assert alarm.description == "Email description"
