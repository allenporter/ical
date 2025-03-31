"""Library for parsing and encoding PERIOD values."""

from collections.abc import Callable, Generator
import dataclasses
import datetime
import enum
import logging
from typing import Any, Optional

try:
    from pydantic.v1 import BaseModel, Field, root_validator
except ImportError:
    from pydantic import BaseModel, Field, root_validator  # type: ignore[no-redef, assignment]

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

from .data_types import DATA_TYPE, encode_model_property_params
from .date_time import DateTimeEncoder
from .duration import DurationEncoder
from .parsing import parse_parameter_values
from .enum import create_enum_validator

_LOGGER = logging.getLogger(__name__)


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

    @classmethod
    def __get_validators__(cls) -> Generator[Callable[[Any], Any], None, None]:
        """Return a generator that validates the value against the enum."""
        yield create_enum_validator(FreeBusyType)


@DATA_TYPE.register("PERIOD")
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

    _parse_parameter_values = root_validator(pre=True, allow_reuse=True)(
        parse_parameter_values
    )

    @property
    def end_value(self) -> datetime.datetime:
        """A computed end value based on either or duration."""
        if self.end:
            return self.end
        if not self.duration:
            raise ValueError("Invalid period missing both end and duration")
        return self.start + self.duration

    @root_validator(pre=True, allow_reuse=True)
    def parse_period_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse a rfc5545 prioriry value."""
        if not (value := values.pop("value", None)):
            return values
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError(f"Period did not have two time values: {value}")
        try:
            start = DateTimeEncoder.__parse_property_value__(
                ParsedProperty(name="ignored", value=parts[0])
            )
        except ValueError as err:
            _LOGGER.debug("Failed to parse start date as date time: %s", parts[0])
            raise err
        values["start"] = start
        try:
            end = DateTimeEncoder.__parse_property_value__(
                ParsedProperty(name="ignored", value=parts[1])
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
    def __parse_property_value__(cls, prop: ParsedProperty) -> dict[str, str]:
        """Convert the property into a dictionary for pydantic model."""
        return dataclasses.asdict(prop)

    @classmethod
    def __encode_property_value__(cls, model_data: dict[str, Any]) -> str:
        """Encode property value."""
        if not (start := model_data.pop("start", None)):
            raise ValueError(f"Invalid period object missing start: {model_data}")
        end = model_data.pop("end", None)
        duration = model_data.pop("duration", None)
        if not end and not duration:
            raise ValueError(
                f"Invalid period missing both end and duration: {model_data}"
            )
        # End and duration are already encoded values
        if end:
            return "/".join([start, end])
        return "/".join([start, duration])

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        return encode_model_property_params(
            cls.__fields__.values(),
            {
                k: v
                for k, v in model_data.items()
                if k not in ("end", "duration", "start")
            },
        )

    class Config:
        """Pyandtic model configuration."""

        allow_population_by_field_name = True
