"""Strict Pydantic discriminated-union schema for declarative scenario operations.

Enforces canonical field names (`range` rather than `recurrence_range`, and
`"NONE" | "THIS_AND_FUTURE"` rather than `"THISANDFUTURE"`) across both rule
`MiniScenarioVector` scenarios and transition `InvariantExample` vectors.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

RecurrenceRange = Literal["NONE", "THIS_AND_FUTURE"]


class AddOperation(BaseModel):
    """Add a component (`VEVENT` by default, or `item['type']`)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add"]
    item: dict[str, Any]
    now: str | None = None
    expect_error: bool | str | None = None


class AddTodoOperation(BaseModel):
    """Add a `VTODO` component."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_todo"]
    item: dict[str, Any]
    now: str | None = None
    expect_error: bool | str | None = None


class EditOperation(BaseModel):
    """Edit a series, single occurrence (`NONE`), or `THIS_AND_FUTURE` range."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["edit"]
    uid: str
    patch: dict[str, Any]
    recurrence_id: str | None = None
    range: RecurrenceRange = "NONE"
    now: str | None = None
    new_uid: str | None = None
    expect_error: bool | str | None = None


class DeleteOperation(BaseModel):
    """Delete a whole UID, single occurrence (`NONE`), or `THIS_AND_FUTURE` range."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["delete"]
    uid: str
    recurrence_id: str | None = None
    range: RecurrenceRange = "NONE"
    now: str | None = None
    expect_error: bool | str | None = None


class ExpandOperation(BaseModel):
    """Read-only timeline expansion without mutating stored components."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["expand"]


class NestedDeleteStep(BaseModel):
    """Nested delete step inside a composite scenario operation."""

    model_config = ConfigDict(extra="forbid")

    uid: str
    recurrence_id: str | None = None
    range: RecurrenceRange = "NONE"
    now: str | None = None


class NestedEditStep(BaseModel):
    """Nested edit step inside a composite scenario operation."""

    model_config = ConfigDict(extra="forbid")

    uid: str
    patch: dict[str, Any]
    recurrence_id: str | None = None
    range: RecurrenceRange = "NONE"
    now: str | None = None
    new_uid: str | None = None


class DeleteThenEditOperation(BaseModel):
    """Composite operation: delete one occurrence then edit another."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["delete_then_edit"]
    delete: NestedDeleteStep
    edit: NestedEditStep


class EditTwiceOperation(BaseModel):
    """Composite operation: apply two successive in-place edits on one UID."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["edit_twice"]
    uid: str
    first_patch: dict[str, Any]
    second_patch: dict[str, Any]


class EditThenPartialDeleteOperation(BaseModel):
    """Composite operation: edit a series then delete a single occurrence."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["edit_then_partial_delete"]
    edit: NestedEditStep
    delete: NestedDeleteStep


ScenarioOperation = Annotated[
    AddOperation
    | AddTodoOperation
    | EditOperation
    | DeleteOperation
    | ExpandOperation
    | DeleteThenEditOperation
    | EditTwiceOperation
    | EditThenPartialDeleteOperation,
    Field(discriminator="op"),
]

_OPERATION_ADAPTER: TypeAdapter[ScenarioOperation] = TypeAdapter(ScenarioOperation)


def validate_operation_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate `raw` against `ScenarioOperation` and return the input dict."""
    _OPERATION_ADAPTER.validate_python(raw)
    return raw
