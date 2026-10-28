"""Adversarial multi-step red-team test suite for the clean-room Reference Store Oracle.

Tests complex cross-layer interactions across all 8 PolicyConfig combinations:
- Cross-boundary rescheduled overrides with THIS_AND_FUTURE delete/edit (R-L2-008 + R-L3-006)
- Out-of-order `[override_2, override_1, master]` metadata edit and schedule shift (R-L4-002..005)
- DST spring-forward multi-split chains (R-L3-003 + R-L3-008)
- Combined RDATE + RRULE + EXDATE series splitting (R-L1-001 + R-L3-007)
"""

# pylint: disable=duplicate-code,line-too-long

from __future__ import annotations

from typing import Any

import pytest

from .reference_oracle import (
    PolicyConfig,
    ReferenceStore,
    SeriesEditOverrideMode,
)
from .test_reference_oracle import ALL_POLICY_CONFIGS, assert_rfc_invariants


def _setup_cross_boundary_store(policy: PolicyConfig) -> ReferenceStore:
    """Create a 5-day series with two cross-boundary rescheduled overrides (Thu->Mon, Tue->Fri)."""
    base_init = [
        {
            "type": "VEVENT",
            "uid": "cross-boundary-1",
            "summary": "Daily Sync",
            "dtstart": "2025-05-05T09:00:00",
            "dtend": "2025-05-05T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": [],
        }
    ]
    st = ReferenceStore(base_init, policy=policy)
    st.edit(
        uid="cross-boundary-1",
        recurrence_id="20250508T090000",
        recurrence_range="NONE",
        patch={
            "summary": "Thu Moved to Mon Afternoon",
            "dtstart": "2025-05-05T14:00:00",
            "dtend": "2025-05-05T15:00:00",
        },
    )
    st.edit(
        uid="cross-boundary-1",
        recurrence_id="20250506T090000",
        recurrence_range="NONE",
        patch={
            "summary": "Tue Moved to Fri Afternoon",
            "dtstart": "2025-05-09T14:00:00",
            "dtend": "2025-05-09T15:00:00",
        },
    )
    tl_pre = assert_rfc_invariants(st, "redteam_a_pre_split")
    assert [item["dtstart"] for item in tl_pre] == [
        "2025-05-05T09:00:00",
        "2025-05-05T14:00:00",
        "2025-05-07T09:00:00",
        "2025-05-09T09:00:00",
        "2025-05-09T14:00:00",
    ]
    assert [item["recurrence_id"] for item in tl_pre] == [
        "20250505T090000",
        "20250508T090000",
        "20250507T090000",
        "20250509T090000",
        "20250506T090000",
    ]
    return st


@pytest.mark.parametrize(
    "policy",
    ALL_POLICY_CONFIGS,
    ids=[
        f"{p.series_edit_override_mode.value}-{p.this_and_future_split_mode.value}-{p.single_edit_exdate_mode.value}"
        for p in ALL_POLICY_CONFIGS
    ],
)
def test_redteam_a_cross_boundary_rescheduled_overrides_this_and_future_delete_and_edit(
    policy: PolicyConfig,
) -> None:
    """Red-Team (a): Cross-boundary rescheduled overrides + THIS_AND_FUTURE delete/edit (R-L2-008 + R-L3-006)."""
    store_del = _setup_cross_boundary_store(policy)
    store_del.delete(
        uid="cross-boundary-1",
        recurrence_id="20250507T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_del = assert_rfc_invariants(store_del, "redteam_a_after_taf_delete")
    assert [
        (item["recurrence_id"], item["dtstart"], item["summary"]) for item in tl_del
    ] == [
        ("20250505T090000", "2025-05-05T09:00:00", "Daily Sync"),
        ("20250506T090000", "2025-05-09T14:00:00", "Tue Moved to Fri Afternoon"),
    ]

    store_edit = _setup_cross_boundary_store(policy)
    store_edit.edit(
        uid="cross-boundary-1",
        recurrence_id="20250507T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch={
            "summary": "Future Sync",
            "dtstart": "2025-05-07T11:00:00",
        },
    )
    tl_edit = assert_rfc_invariants(store_edit, "redteam_a_after_taf_edit")
    assert [
        (item["recurrence_id"], item["dtstart"], item["summary"]) for item in tl_edit
    ] == [
        ("20250505T090000", "2025-05-05T09:00:00", "Daily Sync"),
        ("20250507T110000", "2025-05-07T11:00:00", "Future Sync"),
        ("20250508T110000", "2025-05-08T11:00:00", "Future Sync"),
        ("20250509T110000", "2025-05-09T11:00:00", "Future Sync"),
        ("20250506T090000", "2025-05-09T14:00:00", "Tue Moved to Fri Afternoon"),
    ]


@pytest.mark.parametrize(
    "policy",
    ALL_POLICY_CONFIGS,
    ids=[
        f"{p.series_edit_override_mode.value}-{p.this_and_future_split_mode.value}-{p.single_edit_exdate_mode.value}"
        for p in ALL_POLICY_CONFIGS
    ],
)
def test_redteam_b_out_of_order_overrides_metadata_edit_and_schedule_shift(
    policy: PolicyConfig,
) -> None:
    """Red-Team (b): Out-of-order [override_2, override_1, master] + metadata edit + schedule shift (R-L4-002..005)."""
    init_out_of_order: list[dict[str, Any]] = [
        {
            "type": "VEVENT",
            "uid": "ooo-series-1",
            "recurrence_id": "20250505T090000",
            "summary": "Override 2 Custom",
            "dtstart": "2025-05-05T15:00:00",
            "dtend": "2025-05-05T16:00:00",
            "rrule": None,
        },
        {
            "type": "VEVENT",
            "uid": "ooo-series-1",
            "recurrence_id": "20250502T090000",
            "summary": "Override 1 Custom",
            "dtstart": "2025-05-02T11:00:00",
            "dtend": "2025-05-02T12:00:00",
            "rrule": None,
        },
        {
            "type": "VEVENT",
            "uid": "ooo-series-1",
            "recurrence_id": None,
            "summary": "Original Master",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": ["2025-05-01T09:00:00", "2025-05-04T09:00:00"],
        },
    ]
    store = ReferenceStore(init_out_of_order, policy=policy)
    tl0 = assert_rfc_invariants(store, "redteam_b_init_out_of_order")
    assert [item["recurrence_id"] for item in tl0] == [
        "20250502T090000",
        "20250503T090000",
        "20250505T090000",
    ]

    store.edit(
        uid="ooo-series-1",
        recurrence_id=None,
        patch={"summary": "Renamed Series"},
    )
    tl1 = assert_rfc_invariants(store, "redteam_b_step1_metadata_edit")
    expected_ov1_sum = (
        "Renamed Series"
        if policy.series_edit_override_mode == SeriesEditOverrideMode.PROPAGATE_PATCH
        else "Override 1 Custom"
    )
    expected_ov2_sum = (
        "Renamed Series"
        if policy.series_edit_override_mode == SeriesEditOverrideMode.PROPAGATE_PATCH
        else "Override 2 Custom"
    )
    assert [(item["recurrence_id"], item["summary"]) for item in tl1] == [
        ("20250502T090000", expected_ov1_sum),
        ("20250503T090000", "Renamed Series"),
        ("20250505T090000", expected_ov2_sum),
    ]

    store.edit(
        uid="ooo-series-1",
        recurrence_id=None,
        patch={"dtstart": "2025-05-03T09:00:00"},
    )
    tl2 = assert_rfc_invariants(store, "redteam_b_step2_schedule_shift")
    remaining_rids = [c.get("recurrence_id") for c in store.components]
    assert "20250502T090000" not in remaining_rids
    assert "20250505T090000" in remaining_rids

    master_comp = next(c for c in store.components if c.get("recurrence_id") is None)
    assert master_comp["exdate"] == ["2025-05-04T09:00:00"]
    assert master_comp["dtend"] == "2025-05-03T10:00:00"
    assert [
        (item["recurrence_id"], item["dtstart"], item["summary"]) for item in tl2
    ] == [
        ("20250503T090000", "2025-05-03T09:00:00", "Renamed Series"),
        ("20250505T090000", "2025-05-05T15:00:00", expected_ov2_sum),
        ("20250506T090000", "2025-05-06T09:00:00", "Renamed Series"),
        ("20250507T090000", "2025-05-07T09:00:00", "Renamed Series"),
    ]


@pytest.mark.parametrize(
    "policy",
    ALL_POLICY_CONFIGS,
    ids=[
        f"{p.series_edit_override_mode.value}-{p.this_and_future_split_mode.value}-{p.single_edit_exdate_mode.value}"
        for p in ALL_POLICY_CONFIGS
    ],
)
def test_redteam_c_dst_spring_forward_multi_split(policy: PolicyConfig) -> None:
    """Red-Team (c): DST Spring-Forward (America/New_York 2025-03-08..2025-03-12) Multi-Split (R-L3-003 + R-L3-008)."""
    store = ReferenceStore(policy=policy, track_vtimezone=True)
    store.add(
        {
            "type": "VEVENT",
            "uid": "dst-multi-1",
            "summary": "Pre-DST Series",
            "dtstart": "2025-03-08T09:00:00-05:00[America/New_York]",
            "dtend": "2025-03-08T10:00:00-05:00[America/New_York]",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": [],
        }
    )
    assert len(assert_rfc_invariants(store, "redteam_c_step0_initial")) == 5

    store.edit(
        uid="dst-multi-1",
        recurrence_id="20250309T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch={
            "summary": "Split 1 (DST Day)",
            "dtstart": "2025-03-09T10:00:00-04:00[America/New_York]",
        },
    )
    assert len(assert_rfc_invariants(store, "redteam_c_step1_first_split")) == 5

    seg1 = next(
        c
        for c in store.components
        if c.get("type") == "VEVENT" and c.get("dtstart", "").startswith("2025-03-08")
    )
    assert seg1["rrule"] == "FREQ=DAILY;UNTIL=20250309T125959Z"

    seg2 = next(
        c
        for c in store.components
        if c.get("type") == "VEVENT" and c.get("dtstart", "").startswith("2025-03-09")
    )
    assert seg2["rrule"] == "FREQ=DAILY;COUNT=4"
    seg2_uid = seg2["uid"]

    store.edit(
        uid=seg2_uid,
        recurrence_id="20250311T100000",
        recurrence_range="THIS_AND_FUTURE",
        patch={
            "summary": "Split 2 (Post-DST)",
            "dtstart": "2025-03-11T14:00:00-04:00[America/New_York]",
        },
    )
    tl2 = assert_rfc_invariants(store, "redteam_c_step2_second_split")
    assert len(tl2) == 5
    assert seg2["rrule"] == "FREQ=DAILY;UNTIL=20250311T135959Z"
    seg3 = next(
        c
        for c in store.components
        if c.get("type") == "VEVENT" and c.get("dtstart", "").startswith("2025-03-11")
    )
    assert seg3["rrule"] == "FREQ=DAILY;COUNT=2"
    assert [(item["dtstart"], item["summary"]) for item in tl2] == [
        ("2025-03-08T09:00:00-05:00[America/New_York]", "Pre-DST Series"),
        ("2025-03-09T10:00:00-04:00[America/New_York]", "Split 1 (DST Day)"),
        ("2025-03-10T10:00:00-04:00[America/New_York]", "Split 1 (DST Day)"),
        ("2025-03-11T14:00:00-04:00[America/New_York]", "Split 2 (Post-DST)"),
        ("2025-03-12T14:00:00-04:00[America/New_York]", "Split 2 (Post-DST)"),
    ]


@pytest.mark.parametrize(
    "policy",
    ALL_POLICY_CONFIGS,
    ids=[
        f"{p.series_edit_override_mode.value}-{p.this_and_future_split_mode.value}-{p.single_edit_exdate_mode.value}"
        for p in ALL_POLICY_CONFIGS
    ],
)
def test_redteam_d_rdate_rrule_exdate_combined_series_split(
    policy: PolicyConfig,
) -> None:
    """Red-Team (d): RDATE + RRULE + EXDATE combined series split (R-L1-001 + R-L3-007)."""
    init_combined = [
        {
            "type": "VEVENT",
            "uid": "rdate-rrule-exdate-1",
            "summary": "Hybrid Series",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=WEEKLY;COUNT=4",
            "rdate": ["2025-05-03T14:00:00", "2025-05-20T14:00:00"],
            "exdate": ["2025-05-08T09:00:00"],
        }
    ]
    store_edit = ReferenceStore(init_combined, policy=policy)
    tl0 = assert_rfc_invariants(store_edit, "redteam_d_initial")
    assert [item["dtstart"] for item in tl0] == [
        "2025-05-01T09:00:00",
        "2025-05-03T14:00:00",
        "2025-05-15T09:00:00",
        "2025-05-20T14:00:00",
        "2025-05-22T09:00:00",
    ]

    store_edit.edit(
        uid="rdate-rrule-exdate-1",
        recurrence_id="20250515T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch={"summary": "Hybrid Future"},
    )
    tl_edit = assert_rfc_invariants(store_edit, "redteam_d_after_taf_edit")
    prior_seg = next(
        c for c in store_edit.components if c.get("dtstart") == "2025-05-01T09:00:00"
    )
    future_seg = next(
        c for c in store_edit.components if c.get("dtstart") == "2025-05-15T09:00:00"
    )
    assert prior_seg["rrule"] == "FREQ=WEEKLY;UNTIL=20250515T085959"
    assert prior_seg["rdate"] == ["2025-05-03T14:00:00"]
    assert prior_seg["exdate"] == ["2025-05-08T09:00:00"]
    assert future_seg["rrule"] == "FREQ=WEEKLY;COUNT=2"
    assert future_seg["rdate"] == ["2025-05-20T14:00:00"]
    assert future_seg["exdate"] == []
    assert [(item["dtstart"], item["summary"]) for item in tl_edit] == [
        ("2025-05-01T09:00:00", "Hybrid Series"),
        ("2025-05-03T14:00:00", "Hybrid Series"),
        ("2025-05-15T09:00:00", "Hybrid Future"),
        ("2025-05-20T14:00:00", "Hybrid Future"),
        ("2025-05-22T09:00:00", "Hybrid Future"),
    ]

    store_del = ReferenceStore(init_combined, policy=policy)
    store_del.delete(
        uid="rdate-rrule-exdate-1",
        recurrence_id="20250515T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_del = assert_rfc_invariants(store_del, "redteam_d_after_taf_delete")
    assert len(store_del.components) == 1
    rem_master = store_del.components[0]
    assert rem_master["rrule"] == "FREQ=WEEKLY;UNTIL=20250515T085959"
    assert rem_master["rdate"] == ["2025-05-03T14:00:00"]
    assert rem_master["exdate"] == ["2025-05-08T09:00:00"]
    assert [item["dtstart"] for item in tl_del] == [
        "2025-05-01T09:00:00",
        "2025-05-03T14:00:00",
    ]
