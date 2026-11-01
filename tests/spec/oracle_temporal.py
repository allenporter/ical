"""Clean-room Temporal Parsing, Formatting, and Recurrence Expansion Engine.

Implements RFC 5545 / RFC 8984 temporal representations, timezone alignment,
DST-safe duration/shift arithmetic, and recurrence candidate expansion
(R-L1-001, R-L1-002, R-L1-003, R-L1-004, R-L1-005, R-L1-006, R-L1-007)
using ONLY the Python standard library and `dateutil.rrule`.
"""

from __future__ import annotations

import datetime
import itertools
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import rrule as du_rrule

from .oracle_policy import PolicyConfig as PolicyConfig, StoreError

MAX_OCCURRENCES = 2000


IANA_BRACKET_RE = re.compile(
    r"^(?P<iso>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?P<offset>[+-]\d{2}:\d{2}|Z))\[(?P<tzid>[^\]]+)\]$"
)
ICAL_PROP_TZID_RE = re.compile(
    r"^(?:(?P<prop>DTSTART|DTEND|DUE|RECURRENCE-ID);)?TZID=(?P<tzid>[^:]+):(?P<val>\d{8}(?:T\d{6})?)$"
)
COMPACT_DT_RE = re.compile(r"^(?P<val>\d{8}(?:T\d{6})?)(?P<utc>Z)?$")


def attach_zone_folding_gaps(
    naive: datetime.datetime, tz: ZoneInfo
) -> datetime.datetime:
    """Attach ZoneInfo to a naive wall-clock datetime, folding non-existent DST gap times forward."""
    return naive.replace(tzinfo=tz).astimezone(datetime.timezone.utc).astimezone(tz)


class ParsedTemporal:
    """Represents a parsed DATE or DATE-TIME with full timezone and offset metadata."""

    def __init__(
        self,
        raw: str,
        value: datetime.date | datetime.datetime,
        is_date: bool,
        kind: str,  # "DATE", "FLOATING", "UTC", "TZID", "OFFSET"
        tzid: str | None = None,
        prop_prefix: str | None = None,
    ) -> None:
        self.raw = raw
        self.value = value
        self.is_date = is_date
        self.kind = kind
        self.tzid = tzid
        self.prop_prefix = prop_prefix

    @property
    def dt_utc_or_naive(self) -> datetime.datetime:
        """Return a comparable UTC or naive datetime for chronological sorting (R-L2-008)."""
        if self.is_date and not isinstance(self.value, datetime.datetime):
            return datetime.datetime(
                self.value.year, self.value.month, self.value.day, 0, 0, 0
            )
        assert isinstance(self.value, datetime.datetime)
        if self.value.tzinfo is not None:
            return self.value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return self.value


def temporal_class(pt: ParsedTemporal) -> str:
    """Classify a ParsedTemporal into DATE, FLOATING, or AWARE (R-L1-004)."""
    return pt.kind if pt.kind in ("DATE", "FLOATING") else "AWARE"


def compute_temporal_duration(
    pt_start: ParsedTemporal, pt_end: ParsedTemporal
) -> datetime.timedelta:
    """Compute physical elapsed duration between two ParsedTemporals across DST boundaries."""
    if pt_start.is_date and pt_end.is_date:
        return pt_end.value - pt_start.value  # type: ignore[operator]
    return pt_end.dt_utc_or_naive - pt_start.dt_utc_or_naive


def add_temporal_duration(
    val: datetime.date | datetime.datetime,
    dur: datetime.timedelta,
    min_days: int = 0,
) -> datetime.date | datetime.datetime:
    """Add physical elapsed duration safely across ZoneInfo DST transitions and DATE bounds."""
    if not isinstance(val, datetime.datetime):
        return val + datetime.timedelta(days=max(min_days, dur.days))
    if val.tzinfo is not None:
        return (val.astimezone(datetime.timezone.utc) + dur).astimezone(val.tzinfo)
    return val + dur


def compute_wall_clock_delta(
    pt_old: ParsedTemporal, pt_new: ParsedTemporal
) -> datetime.timedelta:
    """Compute wall-clock shift between two same-value-type ParsedTemporals."""
    if pt_old.is_date and pt_new.is_date:
        return pt_new.value - pt_old.value  # type: ignore[operator]
    assert isinstance(pt_old.value, datetime.datetime)
    assert isinstance(pt_new.value, datetime.datetime)
    return pt_new.value.replace(tzinfo=None) - pt_old.value.replace(tzinfo=None)


def shift_wall_clock(
    val: datetime.date | datetime.datetime,
    wall_delta: datetime.timedelta,
) -> datetime.date | datetime.datetime:
    """Shift a date or datetime in local wall-clock coordinates, folding DST gaps cleanly."""
    if not isinstance(val, datetime.datetime):
        return val + datetime.timedelta(days=wall_delta.days)
    shifted_naive = val.replace(tzinfo=None) + wall_delta
    if isinstance(val.tzinfo, ZoneInfo):
        return attach_zone_folding_gaps(shifted_naive, val.tzinfo)
    if val.tzinfo is not None:
        return shifted_naive.replace(tzinfo=val.tzinfo)
    return shifted_naive


def _parse_tzid_temporal(raw: str) -> ParsedTemporal | None:
    """Parse an IANA bracketed or iCalendar TZID=... temporal string (preserving fold=0/1)."""
    if m_iana := IANA_BRACKET_RE.match(raw):
        iso_part = m_iana.group("iso")
        tzid = m_iana.group("tzid")
        try:
            tz = ZoneInfo(tzid)
        except ZoneInfoNotFoundError as exc:
            raise StoreError(f"Unknown IANA timezone {tzid!r} in {raw!r}") from exc
        dt_parsed = datetime.datetime.fromisoformat(iso_part)
        dt_zoned = dt_parsed.astimezone(tz)
        if (
            dt_zoned.replace(tzinfo=None) != dt_parsed.replace(tzinfo=None)
            or dt_zoned.utcoffset() != dt_parsed.utcoffset()
        ):
            expected_off = attach_zone_folding_gaps(
                dt_parsed.replace(tzinfo=None), tz
            ).utcoffset()
            raise StoreError(
                f"UTC offset or nonexistent local time mismatch in {raw!r}: "
                f"got {dt_parsed.utcoffset()}, expected {expected_off}"
            )
        return ParsedTemporal(raw, dt_zoned, False, "TZID", tzid=tzid)

    if m_ical := ICAL_PROP_TZID_RE.match(raw):
        prop_prefix = m_ical.group("prop")
        tzid = m_ical.group("tzid")
        val = m_ical.group("val")
        try:
            tz = ZoneInfo(tzid)
        except ZoneInfoNotFoundError as exc:
            raise StoreError(f"Unknown IANA timezone {tzid!r} in {raw!r}") from exc
        if "T" in val:
            naive = datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
            zoned = attach_zone_folding_gaps(naive, tz)
            return ParsedTemporal(
                raw, zoned, False, "TZID", tzid=tzid, prop_prefix=prop_prefix
            )
        d_val = datetime.datetime.strptime(val, "%Y%m%d").date()
        return ParsedTemporal(
            raw, d_val, True, "DATE", tzid=tzid, prop_prefix=prop_prefix
        )
    return None


def parse_temporal(raw: str, field_name: str = "") -> ParsedTemporal:
    """Parse a temporal string and validate timezone/offset consistency (R-L1-006, R-L5-005, R-L5-006)."""
    if not isinstance(raw, str) or not raw:
        raise StoreError(f"Invalid temporal value for {field_name}: {raw!r}")

    if (pt_tzid := _parse_tzid_temporal(raw)) is not None:
        return pt_tzid

    if m_compact := COMPACT_DT_RE.match(raw):
        val = m_compact.group("val")
        is_utc = bool(m_compact.group("utc"))
        if "T" in val:
            naive = datetime.datetime.strptime(val, "%Y%m%dT%H%M%S")
            if is_utc:
                return ParsedTemporal(
                    raw, naive.replace(tzinfo=datetime.timezone.utc), False, "UTC"
                )
            return ParsedTemporal(raw, naive, False, "FLOATING")
        if is_utc:
            raise StoreError(f"DATE value cannot have Z suffix: {raw!r}")
        d_val = datetime.datetime.strptime(val, "%Y%m%d").date()
        return ParsedTemporal(raw, d_val, True, "DATE")

    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return ParsedTemporal(raw, datetime.date.fromisoformat(raw), True, "DATE")

    try:
        dt_parsed = datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise StoreError(f"Malformed temporal value for {field_name}: {raw!r}") from exc
    if raw.endswith("Z"):
        return ParsedTemporal(
            raw, dt_parsed.astimezone(datetime.timezone.utc), False, "UTC"
        )
    if dt_parsed.tzinfo is not None:
        return ParsedTemporal(raw, dt_parsed, False, "OFFSET")
    return ParsedTemporal(raw, dt_parsed, False, "FLOATING")


def format_canonical_rid(pt: ParsedTemporal) -> str:
    """Format a ParsedTemporal into canonical compact RECURRENCE-ID string (R-L1-005, R-L1-007)."""
    if pt.is_date and not isinstance(pt.value, datetime.datetime):
        return pt.value.strftime("%Y%m%d")
    assert isinstance(pt.value, datetime.datetime)
    if pt.kind == "UTC":
        return pt.value.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return pt.value.strftime("%Y%m%dT%H%M%S")


def format_temporal_like(
    target_val: datetime.date | datetime.datetime,
    reference_pt: ParsedTemporal,
    use_ical_prop: str | None = None,
) -> str:
    """Format a date/datetime value to match the representation of reference_pt (R-L1-004, R-L1-007, R-L5-005)."""
    if reference_pt.is_date or (
        isinstance(target_val, datetime.date)
        and not isinstance(target_val, datetime.datetime)
    ):
        if isinstance(target_val, datetime.datetime):
            target_val = target_val.date()
        return target_val.strftime("%Y-%m-%d")
    assert isinstance(target_val, datetime.datetime)
    if reference_pt.kind == "UTC":
        utc_dt = (
            target_val.astimezone(datetime.timezone.utc)
            if target_val.tzinfo is not None
            else target_val.replace(tzinfo=datetime.timezone.utc)
        )
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if reference_pt.kind == "TZID" and reference_pt.tzid:
        tz = ZoneInfo(reference_pt.tzid)
        zoned_dt = (
            target_val.astimezone(datetime.timezone.utc).astimezone(tz)
            if target_val.tzinfo is not None
            else attach_zone_folding_gaps(target_val, tz)
        )
        if use_ical_prop:
            return f"{use_ical_prop};TZID={reference_pt.tzid}:{zoned_dt.strftime('%Y%m%dT%H%M%S')}"
        return f"{zoned_dt.isoformat()}[{reference_pt.tzid}]"
    return target_val.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def align_rid_to_master(
    rid_raw: str, master_dtstart_pt: ParsedTemporal
) -> ParsedTemporal:
    """Resolve a recurrence_id string against a master/segment DTSTART (R-L1-006, R-L1-007)."""
    pt_rid = parse_temporal(rid_raw, "recurrence_id")
    if pt_rid.is_date != master_dtstart_pt.is_date:
        raise StoreError(
            f"Value type mismatch between recurrence_id {rid_raw!r} and DTSTART {master_dtstart_pt.raw!r} (R-L1-006, R-L1-007)"
        )
    if pt_rid.is_date:
        assert isinstance(pt_rid.value, datetime.date)
        return ParsedTemporal(pt_rid.value.isoformat(), pt_rid.value, True, "DATE")
    assert isinstance(pt_rid.value, datetime.datetime)
    if master_dtstart_pt.kind == "TZID" and master_dtstart_pt.tzid:
        tz = ZoneInfo(master_dtstart_pt.tzid)
        zoned = (
            attach_zone_folding_gaps(pt_rid.value, tz)
            if pt_rid.kind == "FLOATING"
            else pt_rid.value.astimezone(tz)
        )
        return ParsedTemporal(
            f"{zoned.isoformat()}[{master_dtstart_pt.tzid}]",
            zoned,
            False,
            "TZID",
            tzid=master_dtstart_pt.tzid,
        )
    if master_dtstart_pt.kind == "UTC":
        utc_dt = (
            pt_rid.value.replace(tzinfo=datetime.timezone.utc)
            if pt_rid.kind == "FLOATING"
            else pt_rid.value.astimezone(datetime.timezone.utc)
        )
        return ParsedTemporal(
            utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), utc_dt, False, "UTC"
        )
    if pt_rid.kind != "FLOATING":
        raise StoreError(
            f"Timezone-aware recurrence_id {rid_raw!r} cannot target floating DTSTART {master_dtstart_pt.raw!r} (R-L1-006)"
        )
    naive = pt_rid.value.replace(tzinfo=None)
    return ParsedTemporal(naive.isoformat(), naive, False, "FLOATING")


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


def validate_rrule_string(rrule_str: str, pt_start: ParsedTemporal) -> dict[str, str]:
    """Validate COUNT/UNTIL mutual exclusion and UNTIL alignment with DTSTART (R-L1-003, R-L1-007)."""
    parts = dict(p.split("=", 1) for p in rrule_str.split(";") if "=" in p)
    if "FREQ" not in parts:
        raise StoreError(f"RRULE missing FREQ part: {rrule_str!r}")
    if "COUNT" in parts and "UNTIL" in parts:
        raise StoreError(f"RRULE cannot contain both COUNT and UNTIL: {rrule_str!r}")
    if "COUNT" in parts and int(parts["COUNT"]) < 1:
        raise StoreError(f"RRULE COUNT must be >= 1: {rrule_str!r}")
    if "UNTIL" in parts:
        pt_until = parse_temporal(parts["UNTIL"], "UNTIL")
        if pt_start.is_date != pt_until.is_date:
            raise StoreError(
                f"UNTIL value type mismatch with DTSTART: {parts['UNTIL']!r} vs {pt_start.raw!r} (R-L1-003)"
            )
        if not pt_start.is_date:
            if pt_start.kind == "FLOATING" and pt_until.kind != "FLOATING":
                raise StoreError(
                    "UNTIL must be floating when DTSTART is floating (R-L1-003)"
                )
            if pt_start.kind in ("UTC", "TZID") and pt_until.kind != "UTC":
                raise StoreError(
                    "UNTIL must be UTC when DTSTART is UTC or TZID (R-L1-003)"
                )
    return parts


def _safe_rrulestr(rrule_str: str, dtstart: datetime.datetime) -> Any:
    """Parse an RRULE string via dateutil.rrule, converting syntax errors to StoreError."""
    try:
        return du_rrule.rrulestr(rrule_str, dtstart=dtstart)
    except (ValueError, TypeError) as exc:
        raise StoreError(f"Malformed RRULE {rrule_str!r}: {exc}") from exc


def _expand_rrule_occurrences(
    rrule_str: str, pt_start: ParsedTemporal
) -> dict[str, ParsedTemporal]:
    """Expand RRULE occurrences into a map of canonical_rid -> ParsedTemporal."""
    parts = validate_rrule_string(rrule_str, pt_start)
    occurrence_rids: dict[str, ParsedTemporal] = {}

    if pt_start.is_date and not isinstance(pt_start.value, datetime.datetime):
        rrule_clean = ";".join(
            p
            for p in rrule_str.split(";")
            if not p.startswith(("BYSECOND=", "BYMINUTE=", "BYHOUR="))
        )
        dt_seed = datetime.datetime(
            pt_start.value.year, pt_start.value.month, pt_start.value.day
        )
        for dt_occ in itertools.islice(
            _safe_rrulestr(rrule_clean, dt_seed), MAX_OCCURRENCES
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

    assert pt_start.kind == "TZID" and pt_start.tzid is not None
    tz = ZoneInfo(pt_start.tzid)
    naive_seed = pt_start.value.replace(tzinfo=None)
    until_utc: datetime.datetime | None = None
    rrule_for_du = rrule_str
    if "UNTIL" in parts:
        pt_u = parse_temporal(parts["UNTIL"], "UNTIL")
        assert isinstance(pt_u.value, datetime.datetime)
        until_utc = pt_u.value.astimezone(datetime.timezone.utc)
        rrule_for_du = ";".join(
            p for p in rrule_str.split(";") if not p.startswith("UNTIL=")
        )
    for naive_occ in itertools.islice(
        _safe_rrulestr(rrule_for_du, naive_seed), MAX_OCCURRENCES
    ):
        zoned_occ = attach_zone_folding_gaps(naive_occ, tz)
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


def expand_component_candidates(
    comp: dict[str, Any], include_exdates: bool = False
) -> list[tuple[str, ParsedTemporal, datetime.timedelta | None]]:
    """Expand a component's recurrence set (RRULE union RDATE, optionally minus EXDATE) (R-L1-001, R-L1-002)."""
    dtstart_raw = comp.get("dtstart")
    if not dtstart_raw:
        return []
    pt_start = parse_temporal(dtstart_raw, "dtstart")

    duration: datetime.timedelta | None = None
    if end_raw := (comp.get("dtend") or comp.get("due")):
        pt_end = parse_temporal(end_raw, "dtend/due")
        if pt_start.is_date == pt_end.is_date:
            duration = compute_temporal_duration(pt_start, pt_end)

    rrule_str = comp.get("rrule")
    rdate_list = comp.get("rdate") or []
    exdate_list = comp.get("exdate") or []

    occurrence_rids = (
        _expand_rrule_occurrences(rrule_str, pt_start) if rrule_str else {}
    )
    if rdate_list and not rrule_str:
        occurrence_rids[format_canonical_rid(pt_start)] = pt_start
    for rd_raw in rdate_list:
        pt_rd = parse_temporal(rd_raw, "rdate")
        if pt_rd.kind == "OFFSET" or temporal_class(pt_rd) != temporal_class(pt_start):
            raise StoreError(
                f"RDATE kind {pt_rd.kind} does not align with DTSTART kind {pt_start.kind} (R-L1-004)"
            )
        pt_rd_aligned = align_rid_to_master(rd_raw, pt_start)
        occurrence_rids[format_canonical_rid(pt_rd_aligned)] = pt_rd_aligned

    if not rrule_str and not rdate_list:
        occurrence_rids[format_canonical_rid(pt_start)] = pt_start

    if not include_exdates:
        for ex_raw in exdate_list:
            pt_ex = parse_temporal(ex_raw, "exdate")
            if pt_ex.kind == "OFFSET" or temporal_class(pt_ex) != temporal_class(
                pt_start
            ):
                raise StoreError(
                    f"EXDATE kind {pt_ex.kind} does not align with DTSTART kind {pt_start.kind} (R-L1-004)"
                )
            pt_ex_aligned = align_rid_to_master(ex_raw, pt_start)
            occurrence_rids.pop(format_canonical_rid(pt_ex_aligned), None)

    sorted_occs = sorted(occurrence_rids.items(), key=lambda kv: kv[1].dt_utc_or_naive)
    return [(rid, pt, duration) for rid, pt in sorted_occs]
