"""Seeded, deterministic random operation sequences checked against every invariant.

Runs random add / edit / delete / split sequences through `CheckedStore` (a
`ReferenceStore` that asserts every `I-*` invariant around each operation, including
atomicity of rejected operations and order-independence) across all 48 policy
configurations. Covers floating, UTC (`Z`), DST spring-forward/fall-back TZIDs
(`America/New_York`, `Europe/London`), all-day `DATE`, `DURATION`-based components,
`RDATE`s, `VTODO`s (including due-only/dateless), cross-class transitions, clock-skewed
timestamps, and invalid patches exercising `I-T-008`.
"""

from __future__ import annotations

import datetime
import itertools
import random
from typing import Any

import pytest

from .invariant_harness import CheckedStore
from .oracle_policy import (
    ParentDeleteCascadeMode,
    PolicyConfig,
    SeriesEditOverrideMode,
    SeriesRescheduleExceptionMode,
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
)
from .oracle_temporal import format_temporal_like, parse_temporal, shift_wall_clock

SEEDS_PER_POLICY = 2
STEPS = 12
NY = "America/New_York"
LON = "Europe/London"

POLICIES = [
    PolicyConfig(*combo)
    for combo in itertools.product(
        SeriesEditOverrideMode,
        SingleEditExdateMode,
        SeriesRescheduleExceptionMode,
        SplitFutureOverrideMode,
        ParentDeleteCascadeMode,
    )
]

INITIAL: list[dict[str, Any]] = [
    {
        "uid": "float-1",
        "summary": "Floating daily",
        "dtstart": "2025-05-01T09:00:00",
        "dtend": "2025-05-01T10:00:00",
        "rrule": "FREQ=DAILY;COUNT=5",
        "rdate": ["2025-05-08T09:00:00"],
        "exdate": ["2025-05-03T09:00:00"],
        "sequence": 0,
    },
    {
        "uid": "utc-dur-1",
        "summary": "UTC duration series",
        "dtstart": "2025-05-01T13:00:00Z",
        "duration": "PT45M",
        "rrule": "FREQ=DAILY;UNTIL=20250505T130000Z",
        "sequence": 0,
    },
    {
        "uid": "ny-dst-gap",
        "summary": "NY spring-forward",
        "dtstart": f"2025-03-08T02:30:00-05:00[{NY}]",
        "duration": "PT30M",
        "rrule": "FREQ=DAILY;COUNT=4",
        "sequence": 0,
    },
    {
        "uid": "ny-dst-fold",
        "summary": "NY fall-back hourly",
        "dtstart": f"2025-11-02T00:30:00-04:00[{NY}]",
        "dtend": f"2025-11-02T01:00:00-04:00[{NY}]",
        "rrule": "FREQ=HOURLY;COUNT=4",
        "sequence": 0,
    },
    {
        "uid": "day-1",
        "summary": "All-day",
        "dtstart": "2025-05-01",
        "dtend": "2025-05-02",
        "rrule": "FREQ=DAILY;UNTIL=20250505",
        "sequence": 0,
    },
    {
        "type": "VTODO",
        "uid": "todo-1",
        "summary": "Chore",
        "dtstart": f"2025-03-29T09:00:00+00:00[{LON}]",
        "due": f"2025-03-29T11:00:00+00:00[{LON}]",
        "rrule": "FREQ=DAILY;COUNT=4",
        "status": "NEEDS-ACTION",
        "sequence": 0,
    },
    {
        "uid": "child-1",
        "summary": "Child",
        "dtstart": "2025-05-02T15:00:00",
        "dtend": "2025-05-02T16:00:00",
        "related_to": [{"uid": "float-1", "reltype": "PARENT"}],
        "sequence": 0,
    },
]

ADD_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "summary": "Added UTC",
        "dtstart": "2025-05-10T10:00:00Z",
        "duration": "PT1H",
        "rrule": "FREQ=DAILY;COUNT=3",
    },
    {
        "summary": "Added RDATE-only",
        "dtstart": "2025-05-10T09:00:00",
        "dtend": "2025-05-10T09:30:00",
        "rdate": ["2025-05-12T09:00:00", "2025-05-14T09:00:00"],
    },
    {
        "type": "VTODO",
        "summary": "Due-only todo",
        "due": "2025-05-12T17:00:00Z",
        "status": "NEEDS-ACTION",
    },
    {
        "type": "VTODO",
        "summary": "Dateless todo",
        "status": "COMPLETED",
    },
)


def _shift(raw: str, hours: int) -> str:
    """Shift a temporal string by whole hours (days for DATE values) in wall-clock time."""
    pt = parse_temporal(raw, "dtstart")
    delta = (
        datetime.timedelta(days=hours)
        if pt.is_date
        else datetime.timedelta(hours=hours)
    )
    return format_temporal_like(shift_wall_clock(pt.value, delta), pt)


def _patch(
    rng: random.Random, occ: dict[str, Any], whole_series: bool
) -> dict[str, Any]:
    """Generate a varied valid or invalid (I-T-008) patch for occ."""
    roll = rng.random()
    if roll < 0.08:
        return rng.choice(
            (
                {"dtstart": None},
                {"dtend": "2025-05-01T10:00:00", "duration": "PT1H"},
                {"rrule": "FREQ=DAILY;COUNT=0"},
                {"dtstart": "2025-02-30"},
            )
        )
    patch: dict[str, Any] = {"summary": f"S{rng.randint(0, 999)}"}
    if occ.get("type") == "VTODO" and rng.random() < 0.35:
        patch["status"] = rng.choice(("COMPLETED", "NEEDS-ACTION", "IN-PROCESS"))
    if whole_series and occ.get("dtstart") and rng.random() < 0.15:
        patch["dtstart"] = rng.choice(
            ("2025-05-02", "2025-05-02T10:00:00", f"2025-05-02T10:00:00-04:00[{NY}]")
        )
        patch["duration"] = "P1D" if patch["dtstart"] == "2025-05-02" else "PT1H"
        return patch
    if occ.get("dtstart") and rng.random() < 0.45:
        patch["dtstart"] = _shift(occ["dtstart"], rng.choice((-2, -1, 1, 3, 24)))
    if occ.get("dtstart") and rng.random() < 0.2:
        pt = parse_temporal(patch.get("dtstart") or occ["dtstart"], "dtstart")
        patch["duration"] = "P2D" if pt.is_date else rng.choice(("PT30M", "PT2H"))
    return patch


def _maybe_wire_rid(rng: random.Random, occ: dict[str, Any]) -> str | None:
    """Occasionally express a zoned/UTC recurrence_id in alternate legal UTC/TZID wire form."""
    rid = occ.get("recurrence_id")
    if not rid or not occ.get("dtstart") or rng.random() >= 0.25:
        return rid
    pt_s = parse_temporal(occ["dtstart"], "dtstart")
    if pt_s.is_date or pt_s.kind == "FLOATING" or rid.endswith("Z"):
        return rid
    pt_r = parse_temporal(rid, "recurrence_id")
    if isinstance(pt_s.value, datetime.datetime) and pt_s.value.tzinfo is not None:
        assert isinstance(pt_r.value, datetime.datetime)
        zoned = pt_r.value.replace(tzinfo=pt_s.value.tzinfo)
        return zoned.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return rid


def _random_op(
    rng: random.Random, store: CheckedStore, step: int
) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
    """Choose a random operation as (method, args, kwargs) on the current state."""
    skew = rng.choice((0, 0, 0, -5))
    minute = max(0, step + skew)
    now = f"2025-06-01T{minute // 60:02d}:{minute % 60:02d}:00Z"
    timeline = store.expand_timeline()
    if not timeline or rng.random() < 0.12:
        tmpl = dict(rng.choice(ADD_TEMPLATES))
        tmpl["uid"] = f"new-{step}"
        return "add", (tmpl,), {"now": now}
    occ = rng.choice(timeline)
    uid = occ["uid"]
    rid = _maybe_wire_rid(rng, occ)
    kind = rng.choice(
        (
            "edit_none",
            "edit_none",
            "delete_none",
            "edit_taf",
            "edit_taf",
            "delete_taf",
            "edit_all",
            "delete_all",
        )
    )
    scope, _, rng_name = kind.partition("_")
    if rng_name == "all" or rid is None:
        if scope == "delete":
            return "delete", (uid,), {"now": now}
        return "edit", (uid, _patch(rng, occ, True)), {"now": now}
    rng_value = "NONE" if rng_name == "none" else "THIS_AND_FUTURE"
    kwargs = {"recurrence_id": rid, "recurrence_range": rng_value, "now": now}
    if scope == "delete":
        return "delete", (uid,), kwargs
    return "edit", (uid, _patch(rng, occ, False)), kwargs


def _run_sequence(policy: PolicyConfig, seed: int) -> int:
    rng = random.Random(seed)
    store = CheckedStore(INITIAL, policy=policy)
    applied = 0
    for step in range(STEPS):
        method, args, kwargs = _random_op(rng, store, step)
        try:
            getattr(store, method)(*args, **kwargs)
            applied += 1
        except StoreError:
            pass
    return applied


@pytest.mark.parametrize("seed_offset", range(SEEDS_PER_POLICY))
def test_random_operation_sequences_preserve_invariants(seed_offset: int) -> None:
    """Every invariant holds after every step of random sequences under every policy."""
    applied = sum(
        _run_sequence(policy, idx * SEEDS_PER_POLICY + seed_offset)
        for idx, policy in enumerate(POLICIES)
    )
    assert applied > len(POLICIES) * STEPS // 2
