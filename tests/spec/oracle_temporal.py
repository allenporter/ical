"""Clean-room Temporal & Recurrence Expansion Engine.

Re-exports temporal primitives from `oracle_tz` and implements RRULE validation,
DST-aware recurrence expansion, and component candidate expansion
(R-L1-001, R-L1-002, R-L1-003, R-L1-004, R-L1-005, R-L1-006, R-L1-007)
using ONLY the Python standard library and `dateutil.rrule`.
"""

from __future__ import annotations

import datetime
import itertools
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import rrule as du_rrule

from .oracle_duration import parse_rfc5545_duration
from .oracle_policy import PolicyConfig as PolicyConfig, StoreError
from .oracle_tz import (
    COMPACT_DT_RE,
    IANA_BRACKET_RE,
    ICAL_PROP_TZID_RE,
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    attach_zone_folding_gaps,
    attach_zone_preserving_fold,
    compute_temporal_duration,
    compute_wall_clock_delta,
    format_canonical_rid,
    format_stored_rid,
    format_temporal_like,
    is_ambiguous_fold1,
    parse_temporal,
    shift_wall_clock,
    temporal_class,
)

__all__ = [
    "COMPACT_DT_RE",
    "IANA_BRACKET_RE",
    "ICAL_PROP_TZID_RE",
    "MAX_OCCURRENCES",
    "ParsedTemporal",
    "PolicyConfig",
    "StoreError",
    "_expand_rrule_occurrences",
    "_safe_rrulestr",
    "add_temporal_duration",
    "align_rid_to_master",
    "attach_zone_folding_gaps",
    "attach_zone_preserving_fold",
    "compute_temporal_duration",
    "compute_until_string",
    "compute_wall_clock_delta",
    "expand_component_candidates",
    "format_canonical_rid",
    "format_stored_rid",
    "format_temporal_like",
    "is_ambiguous_fold1",
    "parse_temporal",
    "replace_rrule_count",
    "replace_rrule_until",
    "shift_wall_clock",
    "temporal_class",
    "validate_rrule_string",
]

MAX_OCCURRENCES = 2000


def compute_until_string(
    split_pt: ParsedTemporal, master_dtstart_pt: ParsedTemporal
) -> str:
    """Compute the inclusive UNTIL bound strictly preceding split_pt (R-L1-003, R-L1-007, R-L3-003)."""
    if master_dtstart_pt.is_date:
        assert isinstance(split_pt.value, datetime.date)
        prev_day = split_pt.value - datetime.timedelta(days=1)
        return prev_day.strftime("%Y%m%d")
    assert isinstance(split_pt.value, datetime.datetime)
    if master_dtstart_pt.kind in ("UTC", "TZID"):
        utc_split = split_pt.value.astimezone(datetime.timezone.utc)
        return (utc_split - datetime.timedelta(seconds=1)).strftime("%Y%m%dT%H%M%SZ")
    naive_split = split_pt.value.replace(tzinfo=None)
    return (naive_split - datetime.timedelta(seconds=1)).strftime("%Y%m%dT%H%M%S")


def replace_rrule_until(rrule_str: str, until_str: str) -> str:
    """Truncate an RRULE string by clearing COUNT and setting UNTIL (R-L1-003, R-L3-001, R-L3-003)."""
    parts = [p for p in rrule_str.split(";") if p]
    filtered = [
        p for p in parts if not p.startswith("COUNT=") and not p.startswith("UNTIL=")
    ]
    filtered.append(f"UNTIL={until_str}")
    return ";".join(filtered)


def replace_rrule_count(rrule_str: str, new_count: int) -> str:
    """Update COUNT in an RRULE string for a forked future segment (R-L3-004)."""
    parts = [p for p in rrule_str.split(";") if p]
    return ";".join(
        f"COUNT={new_count}" if p.startswith("COUNT=") else p for p in parts
    )


def _parse_rrule_parts_checked(rrule_str: Any) -> dict[str, str]:
    """Parse NAME=VALUE tokens from an RRULE string, rejecting non-strings and bad tokens."""
    if not isinstance(rrule_str, str) or not rrule_str:
        raise StoreError(f"Invalid RRULE value: {rrule_str!r}")
    parts: dict[str, str] = {}
    for token in rrule_str.split(";"):
        if not token:
            continue
        if "=" not in token:
            raise StoreError(f"Malformed RRULE token {token!r} in {rrule_str!r}")
        k, v = token.split("=", 1)
        if not k or not v:
            raise StoreError(f"Malformed RRULE token {token!r} in {rrule_str!r}")
        parts[k.upper()] = v
    if "FREQ" not in parts:
        raise StoreError(f"RRULE missing FREQ part: {rrule_str!r}")
    if "COUNT" in parts and "UNTIL" in parts:
        raise StoreError(f"RRULE cannot contain both COUNT and UNTIL: {rrule_str!r}")
    if "COUNT" in parts:
        if not parts["COUNT"].isdigit() or int(parts["COUNT"]) < 1:
            raise StoreError(f"RRULE COUNT must be an integer >= 1: {rrule_str!r}")
    return parts


def validate_rrule_string(rrule_str: Any, pt_start: ParsedTemporal) -> dict[str, str]:
    """Validate RRULE syntax, COUNT/UNTIL, DATE BY* restrictions, and UNTIL alignment."""
    parts = _parse_rrule_parts_checked(rrule_str)
    if pt_start.is_date and any(k in parts for k in ("BYHOUR", "BYMINUTE", "BYSECOND")):
        raise StoreError(
            f"DATE DTSTART forbids BYHOUR/BYMINUTE/BYSECOND in RRULE: {rrule_str!r} (I-C-008)"
        )
    if "UNTIL" not in parts:
        return parts
    pt_until = parse_temporal(parts["UNTIL"], "UNTIL")
    if pt_start.is_date != pt_until.is_date:
        raise StoreError(
            f"UNTIL value type mismatch with DTSTART: {parts['UNTIL']!r} vs {pt_start.raw!r} (R-L1-003)"
        )
    if not pt_start.is_date:
        expected = "FLOATING" if pt_start.kind == "FLOATING" else "UTC"
        if pt_until.kind != expected:
            raise StoreError(
                f"UNTIL must be {expected} when DTSTART is {pt_start.kind} (R-L1-003)"
            )
    return parts


def _safe_rrulestr(rrule_str: str, dtstart: datetime.datetime) -> Any:
    """Parse an RRULE string via dateutil.rrule, converting syntax errors to StoreError."""
    try:
        return du_rrule.rrulestr(rrule_str, dtstart=dtstart)
    except (ValueError, TypeError) as exc:
        raise StoreError(f"Malformed RRULE {rrule_str!r}: {exc}") from exc


def _expand_tzid_rrule(
    rrule_str: str, parts: dict[str, str], pt_start: ParsedTemporal
) -> dict[str, ParsedTemporal]:
    """Expand a TZID-qualified RRULE preserving fold=1 and sub-daily physical intervals."""
    assert isinstance(pt_start.value, datetime.datetime) and pt_start.tzid is not None
    tz = ZoneInfo(pt_start.tzid)
    occurrence_rids: dict[str, ParsedTemporal] = {}
    is_pure_subdaily = parts["FREQ"].upper() in (
        "HOURLY",
        "MINUTELY",
        "SECONDLY",
    ) and not any(k in parts for k in ("BYHOUR", "BYMINUTE", "BYSECOND"))
    if is_pure_subdaily:
        utc_seed = pt_start.value.astimezone(datetime.timezone.utc)
        for utc_occ in itertools.islice(
            _safe_rrulestr(rrule_str, utc_seed), MAX_OCCURRENCES
        ):
            zoned_occ = utc_occ.astimezone(tz)
            raw_str = format_temporal_like(
                zoned_occ, pt_start, use_ical_prop=pt_start.prop_prefix
            )
            pt_occ = ParsedTemporal(
                raw_str, zoned_occ, False, "TZID", tzid=pt_start.tzid
            )
            occurrence_rids[format_canonical_rid(pt_occ)] = pt_occ
        return occurrence_rids

    naive_seed = pt_start.value.replace(tzinfo=None)
    until_utc: datetime.datetime | None = None
    rrule_for_du = rrule_str
    if "UNTIL" in parts:
        pt_u = parse_temporal(parts["UNTIL"], "UNTIL")
        assert isinstance(pt_u.value, datetime.datetime)
        until_utc = pt_u.value.astimezone(datetime.timezone.utc)
        rrule_for_du = ";".join(
            p for p in rrule_str.split(";") if not p.upper().startswith("UNTIL=")
        )
    for naive_occ in itertools.islice(
        _safe_rrulestr(rrule_for_du, naive_seed), MAX_OCCURRENCES
    ):
        zoned_occ = attach_zone_preserving_fold(naive_occ, tz, fold=pt_start.value.fold)
        if (
            until_utc is not None
            and zoned_occ.astimezone(datetime.timezone.utc) > until_utc
        ):
            break
        raw_str = format_temporal_like(
            zoned_occ, pt_start, use_ical_prop=pt_start.prop_prefix
        )
        pt_occ = ParsedTemporal(raw_str, zoned_occ, False, "TZID", tzid=pt_start.tzid)
        occurrence_rids[format_canonical_rid(pt_occ)] = pt_occ
    return occurrence_rids


def _expand_rrule_occurrences(
    rrule_str: str, pt_start: ParsedTemporal
) -> dict[str, ParsedTemporal]:
    """Expand RRULE occurrences into a map of canonical_rid -> ParsedTemporal."""
    parts = validate_rrule_string(rrule_str, pt_start)
    occurrence_rids: dict[str, ParsedTemporal] = {}

    if pt_start.is_date and not isinstance(pt_start.value, datetime.datetime):
        dt_seed = datetime.datetime(
            pt_start.value.year, pt_start.value.month, pt_start.value.day
        )
        for dt_occ in itertools.islice(
            _safe_rrulestr(rrule_str, dt_seed), MAX_OCCURRENCES
        ):
            d_occ = dt_occ.date()
            pt_occ = ParsedTemporal(d_occ.isoformat(), d_occ, True, "DATE")
            occurrence_rids[format_canonical_rid(pt_occ)] = pt_occ
        return occurrence_rids

    assert isinstance(pt_start.value, datetime.datetime)
    if pt_start.kind in ("FLOATING", "UTC"):
        for dt_occ in itertools.islice(
            _safe_rrulestr(rrule_str, pt_start.value), MAX_OCCURRENCES
        ):
            raw_occ = (
                dt_occ.strftime("%Y-%m-%dT%H:%M:%SZ")
                if pt_start.kind == "UTC"
                else dt_occ.isoformat()
            )
            pt_occ = ParsedTemporal(raw_occ, dt_occ, False, pt_start.kind)
            occurrence_rids[format_canonical_rid(pt_occ)] = pt_occ
        return occurrence_rids

    return _expand_tzid_rrule(rrule_str, parts, pt_start)


def _resolve_candidate_duration(
    comp: dict[str, Any], pt_start: ParsedTemporal
) -> datetime.timedelta | None:
    if comp.get("duration") is not None:
        return parse_rfc5545_duration(comp["duration"]).delta
    if end_raw := (comp.get("dtend") or comp.get("due")):
        pt_end = parse_temporal(end_raw, "dtend/due")
        if pt_start.is_date == pt_end.is_date:
            return compute_temporal_duration(pt_start, pt_end)
    return None


def _align_recur_entry(
    raw: Any, field_name: str, pt_start: ParsedTemporal
) -> ParsedTemporal:
    pt = parse_temporal(raw, field_name)
    if pt.kind == "OFFSET" or temporal_class(pt) != temporal_class(pt_start):
        raise StoreError(
            f"{field_name.upper()} kind {pt.kind} does not align with DTSTART kind {pt_start.kind} (R-L1-004)"
        )
    return align_rid_to_master(raw, pt_start)


def expand_component_candidates(
    comp: dict[str, Any], include_exdates: bool = False
) -> list[tuple[str, ParsedTemporal, datetime.timedelta | None]]:
    """Expand a component's recurrence set (RRULE union RDATE, optionally minus EXDATE) (R-L1-001, R-L1-002)."""
    dtstart_raw = comp.get("dtstart")
    if not dtstart_raw:
        return []
    pt_start = parse_temporal(dtstart_raw, "dtstart")
    duration = _resolve_candidate_duration(comp, pt_start)

    rrule_str = comp.get("rrule")
    rdate_list = comp.get("rdate") or []
    exdate_list = comp.get("exdate") or []
    if not isinstance(rdate_list, list) or not isinstance(exdate_list, list):
        raise StoreError("rdate and exdate must be lists")

    occurrence_rids = (
        _expand_rrule_occurrences(rrule_str, pt_start) if rrule_str else {}
    )
    if not rrule_str:
        occurrence_rids[format_canonical_rid(pt_start)] = pt_start
    for rd_raw in rdate_list:
        pt_rd = _align_recur_entry(rd_raw, "rdate", pt_start)
        occurrence_rids[format_canonical_rid(pt_rd)] = pt_rd

    for ex_raw in exdate_list:
        pt_ex = _align_recur_entry(ex_raw, "exdate", pt_start)
        if not include_exdates:
            occurrence_rids.pop(format_canonical_rid(pt_ex), None)

    sorted_occs = sorted(occurrence_rids.items(), key=lambda kv: kv[1].dt_utc_or_naive)
    return [(rid, pt, duration) for rid, pt in sorted_occs]
