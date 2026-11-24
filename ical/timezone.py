"""A grouping of component properties that defines a time zone.

An iCal timezone is a complete description of a timezone, separate
from the built-in timezones used by python datetime objects. You can
think of this like fully persisting all timezone information referenced
in the calendar for dates to reference. Timezones are captured to
unambiguously describe time information to aid in interoperability between
different calendaring systems.
"""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import bisect
import copy
import traceback
import datetime
import enum
import logging
from dataclasses import dataclass
from typing import Annotated, Any, Iterable, Optional, Self, Union

from pydantic import (
    BeforeValidator,
    Field,
    PrivateAttr,
    field_serializer,
    field_validator,
    model_validator,
)

from ical.types.data_types import serialize_field

from .component import ComponentModel
from .iter import (
    CachedTransitionTimeline,
    MergedIterable,
    RecurIterable,
    RulesetIterable,
)
from .types import ExtraProperty, Recur, Uri, UtcOffset
from .tzif import timezoneinfo, tz_rule
from .util import parse_date_and_datetime_list

__all__ = [
    "Timezone",
    "Observance",
]

_LOGGER = logging.getLogger(__name__)


# Assume that all tzif timezone rules start at an arbitrary old date. This library
# typically only works with "go forward" dates, so we don't need to be completely
# accurate and use the historical database of times.
_TZ_START = datetime.datetime(2010, 1, 1, 0, 0, 0)

_ZERO = datetime.timedelta(0)


class Observance(ComponentModel):
    """A sub-component with properties for a set of timezone observances."""

    # Has an alias of 'start'
    dtstart: Optional[datetime.datetime] = Field(default=None)
    """The first onset datetime (local time) for the observance."""

    tz_offset_to: UtcOffset = Field(alias="tzoffsetto")
    """Gives the UTC offset for the time zone when this observance is in use."""

    tz_offset_from: UtcOffset = Field(alias="tzoffsetfrom")
    """The timezone offset used when the onset of this time zone observance begins.

    The tz_offset_from and dtstart define the effective onset for the time zone sub-component.
    """

    rrule: Optional[Recur] = None
    """The recurrence rule for the onset of observances defined in this sub-component."""

    rdate: Annotated[
        list[Union[datetime.date, datetime.datetime]],
        BeforeValidator(parse_date_and_datetime_list),
    ] = Field(default_factory=list)
    """A rule to determine the onset of the observances defined in this sub-component."""

    tz_name: list[str] = Field(alias="tzname", default_factory=list)
    """A name for the observance."""

    comment: list[str] = Field(default_factory=list)
    """Descriptive explanatory text."""

    extras: list[ExtraProperty] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        """Initialize Timezone."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        super().__init__(**data)

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the start of the observance."""
        assert self.dtstart is not None
        return self.dtstart

    def as_ruleset(self) -> Iterable[datetime.datetime | datetime.date]:
        """Represent the occurrence as a rule of repeated dates or datetimes."""
        if not self.rrule and not self.rdate:
            return [self.start_datetime]
        return RulesetIterable(
            self.start_datetime,
            [self.rrule.as_rrule(self.start_datetime)] if self.rrule else [],
            self.rdate if self.rrule else [self.start_datetime, *self.rdate],
            [],
        )

    @field_validator("dtstart")
    @classmethod
    def verify_dtstart_local_time(cls, value: datetime.datetime) -> datetime.datetime:
        """Validate that dtstart is specified in a local time."""
        if value.utcoffset() is not None:
            raise ValueError(f"Start time must be in local time format: {value}")
        return value

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]


class _ObservanceType(str, enum.Enum):
    """Type of a timezone observance."""

    STANDARD = "STANDARD"
    DAYLIGHT = "DAYLIGHT"


@dataclass
class _ObservanceInfo:
    """Object holding observance information."""

    observance_type: _ObservanceType
    observance: Observance

    @property
    def offset_delta(self) -> datetime.timedelta:
        """Return the wall-clock shift (tz_offset_to - tz_offset_from) at onset."""
        return (
            self.observance.tz_offset_to.offset - self.observance.tz_offset_from.offset
        )

    def __lt__(self, other: Any) -> bool:
        """Provide deterministic tie-breaking when two observances share an onset."""
        if not isinstance(other, _ObservanceInfo):
            return NotImplemented
        return (
            self.observance.tz_offset_to.offset,
            self.observance_type.value,
        ) < (
            other.observance.tz_offset_to.offset,
            other.observance_type.value,
        )

    def get(
        self,
        value: datetime.datetime | datetime.date,
    ) -> tuple[datetime.datetime | datetime.date, "_ObservanceInfo"]:
        """Adapt for an iterator over observances."""
        return (value, self)

    def get_utc(
        self,
        value: datetime.datetime | datetime.date,
    ) -> tuple[datetime.datetime, "_ObservanceInfo"]:
        """Adapt for an iterator over UTC onset instants."""
        dt = (
            value
            if isinstance(value, datetime.datetime)
            else datetime.datetime.combine(value, datetime.time.min)
        )
        return (dt - self.observance.tz_offset_from.offset, self)


def _transition_onset(
    item: tuple[datetime.datetime | datetime.date, _ObservanceInfo],
) -> datetime.datetime | datetime.date:
    return item[0]


class Timezone(ComponentModel):
    """A single free/busy entry on a calendar.

    A Timezone must have at least one definition of a standard or daylight
    sub-component.
    """

    tz_id: str = Field(alias="tzid")
    """An identifier for this Timezone, unique within a calendar."""

    standard: list[Observance] = Field(default_factory=list)
    """Describes the base offset from UTC for the time zone."""

    daylight: list[Observance] = Field(default_factory=list)
    """Describes adjustments made to account for changes in daylight hours."""

    tz_url: Optional[Uri] = Field(alias="tzurl", default=None)
    """Url that points to a published timezone definition."""

    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    """Specifies the date and time that this time zone was last updated."""

    # Unknown or unsupported properties
    extras: list[ExtraProperty] = Field(default_factory=list)

    # Per-instance lazily-cached timeline over the observance transitions, so the
    # (potentially centuries-long) recurrence expansion only runs once instead of
    # on every `get_observance` lookup.
    _observance_timeline: Optional[CachedTransitionTimeline["_ObservanceInfo"]] = (
        PrivateAttr(default=None)
    )
    _utc_observance_timeline: Optional[CachedTransitionTimeline["_ObservanceInfo"]] = (
        PrivateAttr(default=None)
    )

    @classmethod
    def from_tzif(cls, key: str, start: datetime.datetime = _TZ_START) -> Timezone:
        """Create a new Timezone from a tzif data source."""
        info = timezoneinfo.read(key)
        rule = info.rule
        if not rule:
            raise ValueError("Unsupported timezoneinfo had no rule")

        dst_offset = rule.std.offset
        if rule.dst and rule.dst.offset:
            dst_offset = rule.dst.offset

        std_timezone_info = Observance(
            tz_name=[rule.std.name],
            tz_offset_to=UtcOffset(offset=rule.std.offset),
            tz_offset_from=UtcOffset(dst_offset),
            dtstart=start,
        )
        daylight = []
        if (
            rule.dst
            and rule.dst_start
            and isinstance(rule.dst_start, tz_rule.RuleDate)
            and rule.dst_end
            and isinstance(rule.dst_end, tz_rule.RuleDate)
        ):
            std_timezone_info.rrule = Recur.model_validate(
                Recur.__parse_property_value__(rule.dst_end.rrule_str)
            )
            std_timezone_info.dtstart = rule.dst_end.rrule_dtstart(start)
            daylight.append(
                Observance(
                    tz_name=[rule.dst.name],
                    tz_offset_to=UtcOffset(offset=rule.dst.offset),
                    tz_offset_from=UtcOffset(offset=rule.std.offset),
                    rrule=Recur.model_validate(
                        Recur.__parse_property_value__(rule.dst_start.rrule_str)
                    ),
                    dtstart=rule.dst_start.rrule_dtstart(start),
                )
            )
        return Timezone(tzid=key, standard=[std_timezone_info], daylight=daylight)

    def _observances(
        self,
    ) -> Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]:
        return MergedIterable(self._std_observances() + self._dst_observances())

    def _std_observances(
        self,
    ) -> list[Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]]:
        iters: list[
            Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]
        ] = []
        for observance in self.standard:
            iters.append(
                RecurIterable(
                    _ObservanceInfo(_ObservanceType.STANDARD, observance).get,
                    observance.as_ruleset(),
                )
            )
        return iters

    def _dst_observances(
        self,
    ) -> list[Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]]:
        iters: list[
            Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]
        ] = []
        for observance in self.daylight:
            iters.append(
                RecurIterable(
                    _ObservanceInfo(_ObservanceType.DAYLIGHT, observance).get,
                    observance.as_ruleset(),
                )
            )
        return iters

    def _utc_observances(
        self,
    ) -> Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]:
        iters: list[
            Iterable[tuple[datetime.datetime | datetime.date, _ObservanceInfo]]
        ] = []
        for observance in self.standard:
            iters.append(
                RecurIterable(
                    _ObservanceInfo(_ObservanceType.STANDARD, observance).get_utc,
                    observance.as_ruleset(),
                )
            )
        for observance in self.daylight:
            iters.append(
                RecurIterable(
                    _ObservanceInfo(_ObservanceType.DAYLIGHT, observance).get_utc,
                    observance.as_ruleset(),
                )
            )
        return MergedIterable(iters)

    def _fallback_prior_observance(
        self, cur_info: _ObservanceInfo
    ) -> _ObservanceInfo | None:
        """Find a defined observance matching ``cur_info.tz_offset_from`` before index 0."""
        target = cur_info.observance.tz_offset_from.offset
        for obs in self.standard:
            if obs.tz_offset_to.offset == target:
                return _ObservanceInfo(_ObservanceType.STANDARD, obs)
        for obs in self.daylight:
            if obs.tz_offset_to.offset == target:
                return _ObservanceInfo(_ObservanceType.DAYLIGHT, obs)
        return None

    def get_observance(self, value: datetime.datetime) -> _ObservanceInfo | None:
        """Return the specified observance for the specified date."""
        if value.tzinfo is not None:
            raise ValueError("Start time must be in local time format")
        if self._observance_timeline is None:
            self._observance_timeline = CachedTransitionTimeline(self._observances())
        cached = self._observance_timeline._cached
        cached.extend_through(lambda item: item[0] <= value)
        cache_list = cached._cache
        n = len(cache_list)
        index = bisect.bisect_right(cache_list, value, hi=n, key=_transition_onset)
        # Ambiguous fall-back fold: when fold=1 falls in [next_onset + delta, next_onset),
        # select the post-transition observance.
        if value.fold == 1 and index < n:
            next_onset, next_info = cache_list[index]
            delta_next = next_info.offset_delta
            if (
                delta_next < _ZERO
                and isinstance(next_onset, datetime.datetime)
                and next_onset + delta_next <= value
            ):
                return next_info
        if index == 0:
            if n > 0:
                return self._fallback_prior_observance(cache_list[0][1])
            return None
        cur_onset, cur_info = cache_list[index - 1]
        # Non-existent spring-forward gap: when fold=0 falls in [cur_onset, cur_onset + delta),
        # select the pre-transition observance when one exists.
        if value.fold == 0 and isinstance(cur_onset, datetime.datetime):
            delta_cur = cur_info.offset_delta
            if delta_cur > _ZERO and value < cur_onset + delta_cur:
                if index >= 2:
                    return cache_list[index - 2][1]
                if prior := self._fallback_prior_observance(cur_info):
                    return prior
        return cur_info

    def _get_utc_transition(
        self, utc_naive: datetime.datetime
    ) -> tuple[datetime.datetime | None, _ObservanceInfo] | None:
        """Return ``(onset_utc, observance_info)`` active at ``utc_naive``."""
        if self._utc_observance_timeline is None:
            self._utc_observance_timeline = CachedTransitionTimeline(
                self._utc_observances()
            )
        cached = self._utc_observance_timeline._cached
        cached.extend_through(lambda item: item[0] <= utc_naive)
        cache_list = cached._cache
        n = len(cache_list)
        index = bisect.bisect_right(cache_list, utc_naive, hi=n, key=_transition_onset)
        if index == 0:
            if n > 0 and (prior := self._fallback_prior_observance(cache_list[0][1])):
                return (None, prior)
            return None
        onset_utc, info = cache_list[index - 1]
        assert isinstance(onset_utc, datetime.datetime)
        return (onset_utc, info)

    @model_validator(mode="after")
    def parse_required_timezoneinfo(self) -> Self:
        """Require at least one standard or daylight definition."""
        standard = self.standard
        daylight = self.daylight
        if not standard and not daylight:
            raise ValueError("At least one standard or daylight definition is required")
        return self

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]


class IcsTimezoneInfo(datetime.tzinfo):
    """An implementation of tzinfo based on an ICS Timezone.

    This class is used to provide a tzinfo object for any datetime object
    used within a calendar. An rfc5545 calendar is an unambiguous definition of
    a calendar, and as a result, must encode all timezone information used in
    the calendar, hence this class.

    Honors PEP 495 ``fold`` across DST fall-back folds and spring-forward gaps,
    and implements ``fromutc`` to set ``fold=1`` on repeated local times.
    """

    def __init__(self, timezone: Timezone) -> None:
        """Initialize IcsTimezoneInfo."""
        self._timezone = timezone

    def __deepcopy__(self, memo: Any) -> IcsTimezoneInfo:
        """Return a deep copy of the timezone object."""
        return IcsTimezoneInfo(
            timezone=copy.deepcopy(self._timezone, memo),
        )

    @classmethod
    def from_timezone(cls, timezone: Timezone) -> IcsTimezoneInfo:
        """Create a new instance of an IcsTimezoneInfo."""
        return cls(timezone)

    def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta:
        """Return offset of local time from UTC, as a timedelta object."""
        if not dt or not (obs := self._get_observance(dt)):
            return _ZERO
        return obs.observance.tz_offset_to.offset

    def tzname(self, dt: datetime.datetime | None) -> str | None:
        """Return the time zone name for the datetime as a sorting."""
        if (
            not dt
            or not (obs := self._get_observance(dt))
            or not obs.observance.tz_name
        ):
            return None
        return obs.observance.tz_name[0]

    def dst(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
        """Return the daylight saving time (DST) adjustment, if applicable."""
        if (
            not dt
            or not (obs := self._get_observance(dt))
            or obs.observance_type != _ObservanceType.DAYLIGHT
        ):
            return _ZERO
        return obs.observance.tz_offset_to.offset - obs.observance.tz_offset_from.offset

    def _get_observance(self, value: datetime.datetime) -> _ObservanceInfo | None:
        return self._timezone.get_observance(value.replace(tzinfo=None))

    def fromutc(self, dt: datetime.datetime) -> datetime.datetime:
        """Convert a datetime with UTC wall fields and ``tzinfo=self`` to local time."""
        if not isinstance(dt, datetime.datetime):
            raise TypeError("fromutc() requires a datetime argument")
        if dt.tzinfo is not self:
            raise ValueError("dt.tzinfo is not self")
        utc_naive = dt.replace(tzinfo=None)
        transition = self._timezone._get_utc_transition(utc_naive)
        if transition is None:
            return dt.replace(fold=0)
        onset_utc, obs_info = transition
        offset_to = obs_info.observance.tz_offset_to.offset
        if onset_utc is None:
            return (dt + offset_to).replace(fold=0)
        delta = obs_info.offset_delta
        local_dt = dt + offset_to
        fold = (
            1
            if (
                delta < _ZERO
                and utc_naive < onset_utc - delta
                and self.utcoffset(local_dt.replace(fold=0)) != offset_to
            )
            else 0
        )
        return local_dt.replace(fold=fold)

    def __str__(self) -> str:
        """A string representation of the timezone object."""
        return self._timezone.tz_id

    def __repr__(self) -> str:
        """A string representation of the timezone object."""
        return f"{self.__class__.__name__}({self._timezone.tz_id})"


class TimezoneModel(ComponentModel):
    """A parser of a calendar that just parses timezone data.

    This exists so that we can parse timezone information in a first pass then propagate
    that information down to child objects when parsing the rest of the calendar. This is
    so we can do one pass on parsing events and timezone information at once, rather than
    deferring to later.
    """

    timezones: list[Timezone] = Field(alias="vtimezone", default_factory=list)
    """Timezones associated with this calendar."""
