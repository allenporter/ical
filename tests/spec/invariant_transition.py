"""Clean-room TRANSITION-scope invariant predicates (`I-T-###`).

Each predicate takes a `Transition` (before-state, operation, after-state, failure flag
and permuted re-runs) and returns a list of violations. Predicates that do not apply to
the operation return an empty list.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from .invariant_common import (
    SCHEDULE_PATCH_KEYS,
    Component,
    Transition,
    identity_key,
    items,
    main_of,
    op_range,
    rel_targets,
    try_parse,
)
from .invariant_timeline import (
    OccurrenceMap,
    expand_occurrences,
    slot_instant,
    slot_key,
)
from .oracle_policy import StoreError

TransitionCheck = Callable[[Transition], list[str]]


def _applies(t: Transition, op: str, rng: str) -> bool:
    o = t.operation
    return (
        not t.failed
        and o.get("op") == op
        and o.get("recurrence_id") is not None
        and op_range(o) == rng
    )


def _expand_both(t: Transition) -> tuple[OccurrenceMap, OccurrenceMap] | str:
    try:
        return expand_occurrences(t.before), expand_occurrences(t.after)
    except (StoreError, ValueError) as exc:
        return f"state cannot be expanded: {exc}"


def _diff_others(b: OccurrenceMap, a: OccurrenceMap, skip: set[Any]) -> list[str]:
    errors: list[str] = []
    for key in sorted((set(b) | set(a)) - skip):
        if key not in a:
            errors.append(f"occurrence {key} disappeared")
        elif key not in b:
            errors.append(f"occurrence {key} appeared")
        elif b[key].comparable() != a[key].comparable():
            errors.append(f"occurrence {key} changed")
    return errors


def _single_target(t: Transition) -> tuple[OccurrenceMap, OccurrenceMap, Any] | str:
    maps = _expand_both(t)
    if isinstance(maps, str):
        return maps
    uid = str(t.operation["uid"])
    key = slot_key(t.before, uid, t.operation["recurrence_id"])
    if (uid, key) not in maps[0]:
        return f"operation succeeded on non-existent occurrence {(uid, key)}"
    return maps[0], maps[1], (uid, key)


def none_edit_targets_only_occurrence(t: Transition) -> list[str]:
    """A Range=NONE edit changes only the targeted occurrence of the timeline."""
    if not _applies(t, "edit", "NONE"):
        return []
    res = _single_target(t)
    if isinstance(res, str):
        return [res]
    before, after, target = res
    errors = _diff_others(before, after, {target})
    if target not in after:
        errors.append(f"edited occurrence {target} disappeared")
    return errors


def none_delete_removes_only_occurrence(t: Transition) -> list[str]:
    """A Range=NONE delete removes exactly the targeted occurrence."""
    if not _applies(t, "delete", "NONE"):
        return []
    res = _single_target(t)
    if isinstance(res, str):
        return [res]
    before, after, target = res
    errors = _diff_others(before, after, {target})
    if target in after:
        errors.append(f"deleted occurrence {target} is still on the timeline")
    return errors


def taf_preserves_prior_occurrences(t: Transition) -> list[str]:
    """A THIS_AND_FUTURE edit/delete leaves occurrences before the split unchanged."""
    if not (
        _applies(t, "edit", "THIS_AND_FUTURE")
        or _applies(t, "delete", "THIS_AND_FUTURE")
    ):
        return []
    uid = str(t.operation["uid"])
    split = slot_instant(t.before, uid, t.operation["recurrence_id"])
    maps = _expand_both(t)
    if isinstance(maps, str):
        return [maps]
    if split is None:
        return []
    before, after = maps
    errors: list[str] = []
    for key, occ in sorted(before.items()):
        if key[0] != uid or occ.slot >= split:
            continue
        if key not in after:
            errors.append(f"prior occurrence {key} disappeared")
        elif after[key].comparable() != occ.comparable():
            errors.append(f"prior occurrence {key} changed")
    return errors


def taf_metadata_edit_preserves_slots(t: Transition) -> list[str]:
    """A metadata-only THIS_AND_FUTURE edit preserves the set of occurrence slots."""
    if not _applies(t, "edit", "THIS_AND_FUTURE"):
        return []
    if set(t.operation.get("patch") or {}) & SCHEDULE_PATCH_KEYS:
        return []
    maps = _expand_both(t)
    if isinstance(maps, str):
        return [maps]
    uid = str(t.operation["uid"])
    new_uids = _uids(t.after) - _uids(t.before)
    before = {o.slot for k, o in maps[0].items() if k[0] == uid}
    after = {o.slot for k, o in maps[1].items() if k[0] == uid or k[0] in new_uids}
    errors = [f"slot {s.isoformat()} lost" for s in sorted(before - after)]
    errors += [f"slot {s.isoformat()} gained" for s in sorted(after - before)]
    return errors


def _persisting(t: Transition) -> list[tuple[Component, Component]]:
    before = {identity_key(c, t.before): c for c in items(t.before)}
    return [
        (before[key], comp)
        for comp in items(t.after)
        if (key := identity_key(comp, t.after)) in before
    ]


def persisting_sequence_and_created(t: Transition) -> list[str]:
    """SEQUENCE never decreases and CREATED never changes for a persisting component."""
    errors: list[str] = []
    for old, new in _persisting(t):
        if "sequence" in new and (new["sequence"] or 0) < (old.get("sequence") or 0):
            errors.append(f"{identity_key(new, t.after)}: sequence decreased")
        if old.get("created") is not None and "created" in new:
            if new["created"] != old["created"]:
                errors.append(f"{identity_key(new, t.after)}: created changed")
    return errors


def persisting_timestamps_monotonic(t: Transition) -> list[str]:
    """DTSTAMP and LAST-MODIFIED never move backwards for a persisting component."""
    errors: list[str] = []
    for old, new in _persisting(t):
        for key in ("dtstamp", "last_modified"):
            if old.get(key) is None or key not in new:
                continue
            pt_old, pt_new = try_parse(old[key], key), try_parse(new[key], key)
            if pt_new is None:
                errors.append(f"{identity_key(new, t.after)}: {key} removed")
            elif pt_old is not None and pt_new.dt_utc_or_naive < pt_old.dt_utc_or_naive:
                errors.append(f"{identity_key(new, t.after)}: {key} moved backwards")
    return errors


def _uids(components: list[Component]) -> set[str]:
    return {str(c.get("uid")) for c in items(components)}


def _new_segment_errors(t: Transition, new_uid: str) -> list[str]:
    uid = str(t.operation["uid"])
    original, old_original = main_of(t.after, uid), main_of(t.before, uid)
    segment = main_of(t.after, new_uid)
    if segment is None or original is None or old_original is None:
        return [f"split segment {new_uid!r} or original {uid!r} has no main component"]
    errors: list[str] = []
    if rel_targets(original, "NEXT") != [new_uid]:
        errors.append(f"original {uid!r} must carry exactly NEXT -> {new_uid!r}")
    first = (rel_targets(old_original, "FIRST") or [uid])[0]
    if rel_targets(segment, "FIRST") != [first]:
        errors.append(f"new segment {new_uid!r} must carry exactly FIRST -> {first!r}")
    if sorted(rel_targets(segment, "NEXT")) != sorted(
        rel_targets(old_original, "NEXT")
    ):
        errors.append(f"new segment {new_uid!r} must take over the original's NEXT")
    holders = [c for c in items(t.after) if new_uid in rel_targets(c, "NEXT")]
    if len(holders) != 1:
        errors.append(f"{len(holders)} components link NEXT -> {new_uid!r}")
    return errors


def split_links_well_formed(t: Transition) -> list[str]:
    """A split's new segment is linked NEXT from the original and FIRST to the chain head."""
    if not _applies(t, "edit", "THIS_AND_FUTURE"):
        return []
    errors: list[str] = []
    for new_uid in sorted(_uids(t.after) - _uids(t.before)):
        errors.extend(_new_segment_errors(t, new_uid))
    return errors


def failed_operation_is_atomic(t: Transition) -> list[str]:
    """A failed operation leaves the calendar state identical."""
    if t.failed and t.after != t.before:
        return ["failed operation modified the calendar state"]
    return []


def _canonical(components: list[Component]) -> list[str]:
    return sorted(json.dumps(c, sort_keys=True, default=str) for c in components)


def order_independent_result(t: Transition) -> list[str]:
    """Permuting the input component order does not change the result."""
    errors: list[str] = []
    for idx, other in enumerate(t.permuted_afters):
        if (other is None) != t.failed:
            errors.append(f"permutation #{idx}: success/failure differs")
        elif other is not None and _canonical(other) != _canonical(t.after):
            errors.append(f"permutation #{idx}: resulting state differs")
    return errors


TRANSITION_CHECKS: dict[str, TransitionCheck] = {
    "none_edit_targets_only_occurrence": none_edit_targets_only_occurrence,
    "none_delete_removes_only_occurrence": none_delete_removes_only_occurrence,
    "taf_preserves_prior_occurrences": taf_preserves_prior_occurrences,
    "taf_metadata_edit_preserves_slots": taf_metadata_edit_preserves_slots,
    "persisting_sequence_and_created": persisting_sequence_and_created,
    "persisting_timestamps_monotonic": persisting_timestamps_monotonic,
    "split_links_well_formed": split_links_well_formed,
    "failed_operation_is_atomic": failed_operation_is_atomic,
    "order_independent_result": order_independent_result,
}
