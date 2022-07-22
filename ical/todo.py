"""Grouping of calendar properties that describe a to-do."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field, root_validator, validator

from .contentlines import ParsedProperty
from .properties import Priority, TodoStatus
from .property_values import Date, DateTime, Text


class IcsTodo(BaseModel):
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

    categories: Optional[list[str]] = None
    status: Optional[TodoStatus] = None
    extras: Optional[list[tuple[str, ParsedProperty]]] = None

    @validator("status", pre=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse a TodoStatus from a ParsedPropertyValue."""
        for func in Text.__get_validators__():
            value = func(value)
        if value and not isinstance(value, str):
            raise ValueError("Expected Text value as a string")
        return value

    @validator("categories", pre=True)
    def parse_categories(cls, value: Any) -> list[str] | None:
        """Parse Categories from a ParsedPropertyValue."""
        for func in Text.__get_validators__():
            value = func(value)
        if not value:
            return []
        if not isinstance(value, str):
            raise ValueError("Expected Text value as a string")
        return value.split(",")

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
