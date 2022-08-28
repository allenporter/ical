"""Constants and enums representing rfc5545 values."""

import enum


class EventStatus(str, enum.Enum):
    """Status or confirmation of the event."""

    CONFIRMED = "CONFIRMED"
    TENTATIVE = "TENTATIVE"
    CANCELLED = "CANCELLED"


class TodoStatus(str, enum.Enum):
    """Status or confirmation of the to-do."""

    NEEDS_ACTION = "NEEDS-ACTION"
    COMPLETED = "COMPLETED"
    IN_PROCESS = "IN-PROCESS"
    CANCELLED = "CANCELLED"


class JournalStatus(str, enum.Enum):
    """Status or confirmation of the journal entry."""

    DRAFT = "DRAFT"
    FINAL = "FINAL"
    CANCELLED = "CANCELLED"


class Classification(str, enum.Enum):
    """Defines the access classification for a calendar component."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    CONFIDENTIAL = "CONFIDENTIAL"


class CalendarUserType(str, enum.Enum):
    """The type of calendar user."""

    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    RESOURCE = "GROUP"
    ROOM = "ROOM"
    UNKNOWN = "UNKNOWN"


class ParticipationStatus(str, enum.Enum):
    """Participation status for a calendar user."""

    NEEDS_ACTION = "NEEDS-ACTION"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    # Additional statuses for Events and Todos
    TENTATIVE = "TENTATIVE"
    DELEGATED = "DELEGATED"
    # Additional status for TODOs
    COMPLETED = "COMPLETED"


class Role(str, enum.Enum):
    """Role for the calendar user."""

    CHAIR = "CHAIR"
    REQUIRED = "REQ-PARTICIPANT"
    OPTIONAL = "OPT-PARTICIPANT"
    NON_PARTICIPANT = "NON-PARTICIPANT"


class FreeBusyType(str, enum.Enum):
    """Specifies the free/busy time type."""

    FREE = "FREE"
    """The time interval is free for scheduling."""

    BUSY = "BUSY"
    """One or more events have been scheduled for the interval."""

    BUSY_UNAVAILABLE = "BUSY-UNAVAILABLE"
    """The interval can not be scheduled."""

    BUSY_TENTATIVE = "BUSY-TENTATIVE"
    """One or more events have been tentatively scheduled for the interval."""
