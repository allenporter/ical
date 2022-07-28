"""Grouping of calendar properties that describe a to-do."""

from __future__ import annotations

import datetime
from typing import Any, Optional, Union

from pydantic import Field, validator

from .contentlines import ParsedProperty
from .types import ComponentModel, Priority, TodoStatus, parse_text


class Todo(ComponentModel):
    """A calendar todo component."""

    uid: str
    dtstamp: Union[datetime.datetime, datetime.date]
    summary: str
    description: Optional[str] = None
    dtstart: Union[datetime.datetime, datetime.date, None] = None
    due: Union[datetime.datetime, datetime.date, None] = None
    classification: Optional[str] = Field(alias="class", default=None)
    completed: Optional[datetime.datetime] = None
    created: Optional[datetime.datetime] = None

    priority: Optional[Priority] = None

    categories: list[str] = Field(default_factory=list)
    status: Optional[TodoStatus] = None
    extras: list[tuple[str, ParsedProperty]] = Field(default_factory=list)

    @validator("status", pre=True, allow_reuse=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse a TodoStatus from a ParsedPropertyValue."""
        value = parse_text(value)
        if value and not isinstance(value, str):
            raise ValueError(f"Expected text value as a string: {value}")
        return value

    @validator("categories", pre=True)
    def parse_categories(cls, value: list[str]) -> list[str]:
        """Parse Categories from a list of ParsedProperty."""
        values: list[str] = []
        for prop in value:
            values.extend(prop.split(","))
        return values
