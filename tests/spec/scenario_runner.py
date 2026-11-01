"""Declarative Scenario Runner and Assertion Projection Layer for Spec Vectors.

Executes `MiniScenarioVector` operations against the clean-room `ReferenceStore`
(using `policy_from_modes(scenario.get("modes"))` when `policy` is omitted) and
projects canonical complete store/timeline outputs onto the concise field subsets
asserted in each rule JSON scenario.
"""

from __future__ import annotations

from typing import Any

from .oracle_policy import PolicyConfig, StoreError, policy_from_modes
from .oracle_temporal import (
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
)
from .reference_oracle import ReferenceStore

_TEMPORAL_SCALAR_KEYS = frozenset(
    {"dtstart", "dtend", "due", "dtstamp", "created", "last_modified", "completed"}
)


def dispatch_scenario_operation(store: ReferenceStore, op_dict: dict[str, Any]) -> None:
    """Dispatch a single or composite declarative scenario operation to ReferenceStore."""
    op_type = op_dict.get("op")
    if op_type == "add":
        store.add(op_dict["item"], default_type=op_dict["item"].get("type"))
    elif op_type == "add_todo":
        store.add(op_dict["item"], default_type="VTODO")
    elif op_type == "delete":
        store.delete(
            uid=op_dict["uid"],
            recurrence_id=op_dict.get("recurrence_id"),
            recurrence_range=op_dict.get("range") or "NONE",
            now=op_dict.get("now"),
        )
    elif op_type == "edit":
        store.edit(
            uid=op_dict["uid"],
            patch=op_dict.get("patch", {}),
            recurrence_id=op_dict.get("recurrence_id"),
            recurrence_range=op_dict.get("range") or "NONE",
            now=op_dict.get("now"),
            new_uid=op_dict.get("new_uid"),
        )
    elif op_type == "expand":
        return  # read-only: only the expanded timeline is asserted (R-L3-009)
    elif op_type == "delete_then_edit":
        del_op, edit_op = op_dict["delete"], op_dict["edit"]
        store.delete(
            uid=del_op["uid"],
            recurrence_id=del_op.get("recurrence_id"),
            recurrence_range=del_op.get("range") or "NONE",
        )
        store.edit(
            uid=edit_op["uid"],
            patch=edit_op.get("patch", {}),
            recurrence_id=edit_op.get("recurrence_id"),
            recurrence_range=edit_op.get("range") or "NONE",
        )
    elif op_type == "edit_twice":
        store.edit(uid=op_dict["uid"], patch=op_dict["first_patch"])
        store.edit(uid=op_dict["uid"], patch=op_dict["second_patch"])
    elif op_type == "edit_then_partial_delete":
        edit_op, del_op = op_dict["edit"], op_dict["delete"]
        store.edit(uid=edit_op["uid"], patch=edit_op.get("patch", {}))
        store.delete(
            uid=del_op["uid"],
            recurrence_id=del_op.get("recurrence_id"),
            recurrence_range=del_op.get("range") or "NONE",
        )
    else:
        raise StoreError(f"Unsupported operation type: {op_type!r}")


def _format_scalar_like_expected(key: str, actual_val: Any, expected_val: Any) -> Any:
    """Format a canonical TZID scalar as wire `PROP;TZID=...` only when expected uses wire syntax."""
    if (
        key in _TEMPORAL_SCALAR_KEYS
        and isinstance(actual_val, str)
        and isinstance(expected_val, str)
    ):
        pt_act = parse_temporal(actual_val, key)
        pt_exp = parse_temporal(expected_val, key)
        if (
            pt_act.kind == "TZID"
            and pt_exp.kind == "TZID"
            and pt_act.tzid == pt_exp.tzid
            and pt_exp.prop_prefix
        ):
            return format_temporal_like(
                pt_act.value, pt_act, use_ical_prop=pt_exp.prop_prefix
            )
    return actual_val


def _project_dict_like_expected(
    actual: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    """Project a canonical component or timeline dict onto the keys present in expected."""
    projected: dict[str, Any] = {}
    for key, exp_val in expected.items():
        if key not in actual:
            continue
        act_val = actual[key]
        if (
            key in ("rdate", "exdate")
            and isinstance(act_val, list)
            and isinstance(exp_val, list)
        ):
            projected[key] = [
                _format_scalar_like_expected("dtstart", a_v, exp_val[i])
                if i < len(exp_val)
                else a_v
                for i, a_v in enumerate(act_val)
            ]
        else:
            projected[key] = _format_scalar_like_expected(key, act_val, exp_val)
    return projected


def _comp_identity_key(comp: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return `(uid, canonical_recurrence_id)` for bijection matching."""
    rid_raw = comp.get("recurrence_id")
    canon_rid = (
        format_canonical_rid(parse_temporal(rid_raw, "recurrence_id"))
        if isinstance(rid_raw, str)
        else None
    )
    return comp.get("uid"), canon_rid


def _project_components(
    actual_components: list[dict[str, Any]],
    expected_components: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Project canonical store components onto expected_components if provided."""
    if expected_components is None:
        return actual_components
    exp_vtz = [c for c in expected_components if c.get("type") == "VTIMEZONE"]
    exp_items = [c for c in expected_components if c.get("type") != "VTIMEZONE"]
    act_vtz = [c for c in actual_components if c.get("type") == "VTIMEZONE"]
    act_items = [c for c in actual_components if c.get("type") != "VTIMEZONE"]

    out: list[dict[str, Any]] = list(act_vtz) if exp_vtz else []
    if len(act_items) != len(exp_items):
        return [*out, *act_items]

    act_keys = [_comp_identity_key(c) for c in act_items]
    exp_keys = [_comp_identity_key(c) for c in exp_items]
    if (
        act_keys != exp_keys
        and len(set(act_keys)) == len(act_keys)
        and set(act_keys) == set(exp_keys)
    ):
        by_key = dict(zip(act_keys, act_items))
        act_items = [by_key[k] for k in exp_keys]

    out.extend(
        _project_dict_like_expected(act_c, exp_c)
        for act_c, exp_c in zip(act_items, exp_items)
    )
    return out


def _project_timeline(
    actual_timeline: list[dict[str, Any]],
    expected_timeline: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Project canonical timeline occurrences onto expected_timeline keys in strict order."""
    if expected_timeline is None or len(actual_timeline) != len(expected_timeline):
        return actual_timeline
    return [
        _project_dict_like_expected(act_occ, exp_occ)
        for act_occ, exp_occ in zip(actual_timeline, expected_timeline)
    ]


def execute_scenario(
    scenario: dict[str, Any], policy: PolicyConfig | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute a declarative MiniScenarioVector against ReferenceStore."""
    init_comps = scenario.get("initial_components", [])
    op_dict = scenario.get("operation", {})
    eff_policy = (
        policy if policy is not None else policy_from_modes(scenario.get("modes"))
    )
    store = ReferenceStore(init_comps, policy=eff_policy)

    expect_error = op_dict.get("expect_error")
    if expect_error:
        try:
            dispatch_scenario_operation(store, op_dict)
        except StoreError as exc:
            if isinstance(expect_error, str) and expect_error not in str(exc):
                raise AssertionError(
                    f"Expected error containing {expect_error!r}, got {str(exc)!r}"
                ) from exc
        else:
            raise AssertionError(
                f"Expected StoreError({expect_error!r}), but operation succeeded"
            )
    else:
        dispatch_scenario_operation(store, op_dict)

    projected_comps = _project_components(
        store.components, scenario.get("expected_components")
    )
    projected_tl = _project_timeline(
        store.expand_timeline(), scenario.get("expected_timeline")
    )
    return projected_comps, projected_tl
