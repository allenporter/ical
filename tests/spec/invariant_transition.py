"""Clean-room TRANSITION-scope invariant predicates (`I-T-###`).

Each predicate takes a `Transition` (before-state, operation, after-state, failure flag
and permuted re-runs) and returns a list of violations. Predicates that do not apply to
the operation return an empty list.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import datetime
import json
from typing import Any

from .invariant_common import (
    SCHEDULE_PATCH_KEYS,
    Component,
    Transition,
    has_recurrence,
    identity_key,
    items,
    main_of,
    op_range,
    rel_targets,
    rrule_parts,
    try_parse,
)
from .invariant_timeline import (
    OccurrenceMap,
    dateless_items,
    expand_occurrences,
    slot_instant,
    slot_key,
)
from .oracle_duration import try_parse_duration
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


def _dateless_unchanged_errors(
    before: list[Component], after: list[Component], skip_uids: set[str] | None = None
) -> list[str]:
    b_dl, a_dl = dateless_items(before), dateless_items(after)
    skip = skip_uids or set()
    return [
        f"dateless component {k} changed"
        for k in sorted(set(b_dl) | set(a_dl))
        if k[0] not in skip and b_dl.get(k) != a_dl.get(k)
    ]


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
    errors.extend(_dateless_unchanged_errors(t.before, t.after))
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
    errors.extend(_dateless_unchanged_errors(t.before, t.after))
    if target in after:
        errors.append(f"deleted occurrence {target} is still on the timeline")
    return errors


def _taf_prior_errors(
    uid: str,
    split: datetime.datetime,
    before: OccurrenceMap,
    after: OccurrenceMap,
    forbid_gained_prior: bool,
) -> list[str]:
    errors: list[str] = []
    for key, occ in sorted(before.items()):
        if key[0] == uid and occ.slot < split:
            if key not in after:
                errors.append(f"prior occurrence {key} disappeared")
            elif after[key].comparable() != occ.comparable():
                errors.append(f"prior occurrence {key} changed")
    if forbid_gained_prior:
        for key, occ in sorted(after.items()):
            if key[0] == uid and occ.slot < split and key not in before:
                errors.append(f"phantom prior occurrence {key} gained")
    return errors


def taf_preserves_prior_occurrences(t: Transition) -> list[str]:
    """A THIS_AND_FUTURE edit/delete preserves prior occurrences and deletes future ones."""
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
        return [f"cannot resolve split recurrence_id {t.operation['recurrence_id']!r}"]
    before, after = maps
    has_prior = any(k[0] == uid and occ.slot < split for k, occ in before.items())
    forbid_gained = t.operation.get("op") == "delete" or has_prior
    errors = _taf_prior_errors(uid, split, before, after, forbid_gained)
    if t.operation.get("op") == "delete":
        errors.extend(
            f"future occurrence {key} survived THIS_AND_FUTURE delete"
            for key, occ in sorted(after.items())
            if key[0] == uid and occ.slot >= split
        )
    return errors


def taf_metadata_edit_preserves_slots(t: Transition) -> list[str]:
    """A metadata-only THIS_AND_FUTURE edit preserves the multiset of occurrence slots."""
    if not _applies(t, "edit", "THIS_AND_FUTURE"):
        return []
    if set(t.operation.get("patch") or {}) & SCHEDULE_PATCH_KEYS:
        return []
    maps = _expand_both(t)
    if isinstance(maps, str):
        return [maps]
    uid = str(t.operation["uid"])
    new_uids = _uids(t.after) - _uids(t.before)
    before = Counter(o.slot for k, o in maps[0].items() if k[0] == uid)
    after = Counter(
        o.slot for k, o in maps[1].items() if k[0] == uid or k[0] in new_uids
    )
    errors = [f"slot {s.isoformat()} lost" for s in sorted((before - after).elements())]
    errors += [
        f"slot {s.isoformat()} gained or duplicated"
        for s in sorted((after - before).elements())
    ]
    return errors


def _persisting(t: Transition) -> list[tuple[Component, Component]]:
    before = {identity_key(c, t.before): c for c in items(t.before)}
    return [
        (before[key], comp)
        for comp in items(t.after)
        if (key := identity_key(comp, t.after)) in before
    ]


_RFC5546_TEMPORAL_SCALARS = ("dtstart", "dtend", "due")
_RFC5546_TEMPORAL_LISTS = ("rdate", "exdate")


def _norm_temporal_val(raw: Any, field: str) -> Any:
    if raw is None:
        return None
    pt = try_parse(raw, field)
    if pt is None:
        return str(raw)
    return (pt.is_date, pt.kind, pt.tzid, pt.dt_utc_or_naive)


def _norm_rrule_val(raw: Any) -> Any:
    if not raw or not isinstance(raw, str):
        return raw or None
    norm: list[tuple[str, Any]] = []
    for k, v in sorted(rrule_parts(raw).items()):
        if k == "UNTIL":
            norm.append((k, _norm_temporal_val(v, "until")))
        elif "," in v:
            norm.append((k, tuple(sorted(v.upper().split(",")))))
        else:
            norm.append((k, v.upper()))
    return tuple(norm)


def _norm_duration_val(raw: Any) -> Any:
    if not raw:
        return None
    dur = try_parse_duration(raw)
    return dur.delta if dur is not None else raw


def _rfc5546_must_bump_changed(old: Component, new: Component) -> list[str]:
    """Return RFC 5546 Section 2.1.4 properties whose value changed between old and new."""
    changed = [
        k
        for k in _RFC5546_TEMPORAL_SCALARS
        if _norm_temporal_val(old.get(k), k) != _norm_temporal_val(new.get(k), k)
    ]
    for k in _RFC5546_TEMPORAL_LISTS:
        old_vals = sorted(_norm_temporal_val(x, k) for x in (old.get(k) or ()))
        new_vals = sorted(_norm_temporal_val(x, k) for x in (new.get(k) or ()))
        if old_vals != new_vals:
            changed.append(k)
    if _norm_duration_val(old.get("duration")) != _norm_duration_val(
        new.get("duration")
    ):
        changed.append("duration")
    if _norm_rrule_val(old.get("rrule")) != _norm_rrule_val(new.get("rrule")):
        changed.append("rrule")
    if (old.get("status") or None) != (new.get("status") or None):
        changed.append("status")
    return changed


def persisting_sequence_and_created(t: Transition) -> list[str]:
    """SEQUENCE is monotonic (strictly increasing on RFC 5546 2.1.4 edits) and CREATED is immutable."""
    errors: list[str] = []
    for old, new in _persisting(t):
        if not t.partial_after or "sequence" in new:
            old_seq = old.get("sequence") or 0
            new_seq = new.get("sequence") or 0
            if new_seq < old_seq:
                errors.append(f"{identity_key(new, t.after)}: sequence decreased")
            elif (
                changed := _rfc5546_must_bump_changed(old, new)
            ) and new_seq <= old_seq:
                errors.append(
                    f"{identity_key(new, t.after)}: sequence not incremented after changing {changed}"
                )
        if old.get("created") is not None and (not t.partial_after or "created" in new):
            if new.get("created") != old["created"]:
                errors.append(f"{identity_key(new, t.after)}: created changed")
    return errors


def persisting_timestamps_monotonic(t: Transition) -> list[str]:
    """DTSTAMP and LAST-MODIFIED never move backwards for a persisting component."""
    errors: list[str] = []
    for old, new in _persisting(t):
        for key in ("dtstamp", "last_modified"):
            if old.get(key) is None or (t.partial_after and key not in new):
                continue
            pt_old, pt_new = try_parse(old[key], key), try_parse(new.get(key), key)
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
    if not has_recurrence(segment):
        errors.append(f"new segment {new_uid!r} is not recurring")
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
    """A non-first split mints a recurring segment linked NEXT/FIRST in the chain."""
    if not _applies(t, "edit", "THIS_AND_FUTURE"):
        return []
    uid = str(t.operation["uid"])
    new_uids = _uids(t.after) - _uids(t.before)
    errors: list[str] = []
    split = slot_instant(t.before, uid, t.operation["recurrence_id"])
    maps = _expand_both(t)
    if not isinstance(maps, str) and split is not None:
        has_prior = any(k[0] == uid and occ.slot < split for k, occ in maps[0].items())
        if has_prior and len(new_uids) != 1:
            errors.append(
                f"non-first THIS_AND_FUTURE edit must create 1 new UID, got {sorted(new_uids)}"
            )
    for new_uid in sorted(new_uids):
        errors.extend(_new_segment_errors(t, new_uid))
    return errors


def failed_operation_is_atomic(t: Transition) -> list[str]:
    """A failed operation leaves the calendar state identical."""
    if t.failed and t.after != t.before:
        return ["failed operation modified the calendar state"]
    return []


def _norm_comp_for_order(comp: Component, uid_map: dict[str, str]) -> Component:
    out = dict(comp)
    if (uid := out.get("uid")) in uid_map:
        out["uid"] = uid_map[str(uid)]
    for key in ("exdate", "rdate"):
        if isinstance(out.get(key), list):
            out[key] = sorted(str(x) for x in out[key])
    if isinstance(out.get("related_to"), list):
        rels = [
            {
                **r,
                "uid": uid_map.get(str(r.get("uid")), r.get("uid")),
                "reltype": str(r.get("reltype") or "PARENT").upper(),
            }
            for r in out["related_to"]
        ]
        out["related_to"] = sorted(
            rels, key=lambda r: (str(r["reltype"]), str(r["uid"]))
        )
    return out


def _canonical(components: list[Component], before_uids: set[str]) -> list[str]:
    minted = sorted(
        _uids(components) - before_uids,
        key=lambda u: (
            (m := main_of(components, u) or {}).get("dtstart") or "",
            m.get("summary") or "",
            u,
        ),
    )
    uid_map = {u: f"<minted-{idx}>" for idx, u in enumerate(minted)}
    return sorted(
        json.dumps(_norm_comp_for_order(c, uid_map), sort_keys=True, default=str)
        for c in components
    )


def order_independent_result(t: Transition) -> list[str]:
    """Permuting the input component order does not change the result."""
    before_uids = _uids(t.before)
    canon_after = _canonical(t.after, before_uids)
    errors: list[str] = []
    for idx, other in enumerate(t.permuted_afters):
        if (other is None) != t.failed:
            errors.append(f"permutation #{idx}: success/failure differs")
        elif other is not None and _canonical(other, before_uids) != canon_after:
            errors.append(f"permutation #{idx}: resulting state differs")
    return errors


_NON_PARENT_RELTYPES = frozenset({"CHILD", "SIBLING", "FIRST", "NEXT"})


def _effective_parent_targets(comp: Component) -> set[str]:
    """Return referenced UIDs whose RELTYPE is PARENT or unrecognized (RFC 5545 3.2.15)."""
    return {
        str(r.get("uid"))
        for r in comp.get("related_to") or ()
        if str(r.get("reltype") or "PARENT").upper() not in _NON_PARENT_RELTYPES
    }


def _parent_descendants(components: list[Component], root_uid: str) -> set[str]:
    descendants: set[str] = set()
    frontier = {root_uid}
    while frontier:
        children = (
            {
                str(c.get("uid"))
                for c in items(components)
                if _effective_parent_targets(c) & frontier
            }
            - descendants
            - {root_uid}
        )
        descendants |= children
        frontier = children
    return descendants


def _mutable_and_cascadable_uids(
    t: Transition, before_occ: OccurrenceMap
) -> tuple[set[str], set[str]]:
    op = t.operation.get("op")
    if op == "add":
        return {str((t.operation.get("item") or {}).get("uid"))}, set()
    uid = str(t.operation.get("uid"))
    if op == "edit":
        return {uid} | (_uids(t.after) - _uids(t.before)), set()
    if op != "delete":
        return set(), set()
    rid = t.operation.get("recurrence_id")
    split = slot_instant(t.before, uid, rid) if rid is not None else None
    has_prior = split is not None and any(
        k[0] == uid and occ.slot < split for k, occ in before_occ.items()
    )
    whole_uid = (
        rid is None
        or not has_recurrence(main_of(t.before, uid) or {})
        or (op_range(t.operation) == "THIS_AND_FUTURE" and not has_prior)
    )
    return {uid}, (_parent_descendants(t.before, uid) if whole_uid else set())


def unrelated_uids_unchanged(t: Transition) -> list[str]:
    """Unrelated UIDs (and non-cascaded relatives) have identical occurrences and content."""
    if t.failed:
        return []
    maps = _expand_both(t)
    if isinstance(maps, str):
        return [maps]
    before_occ, after_occ = maps
    mutable, cascadable = _mutable_and_cascadable_uids(t, before_occ)
    after_uids = _uids(t.after)
    removed_cascade = {u for u in cascadable if u not in after_uids}
    skip_uids = mutable | removed_cascade
    skip_keys = {k for k in (set(before_occ) | set(after_occ)) if k[0] in skip_uids}
    errors = _diff_others(before_occ, after_occ, skip_keys)
    errors.extend(_dateless_unchanged_errors(t.before, t.after, skip_uids))
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
    "unrelated_uids_unchanged": unrelated_uids_unchanged,
}
