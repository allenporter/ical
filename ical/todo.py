"""Grouping of calendar properties that describe a to-do."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field, root_validator, validator

from .contentlines import ParsedProperty
from .properties import Priority, TodoStatus
from .property_values import Date, DateTime, Text
from .validators import parse_property_fields


class Todo(BaseModel):
    """A calendar todo component."""

    dtstamp: Union[DateTime, Date]
    uid: Text
    summary: Text
    description: Optional[Text] = None
    dtstart: Optional[Union[DateTime, Date]] = None
    due: Optional[Union[DateTime, Date]]
    classification: Optional[Text] = Field(alias="class", default=None)
    completed: Optional[DateTime] = None
    created: Optional[DateTime] = None

    priority: Optional[Priority] = None

    categories: list[str] = Field(default_factory=list)
    status: Optional[TodoStatus] = None
    extras: list[tuple[str, ParsedProperty]] = Field(default_factory=list)

    # Flatten list[ParsedProperty] to ParsedProperty where appropriate
    _parse_property_fields = root_validator(pre=True, allow_reuse=True)(
        parse_property_fields
    )

    @validator("status", pre=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse a TodoStatus from a ParsedPropertyValue."""
        for func in Text.__get_validators__():
            value = func(value)
        if value and not isinstance(value, str):
            raise ValueError("Expected Text value as a string")
        return value

    @validator("categories", pre=True)
    def parse_categories(cls, value: Any) -> list[str]:
        """Parse Categories from a list of ParsedProperty."""
        values: list[str] = []
        for prop in value:
            # Extract string from text value
            for func in Text.__get_validators__():
                prop = func(prop)
            if not isinstance(prop, str):
                raise ValueError("Expected Text value as a string")
            values.extend(prop.split(","))
        return values

    @root_validator(pre=True)
    def parse_extra_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse extra fields not in the model."""
        all_fields = {
            field.alias for field in cls.__fields__.values() if field.alias != "extras"
        }
        extras: list[tuple[str, ParsedProperty]] = []
        for field_name in list(values):
            if field_name in all_fields:
                continue
            for prop in values.pop(field_name):
                extras.append((field_name, prop))
        if extras:
            values["extras"] = extras
        return values
