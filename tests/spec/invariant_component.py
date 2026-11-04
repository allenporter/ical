"""Clean-room COMPONENT-scope invariant predicates (`I-C-###`).

Each predicate takes one VEVENT/VTODO component dictionary plus a `CheckContext` and
returns a list of human-readable violations (empty when the invariant holds).
"""

from __future__ import annotations

from collections.abc import Callable
import datetime
import itertools
from typing import Any

from .invariant_common import (
    CheckContext,
    Component,
    label,
    rrule_parts,
    try_parse,
)
from .oracle_duration import try_parse_duration
from .oracle_policy import StoreError
from .oracle_temporal import ParsedTemporal, _safe_rrulestr

ComponentCheck = Callable[[Component, CheckContext], list[str]]


def uid_present(comp: Component, ctx: CheckContext) -> list[str]:
    """Every VEVENT/VTODO has a non-empty UID (RFC 5545 Section 3.6.1 / 3.6.2)."""
    del ctx
    uid = comp.get("uid")
    if isinstance(uid, str) and uid:
        return []
    return [f"component {label(comp)} has no non-empty UID"]


def utc_timestamps(comp: Component, ctx: CheckContext) -> list[str]:
    """DTSTAMP, CREATED, LAST-MODIFIED and COMPLETED are UTC date-times."""
    del ctx
    errors: list[str] = []
    for key in ("dtstamp", "created", "last_modified", "completed"):
        raw = comp.get(key)
        if raw is None:
            continue
        pt = try_parse(raw, key)
        if pt is None or pt.kind != "UTC":
            errors.append(f"{label(comp)}: {key} {raw!r} is not a UTC date-time")
    return errors


def end_xor_duration(comp: Component, ctx: CheckContext) -> list[str]:
    """DTEND/DUE never co-occur with DURATION, and DURATION is positive and valid."""
    del ctx
    raw_dur = comp.get("duration")
    if raw_dur is None:
        return []
    errors = [
        f"{label(comp)}: {key} and duration both present"
        for key in ("dtend", "due")
        if comp.get(key) is not None
    ]
    if comp.get("dtstart") is None:
        errors.append(f"{label(comp)}: duration requires dtstart")
    dur = try_parse_duration(raw_dur)
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    if dur is None or dur.delta <= datetime.timedelta(0):
        errors.append(f"{label(comp)}: invalid or non-positive duration {raw_dur!r}")
    elif pt_s is not None and pt_s.is_date and dur.has_time_part:
        errors.append(
            f"{label(comp)}: DATE dtstart requires day/week duration, got {raw_dur!r}"
        )
    return errors


def end_value_type_matches_start(comp: Component, ctx: CheckContext) -> list[str]:
    """DTEND/DUE have DTSTART's value type and are floating iff DTSTART is floating."""
    del ctx
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    errors: list[str] = []
    for key in ("dtend", "due"):
        pt_e = try_parse(comp.get(key), key)
        if pt_s is None or pt_e is None:
            continue
        if pt_s.is_date != pt_e.is_date:
            errors.append(f"{label(comp)}: {key} value type differs from dtstart")
        elif (pt_s.kind == "FLOATING") != (pt_e.kind == "FLOATING"):
            errors.append(f"{label(comp)}: {key} floating-ness differs from dtstart")
    return errors


def end_after_start(comp: Component, ctx: CheckContext) -> list[str]:
    """DTEND and DUE are strictly later than DTSTART."""
    del ctx
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    errors: list[str] = []
    for key in ("dtend", "due"):
        pt_e = try_parse(comp.get(key), key)
        if pt_s is None or pt_e is None or pt_s.is_date != pt_e.is_date:
            continue
        if (pt_s.kind == "FLOATING") != (pt_e.kind == "FLOATING"):
            continue
        if pt_e.dt_utc_or_naive <= pt_s.dt_utc_or_naive:
            errors.append(
                f"{label(comp)}: {key} {comp[key]!r} is not later than "
                f"dtstart {comp['dtstart']!r}"
            )
    return errors


def recurrence_id_excludes_recurrence_rules(
    comp: Component, ctx: CheckContext
) -> list[str]:
    """A component with RECURRENCE-ID carries no RRULE, RDATE or EXDATE."""
    if comp.get("recurrence_id") is None or ctx.legacy_input:
        return []
    return [
        f"{label(comp)}: has RECURRENCE-ID and non-empty {key}"
        for key in ("rrule", "rdate", "exdate")
        if comp.get(key)
    ]


def until_matches_dtstart(comp: Component, ctx: CheckContext) -> list[str]:
    """RRULE UNTIL has DTSTART's value type; floating iff floating; else UTC."""
    del ctx
    until_raw = rrule_parts(comp.get("rrule")).get("UNTIL")
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    if until_raw is None or pt_s is None:
        return []
    pt_u = try_parse(until_raw, "until")
    if pt_u is None:
        return [f"{label(comp)}: unparsable UNTIL {until_raw!r}"]
    if pt_u.is_date != pt_s.is_date:
        return [f"{label(comp)}: UNTIL {until_raw!r} value type differs from DTSTART"]
    if pt_s.is_date:
        return []
    expected = "FLOATING" if pt_s.kind == "FLOATING" else "UTC"
    if pt_u.kind != expected:
        return [
            f"{label(comp)}: UNTIL {until_raw!r} must be {expected} for a "
            f"{pt_s.kind} DTSTART"
        ]
    return []


def date_start_has_no_time_byparts(comp: Component, ctx: CheckContext) -> list[str]:
    """A DATE DTSTART has no BYHOUR/BYMINUTE/BYSECOND rule parts."""
    del ctx
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    if pt_s is None or not pt_s.is_date:
        return []
    parts = rrule_parts(comp.get("rrule"))
    return [
        f"{label(comp)}: DATE DTSTART with {part} in RRULE"
        for part in ("BYHOUR", "BYMINUTE", "BYSECOND")
        if part in parts
    ]


def count_until_exclusive(comp: Component, ctx: CheckContext) -> list[str]:
    """COUNT and UNTIL never occur in the same RRULE."""
    del ctx
    parts = rrule_parts(comp.get("rrule"))
    if "COUNT" in parts and "UNTIL" in parts:
        return [f"{label(comp)}: RRULE has both COUNT and UNTIL"]
    return []


def sequence_non_negative(comp: Component, ctx: CheckContext) -> list[str]:
    """SEQUENCE, when present, is a non-negative integer."""
    del ctx
    seq = comp.get("sequence")
    if seq is None or (isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0):
        return []
    return [f"{label(comp)}: sequence {seq!r} is not a non-negative integer"]


def _check_recur_list_entry(
    comp: Component, key: str, raw: Any, pt_s: ParsedTemporal
) -> list[str]:
    pt = try_parse(raw, key)
    if pt is None or pt.kind == "OFFSET":
        return [f"{label(comp)}: invalid {key} entry {raw!r}"]
    if pt.is_date != pt_s.is_date or (pt.kind == "FLOATING") != (
        pt_s.kind == "FLOATING"
    ):
        return [
            f"{label(comp)}: {key} entry {raw!r} temporal form differs from dtstart"
        ]
    return []


def exdate_rdate_align_with_dtstart(comp: Component, ctx: CheckContext) -> list[str]:
    """EXDATE and RDATE entries parse cleanly and match DTSTART's temporal class."""
    del ctx
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    errors: list[str] = []
    for key in ("exdate", "rdate"):
        vals = comp.get(key)
        if not vals:
            if vals is not None and not isinstance(vals, list):
                errors.append(f"{label(comp)}: {key} must be a list")
            continue
        if not isinstance(vals, list):
            errors.append(f"{label(comp)}: {key} must be a list")
        elif pt_s is None:
            errors.append(f"{label(comp)}: {key} requires a valid dtstart")
        else:
            for raw in vals:
                errors.extend(_check_recur_list_entry(comp, key, raw, pt_s))
    return errors


def _rrule_syntax_errors(comp: Component) -> list[str]:
    raw = comp.get("rrule")
    if raw is None:
        return []
    if not isinstance(raw, str) or not raw:
        return [f"{label(comp)}: invalid rrule {raw!r}"]
    if try_parse(comp.get("dtstart"), "dtstart") is None:
        return [f"{label(comp)}: rrule requires a valid dtstart"]
    parts = rrule_parts(raw)
    if "FREQ" not in parts or (
        "COUNT" in parts and (not parts["COUNT"].isdigit() or int(parts["COUNT"]) < 1)
    ):
        return [f"{label(comp)}: malformed rrule {raw!r}"]
    stripped = ";".join(
        p
        for p in raw.split(";")
        if p and not p.upper().startswith(("UNTIL=", "COUNT="))
    )
    try:
        list(
            itertools.islice(
                _safe_rrulestr(stripped, datetime.datetime(2025, 1, 1, 9, 0)), 1
            )
        )
    except StoreError as exc:
        return [f"{label(comp)}: {exc}"]
    return []


def component_fields_well_formed(comp: Component, ctx: CheckContext) -> list[str]:
    """Component type, required DTSTART, scalar temporals, and RRULE syntax are valid."""
    del ctx
    errors: list[str] = []
    comp_type = comp.get("type") or "VEVENT"
    if comp_type not in ("VEVENT", "VTODO"):
        errors.append(f"{label(comp)}: unsupported component type {comp_type!r}")
    if comp_type == "VEVENT" and comp.get("dtstart") is None:
        errors.append(f"{label(comp)}: VEVENT requires dtstart")
    for key in ("dtstart", "dtend", "due", "recurrence_id"):
        raw = comp.get(key)
        if raw is None:
            continue
        pt = try_parse(raw, key)
        if pt is None or pt.kind == "OFFSET":
            errors.append(f"{label(comp)}: malformed or fixed-offset {key} {raw!r}")
    errors.extend(_rrule_syntax_errors(comp))
    return errors


COMPONENT_CHECKS: dict[str, ComponentCheck] = {
    "uid_present": uid_present,
    "utc_timestamps": utc_timestamps,
    "end_xor_duration": end_xor_duration,
    "end_value_type_matches_start": end_value_type_matches_start,
    "end_after_start": end_after_start,
    "recurrence_id_excludes_recurrence_rules": recurrence_id_excludes_recurrence_rules,
    "until_matches_dtstart": until_matches_dtstart,
    "date_start_has_no_time_byparts": date_start_has_no_time_byparts,
    "count_until_exclusive": count_until_exclusive,
    "sequence_non_negative": sequence_non_negative,
    "exdate_rdate_align_with_dtstart": exdate_rdate_align_with_dtstart,
    "component_fields_well_formed": component_fields_well_formed,
}
