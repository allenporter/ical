"""Clean-room Canonical Component Schema and Validation for ReferenceStore.

Implements canonical VEVENT / VTODO / VTIMEZONE dictionary normalization,
extra-property preservation, temporal constraint checking, and RELATED-TO
validation (R-L1-003, R-L1-004, R-L5-001, R-L5-004..R-L5-009).
"""

from __future__ import annotations

import copy
import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .oracle_policy import StoreError
from .oracle_temporal import (
    ParsedTemporal,
    align_rid_to_master,
    attach_zone_folding_gaps,
    expand_component_candidates,
    format_stored_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_until,
    shift_wall_clock,
    temporal_class,
)

DEFAULT_DTSTAMP = "2025-01-01T00:00:00Z"
CORE_COMPONENT_KEYS = frozenset(
    {
        "type",
        "uid",
        "recurrence_id",
        "summary",
        "dtstart",
        "dtend",
        "due",
        "rrule",
        "rdate",
        "exdate",
        "dtstamp",
        "created",
        "sequence",
        "last_modified",
        "status",
        "completed",
        "related_to",
    }
)


def normalize_range(recurrence_range: str | None) -> str:
    """Validate and normalize recurrence_range to NONE or THIS_AND_FUTURE."""
    if recurrence_range in (None, "NONE"):
        return "NONE"
    if recurrence_range in ("THIS_AND_FUTURE", "THISANDFUTURE"):
        return "THIS_AND_FUTURE"
    raise StoreError(f"Unsupported recurrence_range: {recurrence_range!r}")


def is_parent_relation(rel: dict[str, Any]) -> bool:
    """Return True if a RELATED-TO entry is a PARENT relationship (R-L5-007, R-L5-009)."""
    reltype = str(rel.get("reltype") or "PARENT").upper()
    return reltype not in ("CHILD", "SIBLING", "NEXT", "FIRST")


def validate_related_to(comp_or_patch: dict[str, Any]) -> None:
    """Validate RELATED-TO property constraints, accepting all RELTYPE values (R-L5-009)."""
    for rel in comp_or_patch.get("related_to") or ():
        if not isinstance(rel, dict) or not rel.get("uid"):
            raise StoreError("RELATED-TO entry missing uid (R-L5-009)")


def canonical_temporal_str(raw: str | None, field_name: str) -> str | None:
    """Parse and format a temporal string into canonical ISO / ISO[TZID] / Z form."""
    if raw is None:
        return None
    pt = parse_temporal(raw, field_name)
    if pt.kind == "OFFSET":
        raise StoreError(
            f"Fixed-offset datetime without TZID is invalid for {field_name}: {raw!r} (R-L5-005, R-L5-006)"
        )
    return format_temporal_like(pt.value, pt, use_ical_prop=None)


def _resolve_type_and_defaults(
    src: dict[str, Any], default_type: str | None, is_add: bool
) -> tuple[str, bool]:
    """Determine component type (VEVENT vs VTODO) and apply VTODO dtstart default on add."""
    ctype = src.get("type") or default_type
    if ctype not in (None, "VEVENT", "VTODO"):
        raise StoreError(f"Unsupported component type: {ctype!r}")
    is_todo = ctype == "VTODO" or any(k in src for k in ("due", "status", "completed"))
    if is_add and is_todo and not src.get("dtstart") and src.get("due"):
        pt_due = parse_temporal(src["due"], "due")
        if pt_due.kind == "OFFSET":
            raise StoreError(
                f"Fixed-offset datetime without TZID is invalid for due: {src['due']!r} (R-L5-006)"
            )
        src["dtstart"] = format_temporal_like(
            shift_wall_clock(pt_due.value, datetime.timedelta(days=-1)), pt_due
        )
    return ("VTODO" if is_todo else "VEVENT"), is_todo


def canonicalize_component(
    comp: dict[str, Any],
    *,
    is_add: bool,
    default_type: str | None = None,
    now: str = DEFAULT_DTSTAMP,
) -> dict[str, Any]:
    """Build a complete, canonical VEVENT or VTODO dictionary preserving extra properties."""
    src = copy.deepcopy(comp)
    uid = src.get("uid")
    if not uid or not isinstance(uid, str):
        raise StoreError("Component missing non-empty string uid")
    comp_type, is_todo = _resolve_type_and_defaults(src, default_type, is_add)

    canon_rid: str | None = None
    if src.get("recurrence_id") is not None:
        pt_rid = parse_temporal(src["recurrence_id"], "recurrence_id")
        if pt_rid.kind == "OFFSET":
            raise StoreError(
                f"Invalid fixed-offset recurrence_id: {src['recurrence_id']!r}"
            )
        canon_rid = format_stored_rid(pt_rid)

    dtstamp_val = canonical_temporal_str(
        src.get("dtstamp") or (now if is_add else DEFAULT_DTSTAMP), "dtstamp"
    )
    assert dtstamp_val is not None
    created_raw = src.get("created") or (dtstamp_val if is_add else None)
    seq_val = (
        src["sequence"] if src.get("sequence") is not None else (0 if is_add else None)
    )

    out: dict[str, Any] = {
        "type": comp_type,
        "uid": uid,
        "recurrence_id": canon_rid,
        "summary": src.get("summary"),
        "dtstart": canonical_temporal_str(src.get("dtstart"), "dtstart"),
    }
    if is_todo:
        out["due"] = canonical_temporal_str(src.get("due"), "due")
    else:
        out["dtend"] = canonical_temporal_str(src.get("dtend"), "dtend")
    out["rrule"] = src.get("rrule")
    out["rdate"] = [
        x
        for raw_r in (src.get("rdate") or [])
        if (x := canonical_temporal_str(raw_r, "rdate")) is not None
    ]
    out["exdate"] = [
        x
        for raw_e in (src.get("exdate") or [])
        if (x := canonical_temporal_str(raw_e, "exdate")) is not None
    ]
    out["dtstamp"] = dtstamp_val
    out["created"] = canonical_temporal_str(created_raw, "created")
    out["sequence"] = seq_val
    out["last_modified"] = canonical_temporal_str(
        src.get("last_modified"), "last_modified"
    )
    if is_todo:
        status_val = src.get("status")
        completed_raw = src.get("completed")
        if is_add and status_val == "COMPLETED" and not completed_raw:
            completed_raw = dtstamp_val
        out["status"] = status_val
        out["completed"] = canonical_temporal_str(completed_raw, "completed")
    validate_related_to(src)
    out["related_to"] = [
        {"uid": str(rel["uid"]), "reltype": str(rel.get("reltype") or "PARENT")}
        for rel in (src.get("related_to") or [])
    ]
    for k, v in src.items():
        if k not in CORE_COMPONENT_KEYS:
            out[k] = copy.deepcopy(v)
    return out


def apply_patch_fields_in_place(comp: dict[str, Any], patch: dict[str, Any]) -> None:
    """Apply user-mutable patch fields onto an existing canonical component dictionary."""
    skip = {"dtstamp", "uid", "recurrence_id", "sequence", "created", "last_modified"}
    for k, v in patch.items():
        if k in skip:
            continue
        if k in ("dtstart", "dtend", "due", "completed"):
            comp[k] = canonical_temporal_str(v, k)
        elif k in ("rdate", "exdate"):
            comp[k] = [
                x
                for raw_x in (v or [])
                if (x := canonical_temporal_str(raw_x, k)) is not None
            ]
        elif k == "related_to":
            validate_related_to(patch)
            comp["related_to"] = [
                {"uid": str(r["uid"]), "reltype": str(r.get("reltype") or "PARENT")}
                for r in (v or [])
            ]
        else:
            comp[k] = copy.deepcopy(v)


def align_rrule_until_on_dtstart_change(
    comp: dict[str, Any],
    pt_old_start: ParsedTemporal | None,
    pt_new_start: ParsedTemporal,
) -> None:
    """Align RRULE UNTIL value type and timezone form when DTSTART changes (R-L1-003, R-L1-007)."""
    rrule_parts = dict(p.split("=", 1) for p in comp["rrule"].split(";") if "=" in p)
    pt_u = parse_temporal(rrule_parts["UNTIL"], "until")
    if pt_new_start.is_date and not pt_u.is_date:
        assert isinstance(pt_u.value, datetime.datetime)
        comp["rrule"] = replace_rrule_until(
            comp["rrule"], pt_u.value.date().strftime("%Y%m%d")
        )
    elif not pt_new_start.is_date and pt_u.is_date:
        assert isinstance(pt_new_start.value, datetime.datetime)
        comb_dt = datetime.datetime.combine(pt_u.value, pt_new_start.value.time())
        if pt_new_start.value.tzinfo is not None:
            comb_dt = comb_dt.replace(tzinfo=pt_new_start.value.tzinfo).astimezone(
                datetime.timezone.utc
            )
            new_u_str = comb_dt.strftime("%Y%m%dT%H%M%SZ")
        else:
            new_u_str = comb_dt.strftime("%Y%m%dT%H%M%S")
        comp["rrule"] = replace_rrule_until(comp["rrule"], new_u_str)
    elif not pt_new_start.is_date and not pt_u.is_date:
        assert isinstance(pt_new_start.value, datetime.datetime)
        assert isinstance(pt_u.value, datetime.datetime)
        if pt_new_start.value.tzinfo is not None and pt_u.value.tzinfo is None:
            comb_dt = pt_u.value.replace(tzinfo=pt_new_start.value.tzinfo).astimezone(
                datetime.timezone.utc
            )
            comp["rrule"] = replace_rrule_until(
                comp["rrule"], comb_dt.strftime("%Y%m%dT%H%M%SZ")
            )
        elif pt_new_start.value.tzinfo is None and pt_u.value.tzinfo is not None:
            ref_tz = (
                pt_old_start.value.tzinfo
                if (pt_old_start and isinstance(pt_old_start.value, datetime.datetime))
                else None
            )
            local_u = (
                pt_u.value.astimezone(ref_tz).replace(tzinfo=None)
                if ref_tz
                else pt_u.value.replace(tzinfo=None)
            )
            comp["rrule"] = replace_rrule_until(
                comp["rrule"], local_u.strftime("%Y%m%dT%H%M%S")
            )


def shift_rrule_until_wall_clock(
    rrule_str: str,
    pt_old_ref: ParsedTemporal,
    pt_new_ref: ParsedTemporal,
    wall_delta: datetime.timedelta,
) -> str:
    """Shift RRULE UNTIL by wall_delta in local wall-clock coordinates across DST (R-L3-010, R-L4-009)."""
    rrule_parts = dict(p.split("=", 1) for p in rrule_str.split(";") if "=" in p)
    pt_u = parse_temporal(rrule_parts["UNTIL"], "until")
    if pt_new_ref.is_date:
        shifted_d = shift_wall_clock(pt_u.value, wall_delta)
        return replace_rrule_until(rrule_str, shifted_d.strftime("%Y%m%d"))
    if pt_new_ref.kind == "FLOATING":
        shifted_dt = shift_wall_clock(pt_u.value, wall_delta)
        assert isinstance(shifted_dt, datetime.datetime)
        return replace_rrule_until(rrule_str, shifted_dt.strftime("%Y%m%dT%H%M%S"))
    assert isinstance(pt_u.value, datetime.datetime)
    old_tz = (
        pt_old_ref.value.tzinfo
        if isinstance(pt_old_ref.value, datetime.datetime) and pt_old_ref.value.tzinfo
        else datetime.timezone.utc
    )
    naive_new = pt_u.value.astimezone(old_tz).replace(tzinfo=None) + wall_delta
    if pt_new_ref.kind == "TZID" and pt_new_ref.tzid:
        zoned_new = attach_zone_folding_gaps(naive_new, ZoneInfo(pt_new_ref.tzid))
    else:
        zoned_new = naive_new.replace(tzinfo=datetime.timezone.utc)
    return replace_rrule_until(
        rrule_str,
        zoned_new.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )


def shift_temporal_list_wall_clock(
    values: list[str],
    pt_old_ref: ParsedTemporal,
    pt_new_ref: ParsedTemporal,
    wall_delta: datetime.timedelta,
    field_name: str,
) -> list[str]:
    """Shift a list of EXDATE/RDATE strings by wall_delta in local wall-clock time (R-L3-010, R-L4-009)."""
    shifted: list[str] = []
    for val in values:
        pt_v = parse_temporal(val, field_name)
        pt_aligned = (
            align_rid_to_master(val, pt_old_ref)
            if temporal_class(pt_v) == temporal_class(pt_old_ref)
            else pt_v
        )
        shifted.append(
            format_temporal_like(
                shift_wall_clock(pt_aligned.value, wall_delta), pt_new_ref
            )
        )
    return shifted


def partition_future_dates(
    all_segs: list[dict[str, Any]],
    patch: dict[str, Any],
    key: str,
    split_cmp: datetime.datetime,
    pt_target_start: ParsedTemporal | None = None,
) -> list[str]:
    """Extract canonical future rdate or exdate values >= split_cmp (or explicit patch list)."""
    if key in patch:
        return [
            x
            for raw_x in (patch[key] or [])
            if (x := canonical_temporal_str(raw_x, key)) is not None
        ]
    out: list[str] = []
    for seg in all_segs:
        pt_seg = parse_temporal(seg["dtstart"], "dtstart")
        if pt_target_start is not None and temporal_class(pt_seg) != temporal_class(
            pt_target_start
        ):
            continue
        for val in seg.get(key) or ():
            if align_rid_to_master(val, pt_seg).dt_utc_or_naive >= split_cmp:
                out.append(val)
    return out


def validate_component_state(comp: dict[str, Any]) -> None:
    """Validate temporal bounds, RRULE/RDATE/EXDATE alignment, and RELATED-TO."""
    validate_related_to(comp)
    for t_field in ("dtstart", "dtend", "due", "recurrence_id"):
        if comp.get(t_field) is not None:
            pt_f = parse_temporal(comp[t_field], t_field)
            if pt_f.kind == "OFFSET":
                raise StoreError(
                    f"Fixed-offset datetime without TZID is invalid for {t_field}: {comp[t_field]!r}"
                )
    if comp.get("dtstart"):
        pt_start = parse_temporal(comp["dtstart"], "dtstart")
        if comp.get("dtend") is not None:
            pt_end = parse_temporal(comp["dtend"], "dtend")
            if pt_start.is_date != pt_end.is_date:
                raise StoreError("DTEND value type must match DTSTART")
            if pt_end.dt_utc_or_naive <= pt_start.dt_utc_or_naive:
                raise StoreError("DTEND must be strictly after DTSTART")
        if comp.get("due") is not None:
            pt_due = parse_temporal(comp["due"], "due")
            if pt_start.is_date != pt_due.is_date:
                raise StoreError("DUE value type must match DTSTART")
            if pt_due.dt_utc_or_naive < pt_start.dt_utc_or_naive:
                raise StoreError("DUE must not precede DTSTART")
        expand_component_candidates(comp, include_exdates=False)
    elif comp.get("rrule") or comp.get("rdate"):
        raise StoreError("Recurring component requires dtstart")
