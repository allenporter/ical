"""Clean-room Schedule Shifting, Partitioning, and Truncation Helpers for ReferenceStore.

Implements DST-safe wall-clock shifting for RRULE UNTIL and RDATE/EXDATE lists,
physical/all-day duration preservation, override shifting, and segment truncation
(R-L1-003, R-L1-004, R-L3-003..R-L3-007, R-L3-010, R-L4-004, R-L4-009).
"""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .oracle_canonical import canonical_temporal_list, canonical_temporal_str
from .oracle_duration import coerce_duration_for_date, parse_rfc5545_duration
from .oracle_policy import StoreError
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    attach_zone_folding_gaps,
    compute_temporal_duration,
    compute_until_string,
    compute_wall_clock_delta,
    expand_component_candidates,
    format_canonical_rid,
    format_stored_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_count,
    replace_rrule_until,
    shift_wall_clock,
    temporal_class,
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
        return
    if not pt_new_start.is_date and pt_u.is_date:
        assert isinstance(pt_new_start.value, datetime.datetime)
        comb_dt = datetime.datetime.combine(pt_u.value, pt_new_start.value.time())
        new_u_str = (
            comb_dt.replace(tzinfo=pt_new_start.value.tzinfo)
            .astimezone(datetime.timezone.utc)
            .strftime("%Y%m%dT%H%M%SZ")
            if pt_new_start.value.tzinfo is not None
            else comb_dt.strftime("%Y%m%dT%H%M%S")
        )
        comp["rrule"] = replace_rrule_until(comp["rrule"], new_u_str)
        return
    if pt_new_start.is_date or pt_u.is_date:
        return
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
    elif (
        pt_old_start is not None
        and isinstance(pt_old_start.value, datetime.datetime)
        and pt_old_start.value.tzinfo is not None
        and pt_new_start.value.tzinfo is not None
        and pt_old_start.value.tzinfo != pt_new_start.value.tzinfo
    ):
        comp["rrule"] = shift_rrule_until_wall_clock(
            comp["rrule"], pt_old_start, pt_new_start, datetime.timedelta(0)
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
        return canonical_temporal_list(patch[key], key)
    out: list[str] = []
    for seg in all_segs:
        pt_seg = parse_temporal(seg["dtstart"], "dtstart")
        if pt_target_start is not None and temporal_class(pt_seg) != temporal_class(
            pt_target_start
        ):
            continue
        for val in seg.get(key) or ():
            if align_rid_to_master(val, pt_seg).dt_utc_or_naive >= split_cmp:
                out.append(canonical_temporal_str(val, key) or val)
    return out


def dedup_temporals(values: list[str], pt_ref: ParsedTemporal) -> list[str]:
    """Deduplicate temporal strings by canonical recurrence key aligned to pt_ref."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        pt = parse_temporal(raw, "rdate")
        key = format_canonical_rid(
            align_rid_to_master(raw, pt_ref)
            if temporal_class(pt) == temporal_class(pt_ref)
            else pt
        )
        if key not in seen:
            seen.add(key)
            out.append(raw)
    return out


def adapted_rrule_for_anchor(
    rrule_str: str,
    rem_count: int,
    patch: dict[str, Any],
    pt_split: ParsedTemporal,
    pt_seg_start: ParsedTemporal,
    pt_anchor: ParsedTemporal,
) -> str:
    """Adapt an inherited RRULE (COUNT or UNTIL) for a candidate future segment anchor."""
    if "COUNT=" in rrule_str.upper():
        return replace_rrule_count(rrule_str, rem_count)
    if "UNTIL=" in rrule_str.upper():
        if "dtstart" in patch and temporal_class(pt_split) == temporal_class(pt_anchor):
            wall_delta = compute_wall_clock_delta(pt_split, pt_anchor)
            if wall_delta:
                return shift_rrule_until_wall_clock(
                    rrule_str, pt_seg_start, pt_anchor, wall_delta
                )
        tmp_c = {"rrule": rrule_str}
        align_rrule_until_on_dtstart_change(tmp_c, pt_seg_start, pt_anchor)
        return tmp_c["rrule"]
    return rrule_str


def compute_component_duration(comp: dict[str, Any]) -> datetime.timedelta | None:
    """Compute physical elapsed duration of comp from DURATION or DTEND/DUE across DST."""
    if comp.get("duration") is not None:
        return parse_rfc5545_duration(comp["duration"]).delta
    dtstart_raw = comp.get("dtstart")
    end_raw = comp.get("dtend") or comp.get("due")
    if not dtstart_raw or not end_raw:
        return None
    pt_s = parse_temporal(dtstart_raw, "dtstart")
    pt_e = parse_temporal(end_raw, "dtend/due")
    if pt_s.is_date != pt_e.is_date:
        return None
    return compute_temporal_duration(pt_s, pt_e)


def shift_comp_end_or_due(
    comp: dict[str, Any],
    patch: dict[str, Any],
    orig_dur: datetime.timedelta | None,
) -> None:
    """Shift dtend/due (or coerce duration for DATE) when dtstart changes."""
    if (
        "dtstart" not in patch
        or "dtend" in patch
        or "due" in patch
        or "duration" in patch
        or not comp.get("dtstart")
    ):
        return
    pt_ns = parse_temporal(comp["dtstart"], "dtstart")
    if comp.get("duration") is not None:
        comp["duration"] = coerce_duration_for_date(comp["duration"], pt_ns.is_date)
        return
    end_key = "due" if comp.get("type") == "VTODO" else "dtend"
    if comp.get(end_key) is None or orig_dur is None:
        return
    new_end_v = add_temporal_duration(pt_ns.value, orig_dur, min_days=1)
    comp[end_key] = format_temporal_like(new_end_v, pt_ns)


def shift_override_in_place(
    ov: dict[str, Any],
    wall_delta: datetime.timedelta,
    pt_old_ref: ParsedTemporal,
    pt_new_ref: ParsedTemporal,
) -> bool:
    """Shift override recurrence_id/dtstart/end in wall-clock time; return True if RID gap-folded."""
    if not wall_delta:
        return False
    pt_rid = align_rid_to_master(ov["recurrence_id"], pt_old_ref)
    shifted_rid_val = shift_wall_clock(pt_rid.value, wall_delta)
    was_gap_folded = False
    if (
        isinstance(pt_rid.value, datetime.datetime)
        and isinstance(pt_new_ref.value, datetime.datetime)
        and isinstance(shifted_rid_val, datetime.datetime)
    ):
        expected_naive = pt_rid.value.replace(tzinfo=None) + wall_delta
        if isinstance(pt_new_ref.value.tzinfo, ZoneInfo):
            actual_zoned = (
                shifted_rid_val.astimezone(pt_new_ref.value.tzinfo)
                if shifted_rid_val.tzinfo is not None
                else shifted_rid_val
            )
            was_gap_folded = actual_zoned.replace(tzinfo=None) != expected_naive
    shifted_rid_str = format_temporal_like(shifted_rid_val, pt_new_ref)
    ov["recurrence_id"] = format_stored_rid(
        parse_temporal(shifted_rid_str, "recurrence_id")
    )
    if ov.get("dtstart"):
        orig_dur = compute_component_duration(ov)
        pt_ov_s = parse_temporal(ov["dtstart"], "dtstart")
        ov["dtstart"] = format_temporal_like(
            shift_wall_clock(pt_ov_s.value, wall_delta), pt_ov_s
        )
        pt_ov_ns = parse_temporal(ov["dtstart"], "dtstart")
        if ov.get("duration") is not None:
            ov["duration"] = coerce_duration_for_date(ov["duration"], pt_ov_ns.is_date)
        else:
            for end_k in ("dtend", "due"):
                if ov.get(end_k) is not None and orig_dur is not None:
                    ov[end_k] = format_temporal_like(
                        add_temporal_duration(pt_ov_ns.value, orig_dur, min_days=1),
                        pt_ov_ns,
                    )
    return was_gap_folded


def filter_valid_exdates(comp: dict[str, Any]) -> list[str]:
    """Filter a component's exdate list against its unexcluded candidate set (R-L1-004, R-L4-004)."""
    if not (comp.get("rrule") or comp.get("rdate")) or not comp.get("exdate"):
        return []
    pt_start = parse_temporal(comp["dtstart"], "dtstart")
    valid_rids = {
        rid for rid, _, _ in expand_component_candidates(comp, include_exdates=True)
    }
    kept: list[str] = []
    for ex_raw in comp["exdate"]:
        pt_ex = parse_temporal(ex_raw, "exdate")
        if temporal_class(pt_ex) != temporal_class(pt_start):
            continue
        if format_canonical_rid(align_rid_to_master(ex_raw, pt_start)) in valid_rids:
            kept.append(ex_raw)
    return kept


def _promote_early_rdate_start(
    target_seg: dict[str, Any],
    surviving_rdates: list[str],
    pt_seg_start: ParsedTemporal,
    orig_dur: datetime.timedelta | None,
) -> None:
    """Promote earliest surviving RDATE to DTSTART when original DTSTART >= split_cmp."""
    ordered = sorted(
        surviving_rdates,
        key=lambda rd: align_rid_to_master(rd, pt_seg_start).dt_utc_or_naive,
    )
    pt_first = align_rid_to_master(ordered[0], pt_seg_start)
    target_seg["dtstart"] = format_temporal_like(pt_first.value, pt_seg_start)
    target_seg["rdate"] = ordered[1:]
    end_key = "due" if target_seg.get("type") == "VTODO" else "dtend"
    if target_seg.get(end_key) is not None and orig_dur is not None:
        new_end_v = add_temporal_duration(pt_first.value, orig_dur, min_days=1)
        target_seg[end_key] = format_temporal_like(new_end_v, pt_seg_start)


def truncate_segment_terms(
    target_seg: dict[str, Any],
    pt_split: ParsedTemporal,
    pt_seg_start: ParsedTemporal,
    split_cmp: datetime.datetime,
    *,
    has_surviving_overrides: bool = False,
) -> None:
    """Truncate target_seg's RRULE/RDATE/EXDATE strictly before pt_split without fabricating slots."""
    orig_dur = compute_component_duration(target_seg)
    if rrule_str := target_seg.get("rrule"):
        rrule_pts = [
            pt
            for _, pt, _ in expand_component_candidates(
                {**target_seg, "rdate": []}, include_exdates=True
            )
        ]
        prior_rrule = [pt for pt in rrule_pts if pt.dt_utc_or_naive < split_cmp]
        future_rrule = [pt for pt in rrule_pts if pt.dt_utc_or_naive >= split_cmp]
        if not prior_rrule:
            target_seg["rrule"] = None
        elif future_rrule or (
            "COUNT=" not in rrule_str.upper() and "UNTIL=" not in rrule_str.upper()
        ):
            until_str = compute_until_string(pt_split, pt_seg_start)
            target_seg["rrule"] = replace_rrule_until(rrule_str, until_str)

    surviving_rdates = [
        rd
        for rd in (target_seg.get("rdate") or ())
        if align_rid_to_master(rd, pt_seg_start).dt_utc_or_naive < split_cmp
    ]
    target_seg["rdate"] = surviving_rdates
    if pt_seg_start.dt_utc_or_naive >= split_cmp and surviving_rdates:
        _promote_early_rdate_start(target_seg, surviving_rdates, pt_seg_start, orig_dur)
    if (
        not target_seg.get("rrule")
        and not target_seg.get("rdate")
        and has_surviving_overrides
    ):
        target_seg["rdate"] = [target_seg["dtstart"]]
    target_seg["exdate"] = filter_valid_exdates(target_seg)


def check_single_edit_recurrence_patch(
    patch: dict[str, Any],
    existing_ov: dict[str, Any] | None,
    target_seg: dict[str, Any] | None,
) -> None:
    """Reject non-noop RRULE, RDATE, or EXDATE modifications on a Range=NONE edit."""
    if "rrule" in patch and patch["rrule"] is not None:
        if (
            existing_ov is not None
            or target_seg is None
            or patch["rrule"] != target_seg.get("rrule")
        ):
            raise StoreError(
                "Cannot modify RRULE on a single-instance override (R-L2-007)"
            )
    for list_k in ("rdate", "exdate"):
        if list_k in patch and patch[list_k] is not None:
            canon_list = canonical_temporal_list(patch[list_k], list_k)
            if canon_list and (
                existing_ov is not None
                or target_seg is None
                or canon_list != (target_seg.get(list_k) or [])
            ):
                raise StoreError(
                    f"Cannot set {list_k} on a single-instance override (I-C-006)"
                )


def adjust_first_instance_patch(
    master_comp: dict[str, Any],
    patch: dict[str, Any],
    pt_old_start: ParsedTemporal | None,
    normalized_from_first_instance: bool,
) -> dict[str, Any]:
    """Re-anchor a first-instance THIS_AND_FUTURE dtstart shift when earliest slot is an RDATE < DTSTART."""
    if (
        not normalized_from_first_instance
        or pt_old_start is None
        or "dtstart" not in patch
        or patch["dtstart"] is None
        or "rrule" in patch
    ):
        return patch
    cands = expand_component_candidates(master_comp, include_exdates=True)
    if not cands or cands[0][1].dt_utc_or_naive == pt_old_start.dt_utc_or_naive:
        return patch
    canon_p = canonical_temporal_str(patch["dtstart"], "dtstart")
    assert canon_p is not None
    pt_patch_s = parse_temporal(canon_p, "dtstart")
    if temporal_class(pt_patch_s) != temporal_class(pt_old_start):
        return patch
    delta = compute_wall_clock_delta(cands[0][1], pt_patch_s)
    shifted_master = format_temporal_like(
        shift_wall_clock(pt_old_start.value, delta), pt_patch_s
    )
    return {**patch, "dtstart": shifted_master}
