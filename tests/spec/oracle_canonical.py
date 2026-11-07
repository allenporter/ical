"""Clean-room Canonical Component Schema and Validation for ReferenceStore.

Implements canonical VEVENT / VTODO / VTIMEZONE dictionary normalization,
extra-property preservation, temporal constraint checking, DURATION mutual
exclusion, and RELATED-TO validation (R-L1-003, R-L1-004, R-L5-001, R-L5-004..R-L5-009).
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_duration import canonical_duration_str, parse_rfc5545_duration
from .oracle_policy import StoreError
from .oracle_temporal import (
    ParsedTemporal,
    expand_component_candidates,
    format_stored_rid,
    format_temporal_like,
    parse_temporal,
    shift_wall_clock,
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
        "duration",
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
    rels = comp_or_patch.get("related_to")
    if rels is None:
        return
    if not isinstance(rels, list):
        raise StoreError(f"related_to must be a list, got {rels!r} (R-L5-009)")
    for rel in rels:
        if (
            not isinstance(rel, dict)
            or not isinstance(rel.get("uid"), str)
            or not rel["uid"]
        ):
            raise StoreError("RELATED-TO entry missing non-empty string uid (R-L5-009)")


def canonical_temporal_str(raw: Any, field_name: str) -> str | None:
    """Parse and format a temporal string into canonical ISO / ISO[TZID] / Z form."""
    if raw is None:
        return None
    pt = parse_temporal(raw, field_name)
    if pt.kind == "OFFSET":
        raise StoreError(
            f"Fixed-offset datetime without TZID is invalid for {field_name}: {raw!r} (R-L5-005, R-L5-006)"
        )
    return format_temporal_like(pt.value, pt, use_ical_prop=None)


def canonical_utc_timestamp(raw: Any, field_name: str) -> str | None:
    """Parse and format a required-UTC timestamp (DTSTAMP/CREATED/LAST-MODIFIED/COMPLETED)."""
    if raw is None:
        return None
    pt = parse_temporal(raw, field_name)
    if pt.kind != "UTC":
        raise StoreError(f"{field_name} must be a UTC date-time, got {raw!r} (I-C-002)")
    return format_temporal_like(pt.value, pt, use_ical_prop=None)


def max_utc_timestamp(base_utc: str, *candidates: str | None) -> str:
    """Return the latest UTC timestamp among base_utc and any non-None candidates (I-T-006)."""
    best_str = base_utc
    best_cmp = parse_temporal(base_utc, "dtstamp").dt_utc_or_naive
    for cand in candidates:
        if not cand:
            continue
        pt_c = parse_temporal(cand, "dtstamp")
        if pt_c.dt_utc_or_naive > best_cmp:
            best_cmp = pt_c.dt_utc_or_naive
            best_str = format_temporal_like(pt_c.value, pt_c, use_ical_prop=None)
    return best_str


def canonical_temporal_list(raw_list: Any, field_name: str) -> list[str]:
    """Canonicalize an RDATE or EXDATE list, rejecting non-lists or None items."""
    if raw_list is None:
        return []
    if not isinstance(raw_list, list):
        raise StoreError(f"{field_name} must be a list, got {raw_list!r}")
    out: list[str] = []
    for item in raw_list:
        if item is None:
            raise StoreError(f"{field_name} entry cannot be None")
        canon = canonical_temporal_str(item, field_name)
        assert canon is not None
        out.append(canon)
    return out


def _validate_sequence_value(seq: Any) -> None:
    if seq is not None and (
        not isinstance(seq, int) or isinstance(seq, bool) or seq < 0
    ):
        raise StoreError(f"sequence must be a non-negative integer, got {seq!r}")


def _validate_rrule_type(rrule_val: Any) -> str | None:
    if rrule_val is None:
        return None
    if not isinstance(rrule_val, str) or not rrule_val:
        raise StoreError(f"rrule must be a non-empty string or None, got {rrule_val!r}")
    return rrule_val


def _resolve_type_and_defaults(
    src: dict[str, Any], default_type: str | None, is_add: bool
) -> tuple[str, bool]:
    """Determine component type (VEVENT vs VTODO) and apply VTODO dtstart default on add."""
    ctype = src.get("type") or default_type
    if ctype not in (None, "VEVENT", "VTODO"):
        raise StoreError(f"Unsupported component type: {ctype!r}")
    is_todo = ctype == "VTODO" or (
        ctype is None and any(k in src for k in ("due", "status", "completed"))
    )
    if is_todo and src.get("dtend") is not None:
        raise StoreError("VTODO component cannot carry DTEND")
    if not is_todo and src.get("due") is not None:
        raise StoreError("VEVENT component cannot carry DUE")
    if (
        is_add
        and is_todo
        and not src.get("dtstart")
        and src.get("due")
        and src.get("duration") is None
    ):
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

    dtstamp_val = canonical_utc_timestamp(
        src.get("dtstamp") or (now if is_add else DEFAULT_DTSTAMP), "dtstamp"
    )
    assert dtstamp_val is not None
    created_raw = src.get("created") or (dtstamp_val if is_add else None)
    seq_val = (
        src["sequence"]
        if "sequence" in src and src["sequence"] is not None
        else (0 if is_add else None)
    )
    _validate_sequence_value(seq_val)

    out: dict[str, Any] = {
        "type": comp_type,
        "uid": uid,
        "recurrence_id": canon_rid,
        "summary": src.get("summary"),
        "dtstart": canonical_temporal_str(src.get("dtstart"), "dtstart"),
        ("due" if is_todo else "dtend"): canonical_temporal_str(
            src.get("due" if is_todo else "dtend"), "due" if is_todo else "dtend"
        ),
        "duration": canonical_duration_str(src.get("duration"), "duration"),
        "rrule": _validate_rrule_type(src.get("rrule")),
        "rdate": canonical_temporal_list(src.get("rdate"), "rdate"),
        "exdate": canonical_temporal_list(src.get("exdate"), "exdate"),
        "dtstamp": dtstamp_val,
        "created": canonical_utc_timestamp(created_raw, "created"),
        "sequence": seq_val,
        "last_modified": canonical_utc_timestamp(
            src.get("last_modified"), "last_modified"
        ),
    }
    if is_todo:
        status_val = src.get("status")
        completed_raw = src.get("completed")
        if is_add and status_val == "COMPLETED" and not completed_raw:
            completed_raw = dtstamp_val
        out["status"] = status_val
        out["completed"] = canonical_utc_timestamp(completed_raw, "completed")
    validate_related_to(src)
    out["related_to"] = [
        {"uid": str(rel["uid"]), "reltype": str(rel.get("reltype") or "PARENT")}
        for rel in (src.get("related_to") or [])
    ]
    for k, v in src.items():
        if k not in CORE_COMPONENT_KEYS:
            out[k] = copy.deepcopy(v)
    return out


def _validate_patch_constraints(comp: dict[str, Any], patch: dict[str, Any]) -> None:
    if "type" in patch and patch["type"] != comp.get("type"):
        raise StoreError(
            f"Cannot change component type from {comp.get('type')!r} to {patch['type']!r}"
        )
    is_todo = comp.get("type") == "VTODO"
    if (is_todo and patch.get("dtend") is not None) or (
        not is_todo and patch.get("due") is not None
    ):
        raise StoreError(f"Invalid end/due field for {comp.get('type')}")
    if patch.get("duration") is not None and (
        patch.get("dtend") is not None or patch.get("due") is not None
    ):
        raise StoreError(
            "Cannot specify both dtend/due and duration in patch (I-C-003)"
        )


def _apply_single_patch_field(
    comp: dict[str, Any], patch: dict[str, Any], k: str, v: Any
) -> None:
    if k in ("dtstart", "dtend", "due"):
        comp[k] = canonical_temporal_str(v, k)
        if k in ("dtend", "due") and comp[k] is not None:
            comp["duration"] = None
    elif k == "completed":
        comp[k] = canonical_utc_timestamp(v, k)
    elif k == "duration":
        comp["duration"] = canonical_duration_str(v, "duration")
        if comp["duration"] is not None:
            comp.update({ek: None for ek in ("dtend", "due") if ek in comp})
    elif k == "rrule":
        comp["rrule"] = _validate_rrule_type(v)
    elif k in ("rdate", "exdate"):
        comp[k] = canonical_temporal_list(v, k)
    elif k == "related_to":
        validate_related_to(patch)
        comp["related_to"] = [
            {"uid": str(r["uid"]), "reltype": str(r.get("reltype") or "PARENT")}
            for r in (v or [])
        ]
    else:
        comp[k] = copy.deepcopy(v)


def apply_patch_fields_in_place(comp: dict[str, Any], patch: dict[str, Any]) -> None:
    """Apply user-mutable patch fields onto an existing canonical component dictionary."""
    _validate_patch_constraints(comp, patch)
    skip = {
        "type",
        "dtstamp",
        "uid",
        "recurrence_id",
        "sequence",
        "created",
        "last_modified",
    }
    for k, v in patch.items():
        if k not in skip:
            _apply_single_patch_field(comp, patch, k, v)


def _validate_duration_bounds(
    comp: dict[str, Any], pt_start: ParsedTemporal | None
) -> None:
    if comp.get("duration") is None:
        return
    if comp.get("dtend") is not None or comp.get("due") is not None:
        raise StoreError("Component cannot carry both DTEND/DUE and DURATION (I-C-003)")
    if pt_start is None:
        raise StoreError("DURATION requires DTSTART (I-C-003)")
    dur = parse_rfc5545_duration(comp["duration"], "duration")
    if dur.delta <= datetime.timedelta(0):
        raise StoreError(f"DURATION must be strictly positive: {comp['duration']!r}")
    if pt_start.is_date and dur.has_time_part:
        raise StoreError(
            f"DATE DTSTART requires day/week DURATION, got {comp['duration']!r} (I-C-003)"
        )


def _validate_end_and_duration(
    comp: dict[str, Any], pt_start: ParsedTemporal | None
) -> None:
    """Enforce I-C-003 (DURATION XOR DTEND/DUE), I-C-004 (value/floating match), and I-C-005 (> DTSTART)."""
    _validate_duration_bounds(comp, pt_start)
    for end_field in ("dtend", "due"):
        if comp.get(end_field) is None:
            continue
        pt_e = parse_temporal(comp[end_field], end_field)
        if end_field == "dtend" and pt_start is None:
            raise StoreError("DTEND requires DTSTART")
        if pt_start is not None:
            if pt_start.is_date != pt_e.is_date or (pt_start.kind == "FLOATING") != (
                pt_e.kind == "FLOATING"
            ):
                raise StoreError(
                    f"{end_field.upper()} value type and floating-ness must match DTSTART (I-C-004)"
                )
            if pt_e.dt_utc_or_naive <= pt_start.dt_utc_or_naive:
                raise StoreError(
                    f"{end_field.upper()} must be strictly after DTSTART (I-C-005)"
                )


def validate_component_state(
    comp: dict[str, Any], *, allow_legacy: bool = False
) -> None:
    """Validate temporal bounds, DURATION, RRULE/RDATE/EXDATE alignment, and RELATED-TO."""
    if comp.get("type") not in ("VEVENT", "VTODO"):
        raise StoreError(f"Unsupported component type: {comp.get('type')!r}")
    _validate_sequence_value(comp.get("sequence"))
    validate_related_to(comp)
    for utc_field in ("dtstamp", "created", "last_modified", "completed"):
        canonical_utc_timestamp(comp.get(utc_field), utc_field)
    for t_field in ("dtstart", "dtend", "due", "recurrence_id"):
        if comp.get(t_field) is not None:
            canonical_temporal_str(comp[t_field], t_field)

    if comp["type"] == "VEVENT" and not comp.get("dtstart"):
        raise StoreError("VEVENT component requires DTSTART (I-C-012)")
    if comp.get("recurrence_id") is not None:
        if not comp.get("dtstart"):
            raise StoreError("Override component requires DTSTART (I-K-007)")
        if not allow_legacy and any(comp.get(k) for k in ("rrule", "rdate", "exdate")):
            raise StoreError(
                "Component with RECURRENCE-ID cannot carry RRULE, RDATE, or EXDATE (I-C-006)"
            )

    pt_start = (
        parse_temporal(comp["dtstart"], "dtstart") if comp.get("dtstart") else None
    )
    _validate_end_and_duration(comp, pt_start)
    if pt_start is not None:
        expand_component_candidates(comp, include_exdates=False)
    elif any(comp.get(k) for k in ("rrule", "rdate", "exdate")):
        raise StoreError("Recurring component requires dtstart")
