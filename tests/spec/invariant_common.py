"""Shared types and helpers for the clean-room invariant predicates (`I-*` invariants).

The invariant layer states properties that MUST hold for every calendar state
(`COMPONENT` / `CALENDAR` scope) and for every operation (`TRANSITION` scope),
independently of any particular scenario. Predicates use ONLY the Python standard
library and the clean-room temporal primitives in `oracle_temporal` (which in turn use
only `dateutil`); they never import the reference store's write paths.

Terminology used throughout (and in rule text):

* main component: a VEVENT/VTODO without RECURRENCE-ID.
* override: same UID as a main component, has RECURRENCE-ID, and has neither RRULE
  nor RDATE (draft-ietf-calext-jscalendar-icalendar Section 2.1.2).
* legacy shared-UID segment: a component with RECURRENCE-ID *and* RRULE/RDATE, as
  written by older stores; tolerated only in explicitly flagged legacy input.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .oracle_policy import StoreError
from .oracle_temporal import (
    IANA_BRACKET_RE,
    ICAL_PROP_TZID_RE,
    ParsedTemporal,
    align_rid_to_master,
    format_canonical_rid,
    parse_temporal,
)

Component = dict[str, Any]

# Revision/linkage metadata: excluded when comparing what an occurrence *is*.
REVISION_KEYS = frozenset(
    {"sequence", "dtstamp", "created", "last_modified", "related_to"}
)
# Patch keys that change the schedule (anything else is a metadata-only patch).
SCHEDULE_PATCH_KEYS = frozenset(
    {"dtstart", "dtend", "due", "duration", "rrule", "rdate", "exdate"}
)


@dataclasses.dataclass(frozen=True)
class CheckContext:
    """Context for state (COMPONENT/CALENDAR) checks."""

    # True only for scenario `initial_components` explicitly flagged as legacy input.
    legacy_input: bool = False


@dataclasses.dataclass
class Transition:
    """One operation applied to a calendar state, as seen by TRANSITION invariants."""

    before: list[Component]
    operation: dict[str, Any]
    after: list[Component]
    failed: bool = False
    # True when `after` comes from a scenario vector that may elide unchanged metadata keys.
    partial_after: bool = False
    # Results of applying the same operation to permutations of `before`
    # (None marks a permutation on which the operation failed).
    permuted_afters: list[list[Component] | None] = dataclasses.field(
        default_factory=list
    )


def items(components: list[Component]) -> list[Component]:
    """Return the VEVENT/VTODO components (everything except VTIMEZONE)."""
    return [c for c in components if c.get("type") != "VTIMEZONE"]


def has_recurrence(comp: Component) -> bool:
    """Return True if the component carries an RRULE or a non-empty RDATE."""
    return bool(comp.get("rrule") or comp.get("rdate"))


def is_override(comp: Component) -> bool:
    """Return True for an override: RECURRENCE-ID set and no RRULE/RDATE."""
    return comp.get("recurrence_id") is not None and not has_recurrence(comp)


def is_legacy_segment(comp: Component) -> bool:
    """Return True for a legacy shared-UID segment (RECURRENCE-ID plus RRULE/RDATE)."""
    return comp.get("recurrence_id") is not None and has_recurrence(comp)


def try_parse(raw: Any, field: str = "") -> ParsedTemporal | None:
    """Parse a temporal value, returning None if it is absent or malformed."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return parse_temporal(raw, field)
    except (StoreError, ValueError):
        return None


def extract_raw_tzid(raw: Any) -> str | None:
    """Extract a TZID name from a temporal string even if ZoneInfo validation fails."""
    if not isinstance(raw, str) or not raw:
        return None
    if (pt := try_parse(raw)) is not None and pt.kind == "TZID" and pt.tzid:
        return pt.tzid
    for pattern in (IANA_BRACKET_RE, ICAL_PROP_TZID_RE):
        if m := pattern.match(raw):
            return m.group("tzid")
    return None


def label(comp: Component) -> str:
    """Return a short human-readable identity label for error messages."""
    return f"(uid={comp.get('uid')!r}, recurrence_id={comp.get('recurrence_id')!r})"


def rrule_parts(rrule: str | None) -> dict[str, str]:
    """Split an RRULE value into its NAME=VALUE parts (upper-cased names)."""
    if not rrule:
        return {}
    return {
        k.upper(): v for k, _, v in (p.partition("=") for p in rrule.split(";") if p)
    }


def rel_targets(comp: Component, reltype: str) -> list[str]:
    """Return the UIDs this component links to with the given RELTYPE."""
    return [
        str(r.get("uid"))
        for r in comp.get("related_to") or ()
        if str(r.get("reltype") or "PARENT").upper() == reltype
    ]


def main_of(components: list[Component], uid: str) -> Component | None:
    """Return the main component (no RECURRENCE-ID) for a UID, if any."""
    return next(
        (
            c
            for c in items(components)
            if c.get("uid") == uid and c.get("recurrence_id") is None
        ),
        None,
    )


def rid_key(raw_rid: str, ref_dtstart: str | None) -> str:
    """Canonical RECURRENCE-ID key, aligned to the series DTSTART when possible."""
    pt_ref = try_parse(ref_dtstart, "dtstart")
    pt_rid = try_parse(raw_rid, "recurrence_id")
    if pt_rid is None:
        return str(raw_rid)
    if pt_ref is not None and pt_ref.is_date == pt_rid.is_date:
        try:
            return format_canonical_rid(align_rid_to_master(raw_rid, pt_ref))
        except (StoreError, ValueError):
            pass
    return format_canonical_rid(pt_rid)


def identity_key(comp: Component, components: list[Component]) -> tuple[str, str]:
    """Return the (UID, canonical RECURRENCE-ID) primary key of a component."""
    uid = str(comp.get("uid"))
    rid = comp.get("recurrence_id")
    if rid is None:
        return uid, ""
    main = main_of(components, uid)
    return uid, rid_key(rid, main.get("dtstart") if main else comp.get("dtstart"))


def op_range(operation: dict[str, Any]) -> str:
    """Return the operation's canonical recurrence range (`NONE` or `THIS_AND_FUTURE`)."""
    raw = operation.get("range") or "NONE"
    return "THIS_AND_FUTURE" if raw in ("THIS_AND_FUTURE", "THISANDFUTURE") else raw
