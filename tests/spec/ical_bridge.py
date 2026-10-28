"""Differential Test Bridge Between ical's Calendar/EventStore/TodoStore and ReferenceStore."""

# pylint: disable=duplicate-code,line-too-long

from __future__ import annotations

from collections.abc import Callable
import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.exceptions import StoreError as IcalStoreError
from ical.recur_adapter import merge_and_expand_items
from ical.store import EventStore, TodoStore
from ical.timezone import Timezone
from ical.todo import Todo, TodoStatus
from ical.types import Period, Range, Recur, RelatedTo, RelationshipType

from .reference_oracle import (
    ParsedTemporal,
    PolicyConfig,
    ReferenceStore,
    SeriesEditOverrideMode,
    SingleEditExdateMode,
    StoreError as OracleStoreError,
    ThisAndFutureSplitMode,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
)
from .scenario_runner import _dispatch_scenario_operation

ICAL_POLICY = PolicyConfig(
    series_edit_override_mode=SeriesEditOverrideMode.PROPAGATE_PATCH,
    this_and_future_split_mode=ThisAndFutureSplitMode.SHARED_UID,
    single_edit_exdate_mode=SingleEditExdateMode.LEGACY_DUAL_EXDATE,
)


def parse_dt_for_ical(raw: str | None) -> datetime.date | datetime.datetime | None:
    """Parse a scenario temporal string into a Python date or datetime for ical models."""
    return None if raw is None else parse_temporal(raw).value


def parse_rrule_for_ical(raw: str | None) -> Recur | None:
    """Parse an RRULE string into an ical Recur model."""
    return None if raw is None else Recur.from_rrule(raw)


def parse_related_to_for_ical(raw_list: list[dict[str, Any]] | None) -> list[RelatedTo]:
    """Convert scenario related_to dicts into ical RelatedTo objects."""
    result: list[RelatedTo] = []
    for rel in raw_list or []:
        reltype_str = rel.get("reltype", "PARENT")
        try:
            reltype: Any = RelationshipType(reltype_str)
        except ValueError:
            reltype = reltype_str
        result.append(RelatedTo(uid=rel["uid"], reltype=reltype))
    return result


def dict_to_ical_component(comp: dict[str, Any], default_is_todo: bool = False) -> Any:
    """Build an ical Event or Todo from a scenario component or patch dictionary."""
    ctype = comp.get("type")
    is_todo = (
        ctype == "VTODO"
        or any(k in comp for k in ("due", "status", "completed"))
        or (ctype is None and default_is_todo)
    )
    kwargs: dict[str, Any] = {}
    for str_key in (
        "uid",
        "summary",
        "location",
        "description",
        "recurrence_id",
        "sequence",
    ):
        if str_key in comp and (str_key != "uid" or comp["uid"] is not None):
            kwargs[str_key] = comp[str_key]
    for dt_key in (
        "dtstart",
        "created",
        "last_modified",
        "due" if is_todo else "dtend",
        "completed",
    ):
        if dt_key in comp and (is_todo or dt_key != "completed"):
            kwargs[dt_key] = parse_dt_for_ical(comp[dt_key])
    if is_todo and comp.get("status") is not None:
        kwargs["status"] = TodoStatus(comp["status"])
    if "rrule" in comp:
        kwargs["rrule"] = parse_rrule_for_ical(comp["rrule"])
    for list_key in ("rdate", "exdate"):
        if list_key in comp:
            kwargs[list_key] = [parse_dt_for_ical(x) for x in (comp[list_key] or [])]
    kwargs["dtstamp"] = (
        parse_dt_for_ical(comp["dtstamp"])
        if comp.get("dtstamp") is not None
        else datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    )
    if "related_to" in comp:
        kwargs["related_to"] = parse_related_to_for_ical(comp["related_to"])
    return (Todo if is_todo else Event)(**kwargs)


def _pt_from_ical_dt(
    val: datetime.date | datetime.datetime,
    ref_raw: str | None = None,
) -> ParsedTemporal:
    """Convert an ical date/datetime to a ParsedTemporal for canonical formatting."""
    if isinstance(val, datetime.datetime):
        if val.tzinfo is None:
            return ParsedTemporal(val.isoformat(), val, False, "FLOATING")
        if val.tzinfo == datetime.timezone.utc:
            return ParsedTemporal(val.strftime("%Y-%m-%dT%H:%M:%SZ"), val, False, "UTC")
        tzid = str(val.tzinfo)
        ref_pt = parse_temporal(ref_raw) if ref_raw else None
        prop_prefix = ref_pt.prop_prefix if (ref_pt and ref_pt.kind == "TZID") else None
        template = ParsedTemporal(
            "", val, False, "TZID", tzid=tzid, prop_prefix=prop_prefix
        )
        raw_str = format_temporal_like(val, template, use_ical_prop=prop_prefix)
        return ParsedTemporal(
            raw_str, val, False, "TZID", tzid=tzid, prop_prefix=prop_prefix
        )
    return ParsedTemporal(val.isoformat(), val, True, "DATE")


def format_ical_dt(
    val: datetime.date | datetime.datetime | None,
    ref_raw: str | None = None,
) -> str | None:
    """Format an ical date/datetime to match a reference temporal string style."""
    if val is None:
        return None
    pt = _pt_from_ical_dt(val, ref_raw=ref_raw)
    if ref_raw:
        ref_pt = parse_temporal(ref_raw)
        if ref_pt.is_date == pt.is_date and ref_pt.kind == pt.kind:
            return format_temporal_like(val, ref_pt, use_ical_prop=ref_pt.prop_prefix)
    return pt.raw


def format_ical_rrule(
    rrule: Recur | None,
    dtstart: datetime.date | datetime.datetime | None,
) -> str | None:
    """Format an ical Recur object into an RFC 5545 RRULE string matching oracle format."""
    if rrule is None:
        return None
    rrule_str = rrule.as_rrule_str()
    if (
        rrule.until is not None
        and isinstance(rrule.until, datetime.datetime)
        and isinstance(dtstart, datetime.datetime)
        and dtstart.tzinfo is not None
    ):
        parts = [
            f"{part}Z"
            if (part.startswith("UNTIL=") and not part.endswith("Z"))
            else part
            for part in rrule_str.split(";")
        ]
        rrule_str = ";".join(parts)
    return rrule_str


def canonical_rid_from_ical(
    rid: str | None,
    _dtstart: datetime.date | datetime.datetime | None = None,
) -> str | None:
    """Normalize an ical recurrence_id to canonical YYYYMMDD or YYYYMMDDTHHMMSS[Z]."""
    return (
        None
        if rid is None
        else format_canonical_rid(parse_temporal(rid, "recurrence_id"))
    )


def _serialize_related_to(comp: Event | Todo) -> list[dict[str, str]]:
    """Serialize an ical component's related_to list into plain dicts."""
    return [
        {
            "uid": rel.uid,
            "reltype": (
                rel.reltype.value
                if isinstance(rel.reltype, RelationshipType)
                else str(rel.reltype)
            ),
        }
        for rel in (comp.related_to or [])
    ]


def _serialize_dt_list(
    items: list[Any], ref: dict[str, Any], key: str
) -> list[str | None]:
    """Serialize an rdate or exdate list matching reference temporal formatting."""
    refs = ref.get(key) or []
    default_ref = ref.get("dtstart")
    return [
        format_ical_dt(
            it.start if isinstance(it, Period) else it,
            refs[i] if i < len(refs) else default_ref,
        )
        for i, it in enumerate(items)
    ]


_COMPONENT_SERIALIZERS: dict[str, Callable[[Event | Todo, dict[str, Any]], Any]] = {
    "type": lambda c, _: "VTODO" if isinstance(c, Todo) else "VEVENT",
    "uid": lambda c, _: c.uid,
    "recurrence_id": lambda c, _: canonical_rid_from_ical(c.recurrence_id, c.dtstart),
    "summary": lambda c, _: c.summary,
    "location": lambda c, _: c.location,
    "description": lambda c, _: c.description,
    "dtstart": lambda c, ref: format_ical_dt(c.dtstart, ref.get("dtstart")),
    "dtend": lambda c, ref: (
        format_ical_dt(c.dtend, ref.get("dtend") or ref.get("dtstart"))
        if isinstance(c, Event)
        else None
    ),
    "due": lambda c, ref: (
        format_ical_dt(c.due, ref.get("due") or ref.get("dtstart"))
        if isinstance(c, Todo)
        else None
    ),
    "rrule": lambda c, _: format_ical_rrule(c.rrule, c.dtstart),
    "rdate": lambda c, ref: _serialize_dt_list(c.rdate or [], ref, "rdate"),
    "exdate": lambda c, ref: _serialize_dt_list(c.exdate or [], ref, "exdate"),
    "sequence": lambda c, _: c.sequence,
    "dtstamp": lambda c, ref: format_ical_dt(c.dtstamp, ref.get("dtstamp")),
    "created": lambda c, ref: format_ical_dt(c.created, ref.get("created")),
    "last_modified": lambda c, ref: format_ical_dt(
        c.last_modified, ref.get("last_modified")
    ),
    "status": lambda c, _: (
        c.status.value if (isinstance(c, Todo) and c.status) else None
    ),
    "completed": lambda c, ref: (
        format_ical_dt(c.completed, ref.get("completed"))
        if isinstance(c, Todo)
        else None
    ),
    "related_to": lambda c, _: _serialize_related_to(c),
}


def serialize_ical_component_like_oracle(
    comp: Event | Todo,
    oracle_comp: dict[str, Any],
) -> dict[str, Any]:
    """Project an ical Event or Todo onto the keys and temporal format of oracle_comp."""
    out: dict[str, Any] = {}
    for k in oracle_comp:
        if (k == "dtend" and not isinstance(comp, Event)) or (
            k in ("due", "status", "completed") and not isinstance(comp, Todo)
        ):
            continue
        serializer = _COMPONENT_SERIALIZERS.get(k)
        if serializer is not None:
            out[k] = serializer(comp, oracle_comp)
    return out


def serialize_ical_store_against_oracle(
    cal: Calendar, oracle_components: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Serialize Calendar timezones, events, and todos aligned with oracle_components."""
    result: list[dict[str, Any]] = [
        {"type": "VTIMEZONE", "tz_id": tz.tz_id}
        for tz in cal.timezones
        if any(c.get("type") == "VTIMEZONE" for c in oracle_components)
    ]
    non_vtz_oracle = [c for c in oracle_components if c.get("type") != "VTIMEZONE"]
    ical_items: list[Event | Todo] = [*cal.events, *cal.todos]
    assert len(ical_items) == len(non_vtz_oracle)
    result.extend(
        serialize_ical_component_like_oracle(comp, oracle_comp)
        for comp, oracle_comp in zip(ical_items, non_vtz_oracle)
    )
    return result


def expand_ical_timeline_against_oracle(
    cal: Calendar, oracle_timeline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expand Calendar events or todos into a timeline matching oracle_timeline keys."""
    raw_occurrences: list[Event | Todo] = (
        [s.item for s in merge_and_expand_items(cal.todos, ZoneInfo("UTC"))]
        if (cal.todos and not cal.events)
        else list(cal.timeline)
    )
    assert len(raw_occurrences) == len(oracle_timeline)
    return [
        serialize_ical_component_like_oracle(occ, ref_occ)
        for occ, ref_occ in zip(raw_occurrences, oracle_timeline)
    ]


def parse_range_for_ical(raw_range: str | None) -> Range:
    """Convert a scenario range string into an ical Range enum."""
    return (
        Range.THIS_AND_FUTURE
        if raw_range in ("THIS_AND_FUTURE", "THISANDFUTURE")
        else Range.NONE
    )


def make_dtstamp_fn(now_str: str | None) -> Any:
    """Return a deterministic dtstamp_fn for EventStore/TodoStore."""
    if now_str:
        dt = parse_dt_for_ical(now_str)
        assert isinstance(dt, datetime.datetime)
        return lambda: dt
    return lambda: datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


def setup_ical_calendar(
    initial_components: list[dict[str, Any]],
) -> tuple[Calendar, bool]:
    """Initialize an ical Calendar from scenario initial_components."""
    cal = Calendar()
    is_todo_scenario = False
    for comp_dict in initial_components:
        if comp_dict.get("type") == "VTIMEZONE":
            cal.timezones.append(Timezone.from_tzif(comp_dict["tz_id"]))
            continue
        comp_obj = dict_to_ical_component(comp_dict)
        if isinstance(comp_obj, Todo):
            is_todo_scenario = True
            cal.todos.append(comp_obj)
        else:
            cal.events.append(comp_obj)
    return cal, is_todo_scenario


def _run_ical_op(
    store: EventStore | TodoStore,
    op: dict[str, Any],
    item_dict: dict[str, Any],
    is_todo: bool,
    now_str: str | None,
) -> None:
    """Execute a scenario operation on an ical EventStore or TodoStore."""
    op_type = op.get("op")
    if op_type in ("add", "add_todo"):
        store.add(
            dict_to_ical_component(
                item_dict, default_is_todo=(is_todo or op_type == "add_todo")
            )  # type: ignore[arg-type]
        )
    elif op_type == "delete":
        store.delete(
            uid=op["uid"],
            recurrence_id=op.get("recurrence_id"),
            recurrence_range=parse_range_for_ical(
                op.get("range") or op.get("recurrence_range")
            ),
        )
    elif op_type == "edit":
        patch_dict = dict(op.get("patch") or {})
        if now_str and "dtstamp" not in patch_dict:
            patch_dict["dtstamp"] = now_str
        store.edit(
            uid=op["uid"],
            item=dict_to_ical_component(patch_dict, default_is_todo=is_todo),  # type: ignore[arg-type]
            recurrence_id=op.get("recurrence_id"),
            recurrence_range=parse_range_for_ical(
                op.get("range") or op.get("recurrence_range")
            ),
        )
    elif op_type in ("delete_then_edit", "edit_then_partial_delete"):
        del_info, edit_info = op["delete"], op["edit"]
        del_uid = str(del_info.get("uid") or op["uid"])
        edit_uid = str(edit_info.get("uid") or op["uid"])
        patch_obj = dict_to_ical_component(
            edit_info.get("patch") or {}, default_is_todo=is_todo
        )
        if op_type == "delete_then_edit":
            store.delete(
                uid=del_uid,
                recurrence_id=del_info.get("recurrence_id"),
                recurrence_range=parse_range_for_ical(del_info.get("range")),
            )
        store.edit(
            uid=edit_uid,
            item=patch_obj,  # type: ignore[arg-type]
            recurrence_id=edit_info.get("recurrence_id"),
            recurrence_range=parse_range_for_ical(edit_info.get("range")),
        )
        if op_type == "edit_then_partial_delete":
            store.delete(
                uid=del_uid,
                recurrence_id=del_info.get("recurrence_id"),
                recurrence_range=parse_range_for_ical(del_info.get("range")),
            )
    elif op_type == "edit_twice":
        p1 = op.get("first_patch") or (op.get("first_edit") or {}).get("patch") or {}
        p2 = op.get("second_patch") or (op.get("second_edit") or {}).get("patch") or {}
        store.edit(
            uid=op["uid"], item=dict_to_ical_component(p1, default_is_todo=is_todo)
        )  # type: ignore[arg-type]
        store.edit(
            uid=op["uid"], item=dict_to_ical_component(p2, default_is_todo=is_todo)
        )  # type: ignore[arg-type]


def execute_scenario_on_both(
    scenario: dict[str, Any],
) -> tuple[Calendar, ReferenceStore]:
    """Execute a scenario operation on both ical's Store and ReferenceStore(policy=ICAL_POLICY)."""
    init_comps = scenario.get("initial_components", [])
    op = scenario.get("operation", {})
    op_type = op.get("op")
    expect_error = op.get("expect_error") or scenario.get("expected_error", False)

    cal, is_todo_init = setup_ical_calendar(init_comps)
    oracle = ReferenceStore(init_comps, policy=ICAL_POLICY)

    item_dict = op.get("item") or op.get("component") or op.get("todo") or {}
    is_todo = (
        is_todo_init
        or op_type == "add_todo"
        or item_dict.get("type") == "VTODO"
        or "due" in item_dict
        or "due" in (op.get("patch") or {})
        or "status" in (op.get("patch") or {})
    )
    now_str = (
        op.get("now")
        or item_dict.get("dtstamp")
        or (op.get("patch") or {}).get("dtstamp")
    )
    dtstamp_fn = make_dtstamp_fn(now_str)
    store: EventStore | TodoStore = (
        TodoStore(cal, dtstamp_fn=dtstamp_fn)
        if is_todo
        else EventStore(cal, dtstamp_fn=dtstamp_fn)
    )

    if expect_error:
        with pytest.raises(IcalStoreError):
            _run_ical_op(store, op, item_dict, is_todo, now_str)
        with pytest.raises(OracleStoreError):
            _dispatch_scenario_operation(oracle, op)
    else:
        _run_ical_op(store, op, item_dict, is_todo, now_str)
        _dispatch_scenario_operation(oracle, op)
    return cal, oracle


def assert_step_parity(
    cal: Calendar,
    oracle: ReferenceStore,
    step_label: str,
) -> list[dict[str, Any]]:
    """Assert 1-to-1 component, timeline, and ICS round-trip agreement between ical Calendar and ReferenceStore."""
    actual_comps = serialize_ical_store_against_oracle(cal, oracle.components)
    assert actual_comps == oracle.components, f"[{step_label}] Component mismatch"
    oracle_tl = oracle.expand_timeline()
    actual_tl = expand_ical_timeline_against_oracle(cal, oracle_tl)
    assert actual_tl == oracle_tl, f"[{step_label}] Timeline mismatch"
    roundtrip_cal = IcsCalendarStream.calendar_from_ics(
        IcsCalendarStream.calendar_to_ics(cal)
    )
    rt_tl = expand_ical_timeline_against_oracle(roundtrip_cal, oracle_tl)
    assert rt_tl == oracle_tl, f"[{step_label}] ICS round-trip timeline mismatch"
    return actual_tl
