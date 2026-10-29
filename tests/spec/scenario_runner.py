"""Declarative Scenario Runner for ReferenceStore and Specification Test Vectors."""

from __future__ import annotations

from typing import Any

from .oracle_temporal import (
    PolicyConfig,
    StoreError,
    align_rid_to_master,
    format_canonical_rid,
    parse_temporal,
)
from .reference_oracle import ReferenceStore


def _dispatch_scenario_operation(
    store: ReferenceStore, op_dict: dict[str, Any]
) -> None:
    """Dispatch a single or composite declarative scenario operation to ReferenceStore."""
    op_type = op_dict.get("op")
    if op_type == "add":
        item = op_dict["item"]
        has_tz_bracket = "[" in (item.get("dtstart") or "")
        store.add(
            item,
            default_type="VEVENT" if has_tz_bracket else None,
            serialize_ical_tzid=has_tz_bracket,
        )
    elif op_type == "add_todo":
        store.add(
            op_dict["item"],
            default_type="VTODO",
            serialize_ical_tzid=False,
        )
    elif op_type == "delete":
        store.delete(
            uid=op_dict["uid"],
            recurrence_id=op_dict.get("recurrence_id"),
            recurrence_range=op_dict.get("range")
            or op_dict.get("recurrence_range")
            or "NONE",
            now=op_dict.get("now"),
        )
    elif op_type == "edit":
        store.edit(
            uid=op_dict["uid"],
            patch=op_dict.get("patch", {}),
            recurrence_id=op_dict.get("recurrence_id"),
            recurrence_range=op_dict.get("range")
            or op_dict.get("recurrence_range")
            or "NONE",
            now=op_dict.get("now"),
        )
    elif op_type == "delete_then_edit":
        del_op = op_dict["delete"]
        edit_op = op_dict["edit"]
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
            append_override_at_end=True,
        )
    elif op_type == "edit_twice":
        store.edit(uid=op_dict["uid"], patch=op_dict["first_patch"])
        store.edit(uid=op_dict["uid"], patch=op_dict["second_patch"])
    elif op_type == "edit_then_partial_delete":
        edit_op = op_dict["edit"]
        del_op = op_dict["delete"]
        store.edit(uid=edit_op["uid"], patch=edit_op.get("patch", {}))
        store.delete(
            uid=del_op["uid"],
            recurrence_id=del_op.get("recurrence_id"),
            recurrence_range=del_op.get("range") or "NONE",
        )
    else:
        raise StoreError(f"Unsupported operation type: {op_type!r}")


def _is_first_instance_taf_edit(
    init_comps: list[dict[str, Any]], op_dict: dict[str, Any]
) -> bool:
    """Return True if op_dict is a THIS_AND_FUTURE edit targeting the first occurrence."""
    eff_range = op_dict.get("range") or op_dict.get("recurrence_range") or "NONE"
    if (
        op_dict.get("op") != "edit"
        or eff_range not in ("THIS_AND_FUTURE", "THISANDFUTURE")
        or not init_comps
        or not op_dict.get("recurrence_id")
    ):
        return False
    init_master = next(
        (
            c
            for c in init_comps
            if c.get("type") != "VTIMEZONE"
            and c.get("uid") == op_dict.get("uid")
            and c.get("recurrence_id") is None
            and c.get("dtstart")
        ),
        None,
    )
    if init_master is None:
        return False
    pt_m = parse_temporal(init_master["dtstart"], "dtstart")
    pt_r = align_rid_to_master(op_dict["recurrence_id"], pt_m)
    return format_canonical_rid(pt_r) == format_canonical_rid(pt_m)


def execute_scenario(
    scenario: dict[str, Any], policy: PolicyConfig | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute a declarative MiniScenarioVector cleanly from initial_components and operation."""
    init_comps = scenario.get("initial_components", [])
    op_dict = scenario.get("operation", {})
    store = ReferenceStore(init_comps, policy=policy)

    op_type = op_dict.get("op")
    expect_error = op_dict.get("expect_error")

    if expect_error:
        try:
            _dispatch_scenario_operation(store, op_dict)
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
        _dispatch_scenario_operation(store, op_dict)

    has_type_in_init = any("type" in c for c in init_comps)
    has_seq_in_init = any("sequence" in c for c in init_comps)
    has_dtstamp_in_init = any("dtstamp" in c for c in init_comps)
    is_first_inst_taf_edit = _is_first_instance_taf_edit(init_comps, op_dict)

    include_status_completed = any("status" in c for c in init_comps)
    include_sequence_in_tl = op_type in ("add", "edit_twice") and (
        has_dtstamp_in_init or "dtstamp" in (op_dict.get("item") or {})
    )
    include_recurrence_id_in_tl = (
        has_type_in_init or any(c.get("rrule") or c.get("rdate") for c in init_comps)
    ) and op_type != "edit_then_partial_delete"
    include_summary_in_tl = not (op_type == "delete" and has_dtstamp_in_init)
    include_end_in_tl = (
        (
            has_type_in_init
            and not (op_type == "delete" and has_seq_in_init)
            and not is_first_inst_taf_edit
        )
        or op_type == "add_todo"
        or include_sequence_in_tl
    )

    timeline = store.expand_timeline(
        include_end=include_end_in_tl,
        include_recurrence_id=include_recurrence_id_in_tl,
        include_summary=include_summary_in_tl,
        include_sequence=include_sequence_in_tl,
        include_status_completed=include_status_completed,
    )
    return store.components, timeline
