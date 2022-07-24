"""Grouping of calendar properties that describe a to-do."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import Field, validator

from .contentlines import ParsedProperty
from .model import ComponentModel
from .properties import Priority, TodoStatus
from .property_values import Date, DateTime, Text


class Todo(ComponentModel):
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
