"""Data model for the tzif library."""

from collections import namedtuple
from dataclasses import dataclass
from typing import Optional

from .tz_rule import Rule


@dataclass
class Transition:
    """An individual item in the Datablock."""

    transition_time: int
    """A transition time at which the rules for computing local time may change."""

    utoff: int
    """Number of seconds added to UTC to determine local time."""

    dst: bool
    """Determines if local time is Daylight Savings Time (else Standard time)."""

    isstdcnt: bool
    """Determines if the transition time is standard time (else, wall clock time)."""

    isutccnt: bool
    """Determines if the transition time is UTC time, else is a local time."""

    designation: str
    """A designation string."""


LeapSecond = namedtuple("LeapSecond", ["occurrence", "correction"])
"""A correction that needs to be applied to UTC in order to determine TAI.

The occurrence is the time at which the leap-second correction occurs.
The correction is the value of LEAPCORR on or after the occurrence (1 or -1).
"""


@dataclass
class TimezoneInfo:
    """The results of parsing the TZif file."""

    transitions: list[Transition]
    """Local time changes."""

    leap_seconds: list[LeapSecond]

    rule: Optional[Rule] = None
    """A rule for computing local time changes after the last transition."""
