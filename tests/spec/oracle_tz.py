"""Clean-room Temporal Parsing, Formatting, and Timezone/DST Primitives.

Implements RFC 5545 / RFC 8984 DATE and DATE-TIME parsing, IANA ZoneInfo validation,
PEP 495 DST fold/gap preservation, and wall-clock/physical duration arithmetic
(R-L1-004..R-L1-007, R-L5-005, R-L5-006) using ONLY the Python standard library.
"""

from __future__ import annotations

import datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .oracle_policy import StoreError

IANA_BRACKET_RE = re.compile(
    r"^(?P<iso>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?P<offset>[+-]\d{2}:\d{2}|Z))\[(?P<tzid>[^\]]+)\]$"
)
ICAL_PROP_TZID_RE = re.compile(
    r"^(?:(?P<prop>DTSTART|DTEND|DUE|RECURRENCE-ID);)?TZID=(?P<tzid>[^:]+):(?P<val>\d{8}(?:T\d{6})?)$"
)
COMPACT_DT_RE = re.compile(r"^(?P<val>\d{8}(?:T\d{6})?)(?P<utc>Z)?$")


def is_ambiguous_fold1(dt: datetime.datetime) -> bool:
    """Return True iff dt sits on the second (fold=1) pass of an ambiguous DST fall-back hour."""
    return (
        isinstance(dt.tzinfo, ZoneInfo)
        and dt.fold == 1
        and dt.utcoffset() != dt.replace(fold=0).utcoffset()
    )


def attach_zone_folding_gaps(
    naive: datetime.datetime, tz: ZoneInfo
) -> datetime.datetime:
    """Attach ZoneInfo to a naive wall-clock datetime, folding non-existent DST gap times forward."""
    return naive.replace(tzinfo=tz).astimezone(datetime.timezone.utc).astimezone(tz)


def attach_zone_preserving_fold(
    naive: datetime.datetime, tz: ZoneInfo, fold: int = 0
) -> datetime.datetime:
    """Attach ZoneInfo preserving fold (0/1) on valid times and folding DST gaps forward."""
    cand = naive.replace(tzinfo=tz, fold=fold)
    roundtrip = cand.astimezone(datetime.timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != naive:
        return attach_zone_folding_gaps(naive, tz)
    return roundtrip


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
        return attach_zone_preserving_fold(shifted_naive, val.tzinfo, fold=val.fold)
    if val.tzinfo is not None:
        return shifted_naive.replace(tzinfo=val.tzinfo)
    return shifted_naive


def _strptime_checked(val: str, fmt: str, raw: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(val, fmt)
    except ValueError as exc:
        raise StoreError(f"Malformed calendar date/time in {raw!r}: {exc}") from exc


def _parse_iana_bracket(m_iana: re.Match[str], raw: str) -> ParsedTemporal:
    tzid = m_iana.group("tzid")
    try:
        tz = ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise StoreError(f"Unknown IANA timezone {tzid!r} in {raw!r}") from exc
    try:
        dt_parsed = datetime.datetime.fromisoformat(m_iana.group("iso"))
    except ValueError as exc:
        raise StoreError(f"Malformed ISO datetime in {raw!r}: {exc}") from exc
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


def _parse_tzid_temporal(raw: str) -> ParsedTemporal | None:
    """Parse an IANA bracketed or iCalendar TZID=... temporal string (preserving fold=0/1)."""
    if m_iana := IANA_BRACKET_RE.match(raw):
        return _parse_iana_bracket(m_iana, raw)
    m_ical = ICAL_PROP_TZID_RE.match(raw)
    if m_ical is None:
        return None
    prop_prefix = m_ical.group("prop")
    tzid = m_ical.group("tzid")
    val = m_ical.group("val")
    try:
        tz = ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise StoreError(f"Unknown IANA timezone {tzid!r} in {raw!r}") from exc
    if "T" in val:
        naive = _strptime_checked(val, "%Y%m%dT%H%M%S", raw)
        zoned = attach_zone_folding_gaps(naive, tz)
        return ParsedTemporal(
            raw, zoned, False, "TZID", tzid=tzid, prop_prefix=prop_prefix
        )
    d_val = _strptime_checked(val, "%Y%m%d", raw).date()
    return ParsedTemporal(raw, d_val, True, "DATE", tzid=tzid, prop_prefix=prop_prefix)


def _parse_compact_temporal(m_compact: re.Match[str], raw: str) -> ParsedTemporal:
    val = m_compact.group("val")
    is_utc = bool(m_compact.group("utc"))
    if "T" in val:
        naive = _strptime_checked(val, "%Y%m%dT%H%M%S", raw)
        if is_utc:
            return ParsedTemporal(
                raw, naive.replace(tzinfo=datetime.timezone.utc), False, "UTC"
            )
        return ParsedTemporal(raw, naive, False, "FLOATING")
    if is_utc:
        raise StoreError(f"DATE value cannot have Z suffix: {raw!r}")
    return ParsedTemporal(
        raw, _strptime_checked(val, "%Y%m%d", raw).date(), True, "DATE"
    )


def parse_temporal(raw: str, field_name: str = "") -> ParsedTemporal:
    """Parse a temporal string and validate timezone/offset consistency (R-L1-006, R-L5-005, R-L5-006)."""
    if not isinstance(raw, str) or not raw:
        raise StoreError(f"Invalid temporal value for {field_name}: {raw!r}")
    if (pt_tzid := _parse_tzid_temporal(raw)) is not None:
        return pt_tzid
    if m_compact := COMPACT_DT_RE.match(raw):
        return _parse_compact_temporal(m_compact, raw)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            return ParsedTemporal(raw, datetime.date.fromisoformat(raw), True, "DATE")
        except ValueError as exc:
            raise StoreError(
                f"Malformed temporal value for {field_name}: {raw!r}"
            ) from exc
    try:
        dt_parsed = datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise StoreError(f"Malformed temporal value for {field_name}: {raw!r}") from exc
    if raw.endswith("Z"):
        return ParsedTemporal(
            raw, dt_parsed.astimezone(datetime.timezone.utc), False, "UTC"
        )
    kind = "OFFSET" if dt_parsed.tzinfo is not None else "FLOATING"
    return ParsedTemporal(raw, dt_parsed, False, kind)


def format_canonical_rid(pt: ParsedTemporal) -> str:
    """Format a ParsedTemporal into compact occurrence slot key (R-L1-005, R-L1-007)."""
    if pt.is_date and not isinstance(pt.value, datetime.datetime):
        return pt.value.strftime("%Y%m%d")
    assert isinstance(pt.value, datetime.datetime)
    if pt.kind == "UTC" or (pt.kind == "TZID" and is_ambiguous_fold1(pt.value)):
        return pt.value.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return pt.value.strftime("%Y%m%dT%H%M%S")


def format_stored_rid(pt: ParsedTemporal) -> str:
    """Format a ParsedTemporal as a stored component RECURRENCE-ID preserving TZID/Z (R-L1-007)."""
    if pt.kind == "TZID" and pt.tzid and isinstance(pt.value, datetime.datetime):
        if is_ambiguous_fold1(pt.value):
            return pt.value.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"TZID={pt.tzid}:{pt.value.strftime('%Y%m%dT%H%M%S')}"
    return format_canonical_rid(pt)


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
        d_out = (
            target_val.date()
            if isinstance(target_val, datetime.datetime)
            else target_val
        )
        return d_out.strftime("%Y-%m-%d")
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
