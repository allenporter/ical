"""Clean-room CALENDAR-scope invariant predicates (`I-K-###`).

Each predicate takes a full list of calendar components (VEVENT, VTODO and VTIMEZONE)
plus a `CheckContext` and returns a list of violations.
"""

from __future__ import annotations

from collections.abc import Callable

from .invariant_common import (
    CheckContext,
    Component,
    has_recurrence,
    identity_key,
    is_legacy_segment,
    is_override,
    items,
    label,
    main_of,
    try_parse,
)
from .oracle_policy import StoreError
from .oracle_temporal import (
    align_rid_to_master,
    expand_component_candidates,
    format_canonical_rid,
)

CalendarCheck = Callable[[list[Component], CheckContext], list[str]]

_TZ_FIELDS = ("dtstart", "dtend", "due", "recurrence_id")
_TZ_LIST_FIELDS = ("rdate", "exdate")


def unique_identity(components: list[Component], ctx: CheckContext) -> list[str]:
    """(UID, RECURRENCE-ID) is unique across the calendar."""
    del ctx
    seen: set[tuple[str, str]] = set()
    errors: list[str] = []
    for comp in items(components):
        key = identity_key(comp, components)
        if key in seen:
            errors.append(f"duplicate component identity {label(comp)}")
        seen.add(key)
    return errors


def single_main_per_uid(components: list[Component], ctx: CheckContext) -> list[str]:
    """Each UID has at most one main component (no RECURRENCE-ID)."""
    del ctx
    counts: dict[str, int] = {}
    for comp in items(components):
        if comp.get("recurrence_id") is None:
            counts[str(comp.get("uid"))] = counts.get(str(comp.get("uid")), 0) + 1
    return [
        f"uid {uid!r} has {n} main components" for uid, n in counts.items() if n > 1
    ]


def override_has_recurring_main(
    components: list[Component], ctx: CheckContext
) -> list[str]:
    """Every override has a recurring main component with the same UID."""
    del ctx
    errors: list[str] = []
    for comp in items(components):
        if not is_override(comp):
            continue
        main = main_of(components, str(comp.get("uid")))
        if main is None:
            errors.append(f"override {label(comp)} has no main component")
        elif not has_recurrence(main):
            errors.append(f"override {label(comp)} has a non-recurring main")
    return errors


def override_rid_matches_main_form(
    components: list[Component], ctx: CheckContext
) -> list[str]:
    """An override's RECURRENCE-ID has the main DTSTART's value type and floating-ness.

    Notation convention: a RECURRENCE-ID written without UTC designator or TZID on a
    UTC/TZID series denotes local wall-clock time in the series' time zone.
    """
    del ctx
    errors: list[str] = []
    for comp in items(components):
        main = main_of(components, str(comp.get("uid")))
        if not is_override(comp) or main is None:
            continue
        pt_rid = try_parse(comp["recurrence_id"], "recurrence_id")
        pt_main = try_parse(main.get("dtstart"), "dtstart")
        if pt_rid is None or pt_main is None:
            errors.append(f"override {label(comp)}: unparsable RECURRENCE-ID/DTSTART")
        elif pt_rid.is_date != pt_main.is_date:
            errors.append(f"override {label(comp)}: value type differs from DTSTART")
        elif pt_rid.kind == "OFFSET":
            errors.append(f"override {label(comp)}: fixed-offset RECURRENCE-ID")
        elif pt_main.kind == "FLOATING" and pt_rid.kind != "FLOATING":
            errors.append(
                f"override {label(comp)}: non-floating RID on floating series"
            )
    return errors


def _candidate_keys(generators: list[Component]) -> set[str]:
    keys: set[str] = set()
    for gen in generators:
        keys.update(
            rid for rid, _, _ in expand_component_candidates(gen, include_exdates=True)
        )
    return keys


def override_rid_is_candidate(
    components: list[Component], ctx: CheckContext
) -> list[str]:
    """Every override's RECURRENCE-ID is a candidate occurrence of its main component."""
    errors: list[str] = []
    for comp in items(components):
        uid = str(comp.get("uid"))
        main = main_of(components, uid)
        if not is_override(comp) or main is None or not has_recurrence(main):
            continue
        gens = [main]
        if ctx.legacy_input:
            gens += [
                c
                for c in items(components)
                if c.get("uid") == uid and is_legacy_segment(c)
            ]
        try:
            pt_main = try_parse(main["dtstart"], "dtstart")
            assert pt_main is not None
            key = format_canonical_rid(
                align_rid_to_master(comp["recurrence_id"], pt_main)
            )
            ok = key in _candidate_keys(gens)
        except (StoreError, ValueError, AssertionError):
            ok = False
        if not ok:
            errors.append(
                f"override {label(comp)} is not a candidate occurrence of its main"
            )
    return errors


def _referenced_tzids(comp: Component) -> set[str]:
    values = [comp.get(k) for k in _TZ_FIELDS]
    for key in _TZ_LIST_FIELDS:
        values.extend(comp.get(key) or ())
    tzids: set[str] = set()
    for raw in values:
        pt = try_parse(raw)
        if pt is not None and pt.kind == "TZID" and pt.tzid:
            tzids.add(pt.tzid)
    return tzids


def vtimezone_coverage(components: list[Component], ctx: CheckContext) -> list[str]:
    """A VTIMEZONE exists for every TZID referenced by a component."""
    del ctx
    defined = {c.get("tz_id") for c in components if c.get("type") == "VTIMEZONE"}
    missing: set[str] = set()
    for comp in items(components):
        missing |= _referenced_tzids(comp) - defined
    return [f"no VTIMEZONE for referenced TZID {tzid!r}" for tzid in sorted(missing)]


CALENDAR_CHECKS: dict[str, CalendarCheck] = {
    "unique_identity": unique_identity,
    "single_main_per_uid": single_main_per_uid,
    "override_has_recurring_main": override_has_recurring_main,
    "override_rid_matches_main_form": override_rid_matches_main_form,
    "override_rid_is_candidate": override_rid_is_candidate,
    "vtimezone_coverage": vtimezone_coverage,
}
