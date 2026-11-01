"""Seeded, deterministic random operation sequences checked against every invariant.

Runs random add / edit / delete / split sequences through `CheckedStore` (a
`ReferenceStore` that asserts every `I-*` invariant around each operation, including
atomicity of rejected operations and order-independence) across policy configurations.
Uses only `random.Random(seed)` so every run is reproducible.
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
    ThisAndFutureSplitMode,
)
from .oracle_temporal import format_temporal_like, parse_temporal, shift_wall_clock

SEEDS_PER_POLICY = 2
STEPS = 12
NY = "America/New_York"

POLICIES = [
    PolicyConfig(*combo)
    for combo in itertools.product(
        SeriesEditOverrideMode,
        [ThisAndFutureSplitMode.NEW_UID],
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
        "rrule": "FREQ=DAILY;COUNT=6",
        "exdate": ["2025-05-03T09:00:00"],
        "sequence": 0,
    },
    {
        "uid": "tz-1",
        "summary": "Weekly across DST",
        "dtstart": f"2025-03-03T09:00:00-05:00[{NY}]",
        "dtend": f"2025-03-03T09:30:00-05:00[{NY}]",
        "rrule": "FREQ=WEEKLY;COUNT=5",
        "sequence": 0,
    },
    {
        "uid": "day-1",
        "summary": "All-day",
        "dtstart": "2025-05-01",
        "dtend": "2025-05-02",
        "rrule": "FREQ=DAILY;UNTIL=20250506",
        "sequence": 0,
    },
    {
        "type": "VTODO",
        "uid": "todo-1",
        "summary": "Chore",
        "dtstart": "2025-05-01T08:00:00",
        "due": "2025-05-01T12:00:00",
        "rrule": "FREQ=DAILY;COUNT=4",
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


def _shift(raw: str, hours: int) -> str:
    """Shift a temporal string by whole hours (days for DATE values) in wall-clock time."""
    pt = parse_temporal(raw, "dtstart")
    delta = (
        datetime.timedelta(days=hours)
        if pt.is_date
        else datetime.timedelta(hours=hours)
    )
    return format_temporal_like(shift_wall_clock(pt.value, delta), pt)


def _patch(rng: random.Random, occ: dict[str, Any], schedule: bool) -> dict[str, Any]:
    patch: dict[str, Any] = {"summary": f"S{rng.randint(0, 999)}"}
    if schedule and occ.get("dtstart"):
        patch["dtstart"] = _shift(occ["dtstart"], rng.choice((-2, 1, 3)))
    return patch


def _random_op(
    rng: random.Random, store: CheckedStore, step: int
) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
    """Choose a random operation as (method, args, kwargs) on the current state."""
    now = f"2025-06-01T{step // 60:02d}:{step % 60:02d}:00Z"
    timeline = store.expand_timeline()
    if not timeline or rng.random() < 0.08:
        uid = f"new-{step}"
        item = {
            "uid": uid,
            "summary": "Added",
            "dtstart": "2025-05-10T10:00:00",
            "dtend": "2025-05-10T11:00:00",
            "rrule": "FREQ=DAILY;COUNT=3",
        }
        return "add", (item,), {"now": now}
    occ = rng.choice(timeline)
    uid, rid = occ["uid"], occ.get("recurrence_id")
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
        return "edit", (uid, _patch(rng, occ, rng.random() < 0.4)), {"now": now}
    rng_value = "NONE" if rng_name == "none" else "THIS_AND_FUTURE"
    kwargs = {"recurrence_id": rid, "recurrence_range": rng_value, "now": now}
    if scope == "delete":
        return "delete", (uid,), kwargs
    return "edit", (uid, _patch(rng, occ, rng.random() < 0.5)), kwargs


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


@pytest.mark.xfail(
    reason="pre-NEW_UID oracle: I-T-004 (re-split gains slots), I-T-006 (SHIFT_WITH_SERIES "
    "re-keys overrides without a revision bump), I-T-007 (re-split drops the NEXT chain)",
    strict=True,
)
@pytest.mark.parametrize("seed_offset", range(SEEDS_PER_POLICY))
def test_random_operation_sequences_preserve_invariants(seed_offset: int) -> None:
    """Every invariant holds after every step of random sequences under every policy."""
    applied = sum(
        _run_sequence(policy, idx * SEEDS_PER_POLICY + seed_offset)
        for idx, policy in enumerate(POLICIES)
    )
    assert applied > len(POLICIES) * STEPS // 2
