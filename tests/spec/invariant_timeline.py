"""Independent occurrence expansion used by TRANSITION invariants.

Expands a calendar state into a map keyed by `(UID, occurrence slot)` where the slot is
the canonical RECURRENCE-ID of the occurrence (for an override: its RECURRENCE-ID; for a
generated instance: its own start). This mirrors RFC 5545 Section 3.8.4.4: an instance
is identified by its original start, never by a rescheduled DTSTART. Uses only the
clean-room temporal primitives (no store write paths).
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from .invariant_common import (
    REVISION_KEYS,
    Component,
    has_recurrence,
    is_override,
    items,
    try_parse,
)
from .oracle_policy import StoreError
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    compute_temporal_duration,
    expand_component_candidates,
    format_canonical_rid,
)

_SHAPE_KEYS = frozenset(
    {"uid", "recurrence_id", "dtstart", "dtend", "due", "rrule", "rdate", "exdate"}
)


@dataclasses.dataclass(frozen=True)
class Occurrence:
    """One expanded occurrence: its slot instant, actual start/end, and content."""

    slot: datetime.datetime
    start: datetime.datetime
    end: datetime.datetime | None
    content: tuple[tuple[str, str], ...]

    def comparable(self) -> tuple[Any, ...]:
        """Return everything that defines the occurrence except revision metadata."""
        return (self.start, self.end, self.content)


OccurrenceMap = dict[tuple[str, str], Occurrence]


def _instant(value: datetime.date | datetime.datetime) -> datetime.datetime:
    """Return a naive UTC (or floating) datetime for ordering and equality."""
    if not isinstance(value, datetime.datetime):
        return datetime.datetime(value.year, value.month, value.day)
    if value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value


def _duration(comp: Component) -> datetime.timedelta | None:
    """Return the component's DTSTART-to-DTEND/DUE duration (None if not computable)."""
    pt_s = try_parse(comp.get("dtstart"), "dtstart")
    pt_e = try_parse(comp.get("dtend") or comp.get("due"), "end")
    if pt_s is None or pt_e is None or pt_s.is_date != pt_e.is_date:
        return None
    return compute_temporal_duration(pt_s, pt_e)


def _content(comp: Component) -> tuple[tuple[str, str], ...]:
    """Project a component onto its non-schedule, non-revision properties."""
    return tuple(
        sorted(
            (k, repr(v))
            for k, v in comp.items()
            if k not in REVISION_KEYS and k not in _SHAPE_KEYS
        )
    )


def _occurrence(
    comp: Component,
    slot: ParsedTemporal,
    start: ParsedTemporal,
    dur: datetime.timedelta | None,
) -> Occurrence:
    end = None
    if dur is not None:
        min_days = 0 if comp.get("due") is not None else 1
        end = _instant(add_temporal_duration(start.value, dur, min_days=min_days))
    return Occurrence(
        slot=slot.dt_utc_or_naive,
        start=start.dt_utc_or_naive,
        end=end,
        content=_content(comp),
    )


def _expand_uid(uid: str, comps: list[Component], out: OccurrenceMap) -> None:
    """Expand one UID's generators, then let overrides replace their slots."""
    generators = [c for c in comps if not is_override(c) and c.get("dtstart")]
    generators.sort(key=lambda c: c.get("recurrence_id") is not None)
    ref = try_parse(generators[0]["dtstart"], "dtstart") if generators else None
    for gen in generators:
        dur = _duration(gen)
        for rid, pt, _ in expand_component_candidates(gen, include_exdates=False):
            out[(uid, rid)] = _occurrence(gen, pt, pt, dur)
    for ov in comps:
        if not is_override(ov) or not ov.get("dtstart"):
            continue
        pt_rid = try_parse(ov["recurrence_id"], "recurrence_id")
        pt_start = try_parse(ov["dtstart"], "dtstart")
        if pt_rid is None or pt_start is None:
            raise StoreError(f"unparsable override {ov.get('recurrence_id')!r}")
        if ref is not None and ref.is_date == pt_rid.is_date:
            pt_rid = align_rid_to_master(ov["recurrence_id"], ref)
        out[(uid, format_canonical_rid(pt_rid))] = _occurrence(
            ov, pt_rid, pt_start, _duration(ov)
        )


def expand_occurrences(components: list[Component]) -> OccurrenceMap:
    """Expand every VEVENT/VTODO in a state into `{(uid, slot_key): Occurrence}`.

    Raises StoreError if the state cannot be expanded (an invalid state).
    """
    by_uid: dict[str, list[Component]] = {}
    for comp in items(components):
        by_uid.setdefault(str(comp.get("uid")), []).append(comp)
    out: OccurrenceMap = {}
    for uid, comps in by_uid.items():
        _expand_uid(uid, comps, out)
    return out


def slot_instant(
    components: list[Component], uid: str, raw_rid: str
) -> datetime.datetime | None:
    """Resolve an operation's RECURRENCE-ID to an instant against the UID's main DTSTART."""
    main = next(
        (
            c
            for c in items(components)
            if c.get("uid") == uid
            and c.get("recurrence_id") is None
            and c.get("dtstart")
        ),
        None,
    )
    if main is None:
        return None
    pt_ref = try_parse(main["dtstart"], "dtstart")
    if pt_ref is None:
        return None
    try:
        return align_rid_to_master(raw_rid, pt_ref).dt_utc_or_naive
    except (StoreError, ValueError):
        return None


def slot_key(components: list[Component], uid: str, raw_rid: str) -> str | None:
    """Return the canonical occurrence key an operation's RECURRENCE-ID addresses."""
    gens = [
        c
        for c in items(components)
        if c.get("uid") == uid and not is_override(c) and c.get("dtstart")
    ]
    gens.sort(key=lambda c: (c.get("recurrence_id") is not None, not has_recurrence(c)))
    pt_rid = try_parse(raw_rid, "recurrence_id")
    if pt_rid is None:
        return None
    pt_ref = try_parse(gens[0]["dtstart"], "dtstart") if gens else None
    if pt_ref is not None and pt_ref.is_date == pt_rid.is_date:
        try:
            return format_canonical_rid(align_rid_to_master(raw_rid, pt_ref))
        except (StoreError, ValueError):
            return None
    return format_canonical_rid(pt_rid)
