"""Clean-room Policy Mode Enumerations and Configuration for ReferenceStore.

Each field of `PolicyConfig` corresponds 1-to-1 with a `PolicyMode` JSON specification
in `tests/spec/modes/<field>.json`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any


class StoreError(ValueError):
    """Exception raised when an operation violates RFC or store policy constraints."""


class SeriesEditOverrideMode(StrEnum):
    """Policy governing how whole-series edits affect valid overrides (R-L4-003, R-L4-005)."""

    PROPAGATE_PATCH = "PROPAGATE_PATCH"
    MASTER_ONLY = "MASTER_ONLY"


class SingleEditExdateMode(StrEnum):
    """Policy governing whether single-instance edit also adds EXDATE to master (R-L2-005)."""

    RFC_OVERRIDE_ONLY = "RFC_OVERRIDE_ONLY"
    LEGACY_DUAL_EXDATE = "LEGACY_DUAL_EXDATE"


class SeriesRescheduleExceptionMode(StrEnum):
    """Policy governing EXDATEs/overrides when a whole-series edit moves the series (R-L4-004, R-L4-005)."""

    PRUNE_INVALID = "PRUNE_INVALID"
    SHIFT_WITH_SERIES = "SHIFT_WITH_SERIES"


class SplitFutureOverrideMode(StrEnum):
    """Policy governing overrides at/after the split point on a THIS_AND_FUTURE edit (R-L3-006)."""

    DISCARD = "DISCARD"
    MIGRATE_TO_FUTURE_SERIES = "MIGRATE_TO_FUTURE_SERIES"


class ParentDeleteCascadeMode(StrEnum):
    """Policy governing RELATED-TO children when a parent UID is fully deleted (R-L5-007)."""

    CASCADE_DELETE = "CASCADE_DELETE"
    DETACH_CHILDREN = "DETACH_CHILDREN"
    LEAVE_DANGLING = "LEAVE_DANGLING"


_MODE_ENUM_BY_FIELD: dict[str, type[StrEnum]] = {
    "series_edit_override_mode": SeriesEditOverrideMode,
    "single_edit_exdate_mode": SingleEditExdateMode,
    "series_reschedule_exception_mode": SeriesRescheduleExceptionMode,
    "split_future_override_mode": SplitFutureOverrideMode,
    "parent_delete_cascade_mode": ParentDeleteCascadeMode,
}


@dataclass(frozen=True)
class PolicyConfig:
    """Explicit policy configuration for the Reference Store Oracle."""

    series_edit_override_mode: SeriesEditOverrideMode = (
        SeriesEditOverrideMode.PROPAGATE_PATCH
    )
    single_edit_exdate_mode: SingleEditExdateMode = (
        SingleEditExdateMode.RFC_OVERRIDE_ONLY
    )
    series_reschedule_exception_mode: SeriesRescheduleExceptionMode = (
        SeriesRescheduleExceptionMode.PRUNE_INVALID
    )
    split_future_override_mode: SplitFutureOverrideMode = (
        SplitFutureOverrideMode.DISCARD
    )
    parent_delete_cascade_mode: ParentDeleteCascadeMode = (
        ParentDeleteCascadeMode.CASCADE_DELETE
    )


def policy_from_modes(modes: dict[str, str] | None = None) -> PolicyConfig:
    """Build a PolicyConfig from a scenario's `modes` mapping, validating mode/option IDs."""
    if not modes:
        return PolicyConfig()
    kwargs: dict[str, Any] = {}
    for mode_id, opt_id in modes.items():
        enum_cls = _MODE_ENUM_BY_FIELD.get(mode_id)
        if enum_cls is None:
            raise StoreError(f"Unknown policy mode {mode_id!r}")
        try:
            kwargs[mode_id] = enum_cls(opt_id)
        except ValueError as exc:
            raise StoreError(
                f"Unknown option {opt_id!r} for policy mode {mode_id!r}"
            ) from exc
    return PolicyConfig(**kwargs)


def is_policy_compatible(
    policy: PolicyConfig, effective_modes: dict[str, list[str]]
) -> bool:
    """Return True if `policy` satisfies all mode constraints in `effective_modes`."""
    for f in fields(PolicyConfig):
        allowed = effective_modes.get(f.name)
        if allowed is not None and getattr(policy, f.name).value not in allowed:
            return False
    return True
