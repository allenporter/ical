"""Adversarial regression suite for ReferenceStore covering all 96 PolicyConfigs and edge cases.

Covers DST fold/gap arithmetic, strict recurrence_id membership, canonical complete
schema, arbitrary property preservation, NEW_UID NEXT/FIRST chain lifecycle,
MIGRATE_TO_FUTURE_SERIES + LEGACY_DUAL_EXDATE, explicit COUNT on split, and earlier
re-split tail bound recovery.
"""

# pylint: disable=duplicate-code,line-too-long

from __future__ import annotations

import datetime
import itertools
from typing import Any

import pytest

from .reference_oracle import (
    ParentDeleteCascadeMode,
    PolicyConfig,
    ReferenceStore,
    SeriesEditOverrideMode,
    SeriesRescheduleExceptionMode,
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
    ThisAndFutureSplitMode,
    parse_temporal,
)
from .test_reference_oracle import assert_rfc_invariants

ALL_96_POLICIES = [
    PolicyConfig(
        series_edit_override_mode=s_edit,
        this_and_future_split_mode=t_split,
        single_edit_exdate_mode=s_ex,
        series_reschedule_exception_mode=s_resched,
        split_future_override_mode=sp_ov,
        parent_delete_cascade_mode=p_del,
    )
    for s_edit, t_split, s_ex, s_resched, sp_ov, p_del in itertools.product(
        SeriesEditOverrideMode,
        ThisAndFutureSplitMode,
        SingleEditExdateMode,
        SeriesRescheduleExceptionMode,
        SplitFutureOverrideMode,
        ParentDeleteCascadeMode,
    )
]


@pytest.mark.parametrize(
    "policy",
    ALL_96_POLICIES,
    ids=[
        f"{p.series_edit_override_mode.value[:4]}-{p.this_and_future_split_mode.value[:3]}-"
        f"{p.single_edit_exdate_mode.value[:3]}-{p.series_reschedule_exception_mode.value[:5]}-"
        f"{p.split_future_override_mode.value[:3]}-{p.parent_delete_cascade_mode.value[:4]}"
        for p in ALL_96_POLICIES
    ],
)
def test_full_96_policy_matrix_lifecycle(policy: PolicyConfig) -> None:
    """Exercise all 6 PolicyConfig axes simultaneously across all 96 combinations."""
    store = ReferenceStore(policy=policy)
    store.add(
        {
            "uid": "m96-parent",
            "summary": "Series V1",
            "dtstart": "2025-05-01T09:00:00-04:00[America/New_York]",
            "dtend": "2025-05-01T10:00:00-04:00[America/New_York]",
            "rrule": "FREQ=DAILY;COUNT=6",
        },
        now="2025-05-01T00:00:00Z",
    )
    store.add(
        {
            "uid": "m96-child",
            "summary": "Child Task",
            "dtstart": "2025-05-01T12:00:00-04:00[America/New_York]",
            "dtend": "2025-05-01T13:00:00-04:00[America/New_York]",
            "related_to": [{"uid": "m96-parent", "reltype": "PARENT"}],
        },
        now="2025-05-01T00:00:00Z",
    )
    assert any(
        c == {"type": "VTIMEZONE", "tz_id": "America/New_York"}
        for c in store.components
    )

    store.edit(
        "m96-parent",
        {"summary": "Day 2 Ov"},
        recurrence_id="20250502T090000",
        recurrence_range="NONE",
        now="2025-05-01T01:00:00Z",
    )
    store.edit(
        "m96-parent",
        {
            "summary": "Day 5 Ov",
            "dtstart": "2025-05-05T15:00:00-04:00[America/New_York]",
        },
        recurrence_id="20250505T090000",
        recurrence_range="NONE",
        now="2025-05-01T02:00:00Z",
    )
    assert len(assert_rfc_invariants(store, "m96_after_overrides")) == 7

    store.edit(
        "m96-parent",
        {
            "dtstart": "2025-05-01T10:00:00-04:00[America/New_York]",
            "summary": "Series V2",
        },
        recurrence_id=None,
        now="2025-05-01T03:00:00Z",
    )
    tl_resched = assert_rfc_invariants(store, "m96_after_reschedule")
    assert len(tl_resched) == 7

    split_rid = (
        "20250504T100000"
        if policy.series_reschedule_exception_mode
        == SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES
        else "20250504T100000"
    )
    store.edit(
        "m96-parent",
        {
            "dtstart": "2025-05-04T11:00:00-04:00[America/New_York]",
            "summary": "Future Seg",
        },
        recurrence_id=split_rid,
        recurrence_range="THIS_AND_FUTURE",
        now="2025-05-01T04:00:00Z",
    )
    tl_split = assert_rfc_invariants(store, "m96_after_split")
    assert len(tl_split) == 7

    store.delete("m96-parent", now="2025-05-01T05:00:00Z")
    tl_del = assert_rfc_invariants(store, "m96_after_delete")
    remaining_uids = [
        c["uid"] for c in store.components if c.get("type") != "VTIMEZONE"
    ]
    if policy.parent_delete_cascade_mode == ParentDeleteCascadeMode.CASCADE_DELETE:
        assert remaining_uids == []
        assert tl_del == []
    else:
        assert remaining_uids == ["m96-child"]


def test_dst_fold_and_gap_arithmetic_and_shift_with_series() -> None:
    """Verify fold=1 parsing/duration, nonexistent spring-forward gap handling, and DST wall-clock shift."""
    pt_edt = parse_temporal("2025-11-02T01:30:00-04:00[America/New_York]")
    pt_est = parse_temporal("2025-11-02T01:30:00-05:00[America/New_York]")
    assert isinstance(pt_edt.value, datetime.datetime)
    assert isinstance(pt_est.value, datetime.datetime)
    assert pt_edt.value.utcoffset() != pt_est.value.utcoffset()
    assert (pt_est.dt_utc_or_naive - pt_edt.dt_utc_or_naive).total_seconds() == 3600

    store_fb = ReferenceStore()
    store_fb.add(
        {
            "uid": "fb-1",
            "summary": "Overnight Maintenance",
            "dtstart": "2025-11-02T01:30:00-04:00[America/New_York]",
            "dtend": "2025-11-02T01:30:00-05:00[America/New_York]",
            "rrule": "FREQ=DAILY;COUNT=2",
        }
    )
    tl_fb = assert_rfc_invariants(store_fb, "fall_back_physical_duration")
    assert tl_fb[0]["dtend"] == "2025-11-02T01:30:00-05:00[America/New_York]"
    assert tl_fb[1]["dtstart"] == "2025-11-03T01:30:00-05:00[America/New_York]"
    assert tl_fb[1]["dtend"] == "2025-11-03T02:30:00-05:00[America/New_York]"

    with pytest.raises(StoreError, match="offset or nonexistent local time"):
        parse_temporal("2025-03-09T02:30:00-05:00[America/New_York]")

    store_gap = ReferenceStore()
    store_gap.add(
        {
            "uid": "gap-1",
            "summary": "2:30 AM Job",
            "dtstart": "2025-03-08T02:30:00-05:00[America/New_York]",
            "dtend": "2025-03-08T03:00:00-05:00[America/New_York]",
            "rrule": "FREQ=DAILY;COUNT=2",
        }
    )
    tl_gap = assert_rfc_invariants(store_gap, "spring_forward_gap_folding")
    assert tl_gap[1]["dtstart"] == "2025-03-09T03:30:00-04:00[America/New_York]"
    assert tl_gap[1]["dtend"] == "2025-03-09T04:00:00-04:00[America/New_York]"

    store_shift = ReferenceStore(
        [
            {
                "uid": "dst-shift",
                "summary": "Morning Sync",
                "dtstart": "2025-03-08T09:00:00-05:00[America/New_York]",
                "dtend": "2025-03-08T10:00:00-05:00[America/New_York]",
                "rrule": "FREQ=DAILY;COUNT=3",
                "exdate": ["2025-03-08T09:00:00-05:00[America/New_York]"],
            },
            {
                "uid": "dst-shift",
                "recurrence_id": "20250309T090000",
                "summary": "Custom",
                "dtstart": "2025-03-09T11:00:00-04:00[America/New_York]",
                "dtend": "2025-03-09T12:00:00-04:00[America/New_York]",
            },
        ],
        policy=PolicyConfig(
            series_reschedule_exception_mode=SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES
        ),
    )
    store_shift.edit(
        "dst-shift",
        {"dtstart": "2025-03-09T09:00:00-04:00[America/New_York]"},
    )
    tl_s = assert_rfc_invariants(store_shift, "dst_wall_clock_shift")
    master_s = next(
        c
        for c in store_shift.components
        if c.get("type") != "VTIMEZONE" and c["recurrence_id"] is None
    )
    ov_s = next(
        c
        for c in store_shift.components
        if c.get("type") != "VTIMEZONE" and c["recurrence_id"] is not None
    )
    assert master_s["exdate"] == ["2025-03-09T09:00:00-04:00[America/New_York]"]
    assert ov_s["recurrence_id"] == "20250310T090000"
    assert ov_s["dtstart"] == "2025-03-10T11:00:00-04:00[America/New_York]"
    assert len(tl_s) == 2


def test_strict_membership_and_validation_errors() -> None:
    """Verify missing UID, non-recurring rid, bogus/excluded rid, bad range, and duplicate identity raise StoreError."""
    store = ReferenceStore(
        [
            {
                "uid": "single-1",
                "summary": "One-off",
                "dtstart": "2025-05-01T09:00:00",
                "dtend": "2025-05-01T10:00:00",
            },
            {
                "uid": "rec-1",
                "summary": "Series",
                "dtstart": "2025-05-01T09:00:00",
                "dtend": "2025-05-01T10:00:00",
                "rrule": "FREQ=DAILY;COUNT=3",
                "exdate": ["2025-05-02T09:00:00"],
            },
        ]
    )
    with pytest.raises(StoreError, match="No component found"):
        store.edit("missing-uid", {"summary": "X"})
    with pytest.raises(StoreError, match="No component found"):
        store.delete("missing-uid")

    for rng in ("NONE", "THIS_AND_FUTURE"):
        with pytest.raises(StoreError):
            store.edit(
                "single-1",
                {"summary": "X"},
                recurrence_id="20250501T090000",
                recurrence_range=rng,
            )
        with pytest.raises(StoreError):
            store.delete(
                "single-1", recurrence_id="20250501T090000", recurrence_range=rng
            )

    with pytest.raises(StoreError, match="No active occurrence"):
        store.edit(
            "rec-1",
            {"summary": "Bogus"},
            recurrence_id="20990101T090000",
            recurrence_range="NONE",
        )
    with pytest.raises(StoreError, match="No active occurrence"):
        store.edit(
            "rec-1",
            {"summary": "Excluded slot"},
            recurrence_id="20250502T090000",
            recurrence_range="NONE",
        )
    with pytest.raises(StoreError, match="No active occurrence"):
        store.delete("rec-1", recurrence_id="20250502T090000", recurrence_range="NONE")
    with pytest.raises(StoreError, match="Unsupported recurrence_range"):
        store.delete(
            "rec-1", recurrence_id="20250501T090000", recurrence_range="THISANDPRIOR"
        )
    with pytest.raises(StoreError, match="Duplicate component identity"):
        store.add(
            {
                "uid": "single-1",
                "summary": "Dup",
                "dtstart": "2025-05-05T09:00:00",
                "dtend": "2025-05-05T10:00:00",
            }
        )
    with pytest.raises(StoreError, match="DTEND must be strictly after DTSTART"):
        store.add(
            {
                "uid": "bad-bounds",
                "summary": "Bad",
                "dtstart": "2025-05-05T10:00:00",
                "dtend": "2025-05-05T09:00:00",
            }
        )


def test_canonical_completeness_extra_props_and_propagate_metadata() -> None:
    """Verify canonical complete fields, arbitrary extra property preservation, and PROPAGATE_PATCH revision bump."""
    store = ReferenceStore()
    added = store.add(
        {
            "uid": "extra-1",
            "summary": "Board Review",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=3",
            "categories": ["EXEC", "Q2"],
            "x_room_code": "RM-404",
        },
        now="2025-05-01T08:00:00Z",
    )
    assert added["type"] == "VEVENT"
    assert added["sequence"] == 0
    assert added["created"] == "2025-05-01T08:00:00Z"
    assert added["categories"] == ["EXEC", "Q2"]
    assert added["x_room_code"] == "RM-404"

    store.edit(
        "extra-1",
        {"summary": "Day 2 Special", "x_note": "Bring deck"},
        recurrence_id="20250502T090000",
        recurrence_range="NONE",
        now="2025-05-01T09:00:00Z",
    )
    ov = next(c for c in store.components if c["recurrence_id"] == "20250502T090000")
    assert ov["sequence"] == 1
    assert ov["created"] == "2025-05-01T08:00:00Z"
    assert ov["last_modified"] == "2025-05-01T09:00:00Z"
    assert ov["categories"] == ["EXEC", "Q2"]
    assert ov["x_note"] == "Bring deck"

    store.edit(
        "extra-1",
        {"summary": "Renamed Board Review", "x_room_code": "RM-500"},
        recurrence_id=None,
        now="2025-05-01T10:00:00Z",
    )
    assert ov["summary"] == "Renamed Board Review"
    assert ov["x_room_code"] == "RM-500"
    assert ov["sequence"] == 2
    assert ov["dtstamp"] == "2025-05-01T10:00:00Z"
    assert ov["last_modified"] == "2025-05-01T10:00:00Z"

    tl = assert_rfc_invariants(store, "extra_props_timeline")
    assert all(occ["x_room_code"] == "RM-500" for occ in tl)
    assert tl[1]["x_note"] == "Bring deck"


def test_explicit_split_count_and_earlier_resplit_tail_recovery() -> None:
    """Verify explicit COUNT in patch is respected (H3), prior segment bumps sequence (L4), and earlier re-split recovers tail (H2)."""
    store = ReferenceStore()
    store.add(
        {
            "uid": "cnt-1",
            "summary": "Workout",
            "dtstart": "2025-05-01T07:00:00",
            "dtend": "2025-05-01T08:00:00",
            "rrule": "FREQ=DAILY;COUNT=6",
        },
        now="2025-05-01T00:00:00Z",
    )
    store.edit(
        "cnt-1",
        {"summary": "Extended Workout", "rrule": "FREQ=DAILY;COUNT=10"},
        recurrence_id="20250503T07:00:00",
        recurrence_range="THIS_AND_FUTURE",
        now="2025-05-01T01:00:00Z",
    )
    tl_explicit = assert_rfc_invariants(store, "explicit_count_split")
    prior = next(c for c in store.components if c["recurrence_id"] is None)
    future = next(c for c in store.components if c["recurrence_id"] is not None)
    assert prior["sequence"] == 1
    assert prior["last_modified"] == "2025-05-01T01:00:00Z"
    assert future["rrule"] == "FREQ=DAILY;COUNT=10"
    assert len(tl_explicit) == 12

    resplit = ReferenceStore()
    resplit.add(
        {
            "uid": "rs-1",
            "summary": "V1",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=6",
        }
    )
    resplit.edit(
        "rs-1",
        {"summary": "V2 from Day 4"},
        recurrence_id="20250504T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    resplit.edit(
        "rs-1",
        {"summary": "V3 from Day 2"},
        recurrence_id="20250502T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_rs = assert_rfc_invariants(resplit, "earlier_resplit_tail_recovery")
    assert len(tl_rs) == 6
    assert [occ["summary"] for occ in tl_rs] == ["V1", *(["V3 from Day 2"] * 5)]


def test_utc_exdate_on_tzid_series_and_migrate_with_legacy_dual_exdate() -> None:
    """Verify UTC EXDATE on TZID series survives filtering (M4) and MIGRATE + LEGACY_DUAL_EXDATE preserves exdate (C5)."""
    store_utc_ex = ReferenceStore(
        [
            {
                "uid": "utc-ex-1",
                "summary": "TZ Series",
                "dtstart": "2025-03-10T09:00:00-04:00[America/New_York]",
                "dtend": "2025-03-10T10:00:00-04:00[America/New_York]",
                "rrule": "FREQ=DAILY;COUNT=3",
                "exdate": ["2025-03-11T13:00:00Z"],
            }
        ]
    )
    store_utc_ex.edit("utc-ex-1", {"summary": "Renamed TZ Series"})
    tl_u = assert_rfc_invariants(store_utc_ex, "utc_exdate_on_tzid")
    utc_ev = next(c for c in store_utc_ex.components if c.get("uid") == "utc-ex-1")
    assert utc_ev["exdate"] == ["2025-03-11T13:00:00Z"]
    assert len(tl_u) == 2

    pol = PolicyConfig(
        this_and_future_split_mode=ThisAndFutureSplitMode.NEW_UID,
        single_edit_exdate_mode=SingleEditExdateMode.LEGACY_DUAL_EXDATE,
        split_future_override_mode=SplitFutureOverrideMode.MIGRATE_TO_FUTURE_SERIES,
    )
    st_mig = ReferenceStore(policy=pol)
    st_mig.add(
        {
            "uid": "mig-dual-1",
            "summary": "Daily",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=5",
        }
    )
    st_mig.edit(
        "mig-dual-1",
        {"summary": "Day 4 Special", "dtstart": "2025-05-04T15:00:00"},
        recurrence_id="20250504T090000",
        recurrence_range="NONE",
    )
    st_mig.edit(
        "mig-dual-1",
        {"dtstart": "2025-05-02T10:00:00"},
        recurrence_id="20250502T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_m = assert_rfc_invariants(st_mig, "migrate_legacy_dual_new_uid")
    assert len(tl_m) == 5
    future_master = next(
        c for c in st_mig.components if c["uid"] != "mig-dual-1" and c["rrule"]
    )
    migrated_ov = next(c for c in st_mig.components if c["recurrence_id"] is not None)
    assert migrated_ov["uid"] == future_master["uid"]
    assert future_master["exdate"] == ["2025-05-04T10:00:00"]

    st_mig.delete("mig-dual-1")
    assert st_mig.components == []
