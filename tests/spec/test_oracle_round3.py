"""Round 3 Adversarial Regression Suite for ReferenceStore and CheckedStore.

Covers all Round 3 red-team reproducers across all 48 PolicyConfig combinations:
- O-1.1..O-1.4: exhausted RRULE + later RDATE, off-pattern RDATE split, early RDATE < DTSTART,
  and RDATE-only truncation with surviving prior overrides.
- O-2: RFC 5545 DURATION property across add/expand/Range=NONE/re-edit/split/whole-series.
- O-3: Strict positive DTEND > DTSTART, DUE > DTSTART, and DURATION > 0 enforcement.
- O-4.1..O-4.4: DST fall-back fold=0/fold=1 disambiguation, spring-forward gap split,
  and SHIFT_WITH_SERIES gap collision deduplication.
- O-5.1..O-5.7, LOW-1, LOW-2: input validation & error atomicity (I-T-008), monotonic
  timestamps under clock skew (I-T-006), persisting key metadata on SHIFT_WITH_SERIES
  (I-T-005), MIGRATE_TO_FUTURE_SERIES with shifted EXDATE, recurring split enforcement
  (I-T-007), and UTC <-> TZID UNTIL wall-clock re-anchoring.
"""

from __future__ import annotations

from typing import Any

import pytest

from .invariant_harness import CheckedStore
from .oracle_policy import (
    PolicyConfig,
    SeriesRescheduleExceptionMode,
    SplitFutureOverrideMode,
    StoreError,
)
from .test_reference_oracle import ALL_48_POLICIES

NY = "America/New_York"


def test_o1_1_exhausted_rrule_with_later_rdates_split_and_delete() -> None:
    """Splitting or truncating at an RDATE after COUNT ended does not fabricate gap slots."""
    init = [
        {
            "uid": "exh-1",
            "summary": "Sync",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=2",
            "rdate": ["2025-05-10T09:00:00", "2025-05-12T09:00:00"],
        }
    ]
    for policy in ALL_48_POLICIES:
        s_edit = CheckedStore(init, policy=policy)
        s_edit.edit(
            "exh-1",
            {"summary": "Tail"},
            recurrence_id="20250510T090000",
            recurrence_range="THIS_AND_FUTURE",
        )
        tl_edit = s_edit.expand_timeline()
        assert [o["dtstart"] for o in tl_edit] == [
            "2025-05-01T09:00:00",
            "2025-05-02T09:00:00",
            "2025-05-10T09:00:00",
            "2025-05-12T09:00:00",
        ]
        assert [o["summary"] for o in tl_edit] == ["Sync", "Sync", "Tail", "Tail"]

        s_del = CheckedStore(init, policy=policy)
        s_del.delete("exh-1", "20250510T090000", "THIS_AND_FUTURE")
        assert [o["dtstart"] for o in s_del.expand_timeline()] == [
            "2025-05-01T09:00:00",
            "2025-05-02T09:00:00",
        ]


def test_o1_2_split_at_off_pattern_rdate_preserves_rrule_weekday() -> None:
    """Splitting a Monday weekly series at a Wednesday RDATE keeps Mondays on Mondays."""
    init = [
        {
            "uid": "off-rd-1",
            "summary": "Monday Weekly",
            "dtstart": "2025-05-05T09:00:00",
            "dtend": "2025-05-05T10:00:00",
            "rrule": "FREQ=WEEKLY;COUNT=3",
            "rdate": ["2025-05-07T09:00:00"],
        }
    ]
    for policy in ALL_48_POLICIES:
        store = CheckedStore(init, policy=policy)
        store.edit(
            "off-rd-1",
            {"summary": "Renamed"},
            recurrence_id="20250507T090000",
            recurrence_range="THIS_AND_FUTURE",
        )
        tl = store.expand_timeline()
        assert [o["dtstart"] for o in tl] == [
            "2025-05-05T09:00:00",
            "2025-05-07T09:00:00",
            "2025-05-12T09:00:00",
            "2025-05-19T09:00:00",
        ]
        assert [o["summary"] for o in tl] == [
            "Monday Weekly",
            "Renamed",
            "Renamed",
            "Renamed",
        ]


def test_o1_3_early_rdate_before_dtstart_split_and_first_instance() -> None:
    """An RDATE earlier than DTSTART is the true first instance and survives splits at DTSTART."""
    init = [
        {
            "uid": "early-rd-1",
            "summary": "Series",
            "dtstart": "2025-05-05T09:00:00",
            "dtend": "2025-05-05T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=2",
            "rdate": ["2025-05-01T09:00:00"],
        }
    ]
    for policy in ALL_48_POLICIES:
        s_split = CheckedStore(init, policy=policy)
        s_split.edit(
            "early-rd-1",
            {"summary": "From May 5"},
            recurrence_id="20250505T090000",
            recurrence_range="THIS_AND_FUTURE",
        )
        assert [o["dtstart"] for o in s_split.expand_timeline()] == [
            "2025-05-01T09:00:00",
            "2025-05-05T09:00:00",
            "2025-05-06T09:00:00",
        ]

        s_del = CheckedStore(init, policy=policy)
        s_del.delete("early-rd-1", "20250505T090000", "THIS_AND_FUTURE")
        assert [o["dtstart"] for o in s_del.expand_timeline()] == [
            "2025-05-01T09:00:00"
        ]

        s_first = CheckedStore(init, policy=policy)
        s_first.edit(
            "early-rd-1",
            {"dtstart": "2025-05-01T10:00:00"},
            recurrence_id="20250501T090000",
            recurrence_range="THIS_AND_FUTURE",
        )
        assert [o["dtstart"] for o in s_first.expand_timeline()] == [
            "2025-05-01T10:00:00",
            "2025-05-05T10:00:00",
            "2025-05-06T10:00:00",
        ]


def test_o1_4_truncate_rdate_only_series_with_surviving_prior_override() -> None:
    """Truncating an RDATE-only series when Day 1 has an override keeps main recurring (I-K-003)."""
    for policy in ALL_48_POLICIES:
        store = CheckedStore(policy=policy)
        store.add(
            {
                "uid": "rd-ov-1",
                "summary": "RDATE series",
                "dtstart": "2025-05-01T09:00:00",
                "dtend": "2025-05-01T10:00:00",
                "rdate": ["2025-05-03T09:00:00"],
            }
        )
        store.edit(
            "rd-ov-1",
            {"summary": "Moved Day 1", "dtstart": "2025-05-01T11:00:00"},
            recurrence_id="20250501T090000",
        )
        s_del = CheckedStore(store.components, policy=policy)
        s_del.delete("rd-ov-1", "20250503T090000", "THIS_AND_FUTURE")
        assert [
            (o["recurrence_id"], o["dtstart"]) for o in s_del.expand_timeline()
        ] == [("20250501T090000", "2025-05-01T11:00:00")]

        store.edit(
            "rd-ov-1",
            {"summary": "Split Day 3"},
            recurrence_id="20250503T090000",
            recurrence_range="THIS_AND_FUTURE",
        )
        assert len(store.expand_timeline()) == 2


def test_o2_duration_property_across_edit_split_and_date_coercion() -> None:
    """Components using DURATION (without DTEND/DUE) work across all edit/split/shift paths."""
    for policy in ALL_48_POLICIES:
        store = CheckedStore(policy=policy)
        store.add(
            {
                "uid": "dur-1",
                "summary": "Dur Event",
                "dtstart": "2025-05-01T09:00:00",
                "duration": "PT1H",
                "rrule": "FREQ=DAILY;COUNT=4",
            }
        )
        assert store.expand_timeline()[0]["dtend"] == "2025-05-01T10:00:00"
        store.edit(
            "dur-1",
            {"dtstart": "2025-05-02T11:00:00"},
            recurrence_id="20250502T090000",
        )
        store.edit(
            "dur-1",
            {"dtend": "2025-05-02T12:30:00"},
            recurrence_id="20250502T090000",
        )
        store.edit(
            "dur-1",
            {"duration": "PT45M"},
            recurrence_id="20250502T090000",
        )
        store.edit("dur-1", {"dtstart": "2025-05-01T10:00:00"})
        store.edit(
            "dur-1",
            {"summary": "Future Dur"},
            recurrence_id="20250503T100000",
            recurrence_range="THIS_AND_FUTURE",
            new_uid="dur-2",
        )
        store.edit("dur-2", {"dtstart": "2025-05-03"})
        seg2 = next(c for c in store.components if c.get("uid") == "dur-2")
        assert seg2["duration"] == "P1D"


def test_o3_strict_positive_bounds_and_vtodo_date_clamping() -> None:
    """Zero-duration DTEND==DTSTART, DUE==DTSTART, and PT0S are rejected; VTODO DATE clamps >=1d."""
    store = CheckedStore()
    for bad in (
        {"uid": "z1", "dtstart": "2025-05-01T09:00:00", "dtend": "2025-05-01T09:00:00"},
        {
            "type": "VTODO",
            "uid": "z2",
            "dtstart": "2025-05-01T09:00:00",
            "due": "2025-05-01T09:00:00",
        },
        {"uid": "z3", "dtstart": "2025-05-01T09:00:00", "duration": "PT0S"},
    ):
        with pytest.raises(StoreError):
            store.add(bad)

    store.add(
        {
            "type": "VTODO",
            "uid": "todo-subday",
            "summary": "Task",
            "dtstart": "2025-05-01T09:00:00",
            "due": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=2",
        }
    )
    store.edit("todo-subday", {"dtstart": "2025-05-01"})
    tl = store.expand_timeline()
    assert tl[0]["dtstart"] == "2025-05-01"
    assert tl[0]["due"] == "2025-05-02"


def test_o4_dst_fall_back_fold_and_spring_forward_gap() -> None:
    """Fall-back folds stay distinct and spring-forward gap splits/shifts preserve invariants."""
    for policy in ALL_48_POLICIES:
        s_fold = CheckedStore(policy=policy)
        s_fold.add(
            {
                "uid": "ny-hourly",
                "summary": "Night shift",
                "dtstart": f"2025-11-02T00:30:00-04:00[{NY}]",
                "duration": "PT30M",
                "rrule": "FREQ=HOURLY;COUNT=4",
            }
        )
        tl = s_fold.expand_timeline()
        assert len(tl) == 4
        assert [o["recurrence_id"] for o in tl] == [
            "20251102T003000",
            "20251102T013000",
            "20251102T063000Z",
            "20251102T023000",
        ]
        s_fold.edit(
            "ny-hourly", {"summary": "Fold-1 Only"}, recurrence_id="20251102T063000Z"
        )
        assert [o["summary"] for o in s_fold.expand_timeline()] == [
            "Night shift",
            "Night shift",
            "Fold-1 Only",
            "Night shift",
        ]

        s_gap = CheckedStore(policy=policy)
        s_gap.add(
            {
                "uid": "ny-gap",
                "summary": "Gap daily",
                "dtstart": f"2025-03-08T02:30:00-05:00[{NY}]",
                "duration": "PT30M",
                "rrule": "FREQ=DAILY;COUNT=3",
            }
        )
        s_gap.edit(
            "ny-gap",
            {"summary": "After gap"},
            recurrence_id="20250309T033000",
            recurrence_range="THIS_AND_FUTURE",
        )
        assert [o["dtstart"] for o in s_gap.expand_timeline()] == [
            f"2025-03-08T02:30:00-05:00[{NY}]",
            f"2025-03-09T03:30:00-04:00[{NY}]",
            f"2025-03-10T02:30:00-04:00[{NY}]",
        ]


def test_o4_4_shift_with_series_dst_gap_override_collision_dedup() -> None:
    """SHIFT_WITH_SERIES deduplicates 02:30 (gap-folded) vs 03:30 overrides deterministically."""
    for policy in ALL_48_POLICIES:
        if (
            policy.series_reschedule_exception_mode
            != SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES
        ):
            continue
        store = CheckedStore(policy=policy)
        store.add(
            {
                "uid": "gap-coll",
                "summary": "Hourly",
                "dtstart": f"2025-03-08T01:30:00-05:00[{NY}]",
                "duration": "PT30M",
                "rrule": "FREQ=HOURLY;COUNT=4",
            }
        )
        store.edit("gap-coll", {"summary": "Ov-0230"}, recurrence_id="20250308T023000")
        store.edit("gap-coll", {"summary": "Ov-0330"}, recurrence_id="20250308T033000")
        store.edit("gap-coll", {"dtstart": f"2025-03-09T01:30:00-05:00[{NY}]"})
        ovs = [
            c
            for c in store.components
            if c.get("uid") == "gap-coll" and c.get("recurrence_id") is not None
        ]
        assert len(ovs) == 1
        assert ovs[0]["summary"] == "Ov-0330"


def test_o5_validation_and_error_atomicity() -> None:
    """Invalid add/edit/re-edit payloads raise StoreError with full error atomicity (I-T-008)."""
    store = CheckedStore()
    store.add(
        {
            "uid": "val-1",
            "summary": "Base",
            "dtstart": "2025-05-01T09:00:00Z",
            "dtend": "2025-05-01T10:00:00Z",
            "rrule": "FREQ=DAILY;UNTIL=20250505T090000Z",
        }
    )
    store.edit("val-1", {"summary": "Ov2"}, recurrence_id="20250502T090000Z")
    bad_edits: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({"dtstart": None}, {"recurrence_id": "20250502T090000Z"}),
        ({"dtstart": "2025-05-02"}, {"recurrence_id": "20250502T090000Z"}),
        (
            {"dtstart": None},
            {
                "recurrence_id": "20250504T090000Z",
                "recurrence_range": "THIS_AND_FUTURE",
            },
        ),
        (
            {"rrule": None},
            {
                "recurrence_id": "20250504T090000Z",
                "recurrence_range": "THIS_AND_FUTURE",
            },
        ),
        ({"dtend": "2025-05-01T11:00:00Z", "duration": "PT2H"}, {}),
        ({"dtstart": "2025-02-30T09:00:00Z"}, {}),
        ({"summary": "Bad now"}, {"now": "2025-05-15T00:00:00"}),
    ]
    for patch, kwargs in bad_edits:
        with pytest.raises(StoreError):
            store.edit("val-1", patch, **kwargs)

    for bad_item in (
        {
            "uid": "b1",
            "dtstart": "2025-05-01",
            "duration": "P1D",
            "rrule": "FREQ=DAILY;BYHOUR=9",
        },
        {
            "uid": "b2",
            "dtstart": "2025-05-01",
            "duration": "P1D",
            "rrule": "FREQ=DAILY;COUNT=0",
        },
        {
            "uid": "val-1",
            "recurrence_id": "20250520T090000Z",
            "dtstart": "2025-05-20T10:00:00Z",
            "dtend": "2025-05-20T11:00:00Z",
        },
    ):
        with pytest.raises(StoreError):
            store.add(bad_item)


def test_o5_monotonicity_shift_meta_and_migration() -> None:
    """Clock-skew monotonicity, persisting key-collision meta, UTC->TZID, and EXDATE migration."""
    shift_pol = PolicyConfig(
        series_reschedule_exception_mode=SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES,
        split_future_override_mode=SplitFutureOverrideMode.MIGRATE_TO_FUTURE_SERIES,
    )
    store = CheckedStore(policy=shift_pol)
    store.add(
        {
            "uid": "val-1",
            "summary": "Base",
            "dtstart": "2025-05-01T09:00:00Z",
            "dtend": "2025-05-01T10:00:00Z",
            "rrule": "FREQ=DAILY;UNTIL=20250505T090000Z",
        },
        now="2025-05-10T00:00:00Z",
    )
    store.edit(
        "val-1",
        {"summary": "Ov2"},
        recurrence_id="20250502T090000Z",
        now="2025-05-11T00:00:00Z",
    )
    store.edit(
        "val-1",
        {"summary": "Ov3"},
        recurrence_id="20250503T090000Z",
        now="2025-05-12T00:00:00Z",
    )
    store.edit("val-1", {"dtstart": "2025-05-02T09:00:00Z"}, now="2025-05-01T00:00:00Z")
    store.edit(
        "val-1",
        {
            "dtstart": f"2025-05-02T09:00:00-04:00[{NY}]",
            "dtend": f"2025-05-02T10:00:00-04:00[{NY}]",
        },
        now="2025-05-15T00:00:00Z",
    )
    assert len(store.expand_timeline()) == 5

    s_mig = CheckedStore(policy=shift_pol)
    s_mig.add(
        {
            "uid": "mig-ex",
            "summary": "Base",
            "dtstart": "2025-05-01T09:00:00",
            "duration": "PT1H",
            "rrule": "FREQ=DAILY;COUNT=5",
        }
    )
    s_mig.delete("mig-ex", "20250503T090000", "NONE")
    s_mig.edit("mig-ex", {"summary": "Ov4"}, recurrence_id="20250504T090000")
    s_mig.edit(
        "mig-ex",
        {"dtstart": "2025-05-03T09:00:00"},
        recurrence_id="20250502T090000",
        recurrence_range="THIS_AND_FUTURE",
        new_uid="mig-ex-2",
    )
    assert all(
        not (c.get("uid") == "mig-ex-2" and c.get("recurrence_id") == "20250504T090000")
        for c in s_mig.components
    )
