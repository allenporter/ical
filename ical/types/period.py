"""Library for parsing and encoding PERIOD values."""

import dataclasses
import datetime
import enum
import logging
from typing import Any, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

from .const import CaseInsensitiveEnum
from .data_types import DATA_TYPE, encode_model_property_params, serialize_field
from .date_time import DateTimeEncoder
from .duration import DurationEncoder
from .parsing import parse_parameter_values

_LOGGER = logging.getLogger(__name__)


@DATA_TYPE.register("FBTYPE")
class FreeBusyType(CaseInsensitiveEnum):
    """Specifies the free/busy time type."""

    FREE = "FREE"
    """The time interval is free for scheduling."""

    BUSY = "BUSY"
    """One or more events have been scheduled for the interval."""

    BUSY_UNAVAILABLE = "BUSY-UNAVAILABLE"
    """The interval can not be scheduled."""

    BUSY_TENTATIVE = "BUSY-TENTATIVE"
    """One or more events have been tentatively scheduled for the interval."""

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> Self | None:
        """Parse value into enum."""
        try:
            return cls(prop.value)
        except ValueError:
            return None


@DATA_TYPE.register("PERIOD", parse_order=3)
class Period(BaseModel):
    """A value with a precise period of time."""

    start: datetime.datetime
    """Start of the period of time."""

    end: Optional[datetime.datetime] = None
    """End of the period of the time (duration is implicit)."""

    duration: Optional[datetime.timedelta] = None
    """Duration of the period of time (end time is implicit)."""

    # Context specific property parameters
    free_busy_type: Optional[FreeBusyType] = Field(alias="FBTYPE", default=None)
    """Specifies the free or busy time type."""

    _parse_parameter_values = model_validator(mode="before")(parse_parameter_values)

    @property
    def end_value(self) -> datetime.datetime:
        """A computed end value based on either end or duration."""
        if self.end is not None:
            return self.end
        if self.duration is None:
            raise ValueError("Invalid period missing both end and duration")
        return self.start + self.duration

    @model_validator(mode="after")
    def _validate_period(self) -> Self:
        """Validate period start, end, and duration fields."""
        if self.end is None and self.duration is None:
            raise ValueError("Invalid period missing both end and duration")
        if self.end is not None and self.duration is not None:
            raise ValueError("Invalid period cannot specify both end and duration")
        if self.end is not None:
            if (self.start.tzinfo is None) != (self.end.tzinfo is None):
                raise ValueError(
                    "Period start and end must both be timezone-aware or both be naive"
                )
            if self.start.tzinfo is not None and str(self.start.tzinfo) != str(
                self.end.tzinfo
            ):
                raise ValueError(
                    f"Period start and end must have the same timezone: {self.start.tzinfo} != {self.end.tzinfo}"
                )
        return self

    @model_validator(mode="before")
    @classmethod
    def parse_period_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse a rfc5545 priority value."""
        if not isinstance(values, dict):
            return values
        if not (value := values.pop("value", None)):
            return values
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError(f"Period did not have two time values: {value}")
        params = values.get("params")
        if params and isinstance(params, list):
            if all(isinstance(p, dict) for p in params):
                params = [
                    ParsedPropertyParameter(name=p["name"], values=p["values"])
                    for p in params
                ]
        try:
            start = DateTimeEncoder.__parse_property_value__(
                ParsedProperty(name="ignored", value=parts[0], params=params)
            )
        except ValueError as err:
            _LOGGER.debug("Failed to parse start date as date time: %s", parts[0])
            raise err
        values["start"] = start
        try:
            end = DateTimeEncoder.__parse_property_value__(
                ParsedProperty(name="ignored", value=parts[1], params=params)
            )
        except ValueError:
            pass
        else:
            values["end"] = end
            return values
        try:
            duration = DurationEncoder.__parse_property_value__(
                ParsedProperty(name="ignored", value=parts[1])
            )
        except ValueError as err:
            raise err
        values["duration"] = duration
        return values

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> dict[str, Any]:
        """Convert the property into a dictionary for pydantic model."""
        if "/" not in prop.value:
            raise ValueError(f"Value does not contain a solidus: {prop.value}")
        return dataclasses.asdict(prop)

    @classmethod
    def __encode_property__(cls, model_data: Any) -> ParsedProperty | None:
        """Encode the property."""
        if not isinstance(model_data, dict):
            return None
        model_data = dict(model_data)
        start_raw = model_data.pop("start", None)
        start_tzid = None
        if isinstance(start_raw, dict):
            start_tzid = start_raw.get("TZID")
            start = start_raw.get("VALUE")
        else:
            start = start_raw
        if not start or not isinstance(start, str):
            raise ValueError(f"Invalid period object missing start: {model_data}")

        end_raw = model_data.pop("end", None)
        end_tzid = None
        if isinstance(end_raw, dict):
            end_tzid = end_raw.get("TZID")
            end = end_raw.get("VALUE")
        else:
            end = end_raw

        duration = model_data.pop("duration", None)
        if not end and not duration:
            raise ValueError(
                f"Invalid period missing both end and duration: {model_data}"
            )
        # End and duration are already encoded values
        if end:
            if (
                not isinstance(end, str)
                or start_tzid != end_tzid
                or (start_tzid is None and start.endswith("Z") != end.endswith("Z"))
            ):
                raise ValueError(
                    f"Period start and end have mismatched timezones: {start_raw} vs {end_raw}"
                )
            value = "/".join([start, end])
        else:
            value = "/".join([start, duration])

        params = (
            encode_model_property_params(
                cls.model_fields,
                {
                    k: v
                    for k, v in model_data.items()
                    if k not in ("end", "duration", "start")
                },
            )
            or []
        )
        if start_tzid:
            params.append(
                ParsedPropertyParameter(name="TZID", values=[str(start_tzid)])
            )
        return ParsedProperty(
            name="",
            value=value,
            params=params or None,
        )

    model_config = ConfigDict(populate_by_name=True)
    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]
