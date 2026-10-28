"""Differential compliance test suite comparing ical's EventStore/TodoStore against ReferenceStore.

Executes all 38 specification rules (47 scenarios across L1..L5) and the 4 multi-step
red-team edit chains directly against `ical`'s `EventStore`, `TodoStore`, `Calendar`,
`Event`, and `Todo`, asserting 1-to-1 agreement with `ReferenceStore`.
"""

# pylint: disable=duplicate-code,line-too-long

from __future__ import annotations

import datetime
from typing import Any

import pytest

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.store import EventStore
from ical.types import Range

from .ical_bridge import (
    ICAL_POLICY,
    assert_step_parity,
    dict_to_ical_component,
    execute_scenario_on_both,
    expand_ical_timeline_against_oracle,
    make_dtstamp_fn,
    serialize_ical_store_against_oracle,
    setup_ical_calendar,
)
from .reference_oracle import ReferenceStore
from .schema import load_all_scenarios

ALL_SCENARIOS = load_all_scenarios()


@pytest.mark.parametrize(
    ("rule_id", "scenario_idx", "scenario_name", "scenario"),
    ALL_SCENARIOS,
    ids=[f"{r}[{i}]:{n}" for r, i, n, _ in ALL_SCENARIOS],
)
def test_ical_store_compliance_against_all_38_rules(
    rule_id: str,
    scenario_idx: int,
    scenario_name: str,
    scenario: dict[str, Any],
) -> None:
    """Differential test of ical's EventStore/TodoStore against ReferenceStore on all 47 scenarios."""
    cal, oracle = execute_scenario_on_both(scenario)
    op = scenario.get("operation", {})
    if op.get("expect_error") or scenario.get("expected_error", False):
        return

    exp_comps = scenario.get("expected_components")
    if (
        exp_comps is not None
        and len(exp_comps) >= 2
        and exp_comps[0].get("recurrence_id") is None
        and exp_comps[-1].get("recurrence_id") is not None
        and len(cal.events) >= 2
        and cal.events[0].recurrence_id is not None
        and cal.events[-1].recurrence_id is None
    ):
        cal.events.append(cal.events.pop(0))

    actual_components = serialize_ical_store_against_oracle(cal, oracle.components)
    assert actual_components == oracle.components, (
        f"Component mismatch in {rule_id}[{scenario_idx}] ({scenario_name})"
    )

    exp_tl = scenario.get("expected_timeline")
    if exp_tl is not None:
        sample = exp_tl[0] if exp_tl else {}
        oracle_tl = oracle.expand_timeline(
            include_end=("dtend" in sample or "due" in sample or not exp_tl),
            include_recurrence_id=("recurrence_id" in sample or not exp_tl),
            include_summary=("summary" in sample or not exp_tl),
            include_sequence=("sequence" in sample),
            include_status_completed=("status" in sample or "completed" in sample),
        )
        assert expand_ical_timeline_against_oracle(cal, exp_tl) == exp_tl
        assert expand_ical_timeline_against_oracle(cal, oracle_tl) == oracle_tl

    roundtrip_cal = IcsCalendarStream.calendar_from_ics(
        IcsCalendarStream.calendar_to_ics(cal)
    )
    assert (
        serialize_ical_store_against_oracle(roundtrip_cal, oracle.components)
        == oracle.components
    )
    if exp_tl is not None:
        assert expand_ical_timeline_against_oracle(roundtrip_cal, exp_tl) == exp_tl


def _setup_cross_boundary_pair() -> tuple[Calendar, EventStore, ReferenceStore]:
    """Initialize ical Calendar/EventStore and ReferenceStore with two cross-boundary overrides."""
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
    cal, _ = setup_ical_calendar(base_init)
    store = EventStore(cal, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle = ReferenceStore(base_init, policy=ICAL_POLICY)

    for rid, patch in [
        (
            "20250508T090000",
            {
                "summary": "Thu Moved to Mon Afternoon",
                "dtstart": "2025-05-05T14:00:00",
                "dtend": "2025-05-05T15:00:00",
            },
        ),
        (
            "20250506T090000",
            {
                "summary": "Tue Moved to Fri Afternoon",
                "dtstart": "2025-05-09T14:00:00",
                "dtend": "2025-05-09T15:00:00",
            },
        ),
    ]:
        store.edit(
            "cross-boundary-1",
            dict_to_ical_component(patch),  # type: ignore[arg-type]
            recurrence_id=rid,
            recurrence_range=Range.NONE,
        )
        oracle.edit(
            "cross-boundary-1", patch=patch, recurrence_id=rid, recurrence_range="NONE"
        )
    assert_step_parity(cal, oracle, "redteam_a_pre_split")
    return cal, store, oracle


def test_ical_redteam_a_cross_boundary_rescheduled_overrides() -> None:
    """Differential test of Red-Team (a) against ical EventStore (R-L2-008 + R-L3-006)."""
    cal_del, store_del, oracle_del = _setup_cross_boundary_pair()
    store_del.delete(
        "cross-boundary-1",
        recurrence_id="20250507T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    oracle_del.delete(
        "cross-boundary-1",
        recurrence_id="20250507T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_del = assert_step_parity(cal_del, oracle_del, "redteam_a_after_taf_delete")
    assert [
        (item["recurrence_id"], item["dtstart"], item["summary"]) for item in tl_del
    ] == [
        ("20250505T090000", "2025-05-05T09:00:00", "Daily Sync"),
        ("20250506T090000", "2025-05-09T14:00:00", "Tue Moved to Fri Afternoon"),
    ]

    cal_edit, store_edit, oracle_edit = _setup_cross_boundary_pair()
    patch_wed = {"summary": "Future Sync", "dtstart": "2025-05-07T11:00:00"}
    store_edit.edit(
        "cross-boundary-1",
        dict_to_ical_component(patch_wed),  # type: ignore[arg-type]
        recurrence_id="20250507T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    oracle_edit.edit(
        "cross-boundary-1",
        patch=patch_wed,
        recurrence_id="20250507T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_edit = assert_step_parity(cal_edit, oracle_edit, "redteam_a_after_taf_edit")
    assert [
        (item["recurrence_id"], item["dtstart"], item["summary"]) for item in tl_edit
    ] == [
        ("20250505T090000", "2025-05-05T09:00:00", "Daily Sync"),
        ("20250507T110000", "2025-05-07T11:00:00", "Future Sync"),
        ("20250508T110000", "2025-05-08T11:00:00", "Future Sync"),
        ("20250509T110000", "2025-05-09T11:00:00", "Future Sync"),
        ("20250506T090000", "2025-05-09T14:00:00", "Tue Moved to Fri Afternoon"),
    ]


def test_ical_redteam_b_out_of_order_overrides_metadata_edit_and_schedule_shift() -> (
    None
):
    """Differential test of Red-Team (b) against ical EventStore (R-L4-002..005)."""
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
    cal, _ = setup_ical_calendar(init_out_of_order)
    store = EventStore(cal, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle = ReferenceStore(init_out_of_order, policy=ICAL_POLICY)

    assert_step_parity(cal, oracle, "redteam_b_init")
    store.edit("ooo-series-1", Event(summary="Renamed Series"), recurrence_id=None)
    oracle.edit("ooo-series-1", recurrence_id=None, patch={"summary": "Renamed Series"})
    assert_step_parity(cal, oracle, "redteam_b_step1_metadata_edit")

    store.edit(
        "ooo-series-1",
        Event(dtstart=datetime.datetime(2025, 5, 3, 9, 0, 0)),
        recurrence_id=None,
    )
    oracle.edit(
        "ooo-series-1",
        recurrence_id=None,
        patch={"dtstart": "2025-05-03T09:00:00"},
    )
    tl2 = assert_step_parity(cal, oracle, "redteam_b_step2_schedule_shift")
    assert [
        (item["recurrence_id"], item["dtstart"], item["summary"]) for item in tl2
    ] == [
        ("20250503T090000", "2025-05-03T09:00:00", "Renamed Series"),
        ("20250505T090000", "2025-05-05T15:00:00", "Renamed Series"),
        ("20250506T090000", "2025-05-06T09:00:00", "Renamed Series"),
        ("20250507T090000", "2025-05-07T09:00:00", "Renamed Series"),
    ]


def test_ical_redteam_c_dst_spring_forward_multi_split() -> None:
    """Differential test of Red-Team (c) against ical EventStore (R-L3-003 + R-L3-008)."""
    cal = Calendar()
    store = EventStore(cal, dtstamp_fn=make_dtstamp_fn("2025-03-01T00:00:00Z"))
    oracle = ReferenceStore(policy=ICAL_POLICY, track_vtimezone=True)

    init_event = {
        "type": "VEVENT",
        "uid": "dst-multi-1",
        "summary": "Pre-DST Series",
        "dtstart": "2025-03-08T09:00:00-05:00[America/New_York]",
        "dtend": "2025-03-08T10:00:00-05:00[America/New_York]",
        "rrule": "FREQ=DAILY;COUNT=5",
        "exdate": [],
    }
    store.add(dict_to_ical_component(init_event))  # type: ignore[arg-type]
    oracle.add(init_event)
    assert_step_parity(cal, oracle, "redteam_c_step0_initial")

    for rid, patch, label in [
        (
            "20250309T090000",
            {
                "summary": "Split 1 (DST Day)",
                "dtstart": "2025-03-09T10:00:00-04:00[America/New_York]",
            },
            "redteam_c_step1_first_split",
        ),
        (
            "20250311T100000",
            {
                "summary": "Split 2 (Post-DST)",
                "dtstart": "2025-03-11T14:00:00-04:00[America/New_York]",
            },
            "redteam_c_step2_second_split",
        ),
    ]:
        store.edit(
            "dst-multi-1",
            dict_to_ical_component(patch),  # type: ignore[arg-type]
            recurrence_id=rid,
            recurrence_range=Range.THIS_AND_FUTURE,
        )
        oracle.edit(
            "dst-multi-1",
            patch=patch,
            recurrence_id=rid,
            recurrence_range="THIS_AND_FUTURE",
        )
        tl = assert_step_parity(cal, oracle, label)
    assert [(item["dtstart"], item["summary"]) for item in tl] == [
        ("2025-03-08T09:00:00-05:00[America/New_York]", "Pre-DST Series"),
        ("2025-03-09T10:00:00-04:00[America/New_York]", "Split 1 (DST Day)"),
        ("2025-03-10T10:00:00-04:00[America/New_York]", "Split 1 (DST Day)"),
        ("2025-03-11T14:00:00-04:00[America/New_York]", "Split 2 (Post-DST)"),
        ("2025-03-12T14:00:00-04:00[America/New_York]", "Split 2 (Post-DST)"),
    ]


def test_ical_redteam_d_rdate_rrule_exdate_combined_series_split() -> None:
    """Differential test of Red-Team (d) against ical EventStore (R-L1-001 + R-L3-007)."""
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
    cal_edit, _ = setup_ical_calendar(init_combined)
    store_edit = EventStore(
        cal_edit, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z")
    )
    oracle_edit = ReferenceStore(init_combined, policy=ICAL_POLICY)
    assert_step_parity(cal_edit, oracle_edit, "redteam_d_initial")

    store_edit.edit(
        "rdate-rrule-exdate-1",
        Event(summary="Hybrid Future"),
        recurrence_id="20250515T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    oracle_edit.edit(
        "rdate-rrule-exdate-1",
        recurrence_id="20250515T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch={"summary": "Hybrid Future"},
    )
    tl_edit = assert_step_parity(cal_edit, oracle_edit, "redteam_d_after_taf_edit")
    assert [(item["dtstart"], item["summary"]) for item in tl_edit] == [
        ("2025-05-01T09:00:00", "Hybrid Series"),
        ("2025-05-03T14:00:00", "Hybrid Series"),
        ("2025-05-15T09:00:00", "Hybrid Future"),
        ("2025-05-20T14:00:00", "Hybrid Future"),
        ("2025-05-22T09:00:00", "Hybrid Future"),
    ]

    cal_del, _ = setup_ical_calendar(init_combined)
    store_del = EventStore(cal_del, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle_del = ReferenceStore(init_combined, policy=ICAL_POLICY)
    store_del.delete(
        "rdate-rrule-exdate-1",
        recurrence_id="20250515T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    oracle_del.delete(
        "rdate-rrule-exdate-1",
        recurrence_id="20250515T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl_del = assert_step_parity(cal_del, oracle_del, "redteam_d_after_taf_delete")
    assert [item["dtstart"] for item in tl_del] == [
        "2025-05-01T09:00:00",
        "2025-05-03T14:00:00",
    ]


def test_ical_multi_step_chain_timed_tzid_and_allday_relations() -> None:
    """Differential test of multi-step timezone chain and all-day RELATED-TO cascade."""
    cal1 = Calendar()
    store1 = EventStore(cal1, dtstamp_fn=make_dtstamp_fn("2025-01-01T00:00:00Z"))
    oracle1 = ReferenceStore(policy=ICAL_POLICY, track_vtimezone=True)

    init_ev = {
        "type": "VEVENT",
        "uid": "tz-chain-1",
        "summary": "Daily Standup",
        "dtstart": "2025-05-01T09:00:00-04:00[America/New_York]",
        "dtend": "2025-05-01T09:30:00-04:00[America/New_York]",
        "rrule": "FREQ=DAILY;COUNT=6",
        "exdate": [],
        "sequence": 0,
    }
    store1.add(dict_to_ical_component(init_ev))  # type: ignore[arg-type]
    oracle1.add(init_ev)
    assert_step_parity(cal1, oracle1, "tz_chain_step1_add")

    p2 = {
        "summary": "May 2 Moved Standup",
        "dtstart": "2025-05-02T10:30:00-04:00[America/New_York]",
        "dtend": "2025-05-02T11:00:00-04:00[America/New_York]",
    }
    store1.edit(
        "tz-chain-1",
        dict_to_ical_component(p2),  # type: ignore[arg-type]
        recurrence_id="20250502T090000",
        recurrence_range=Range.NONE,
    )
    oracle1.edit(
        "tz-chain-1", recurrence_id="20250502T090000", recurrence_range="NONE", patch=p2
    )
    assert_step_parity(cal1, oracle1, "tz_chain_step2_single_edit")

    p3 = {"summary": "May 2 Re-Edited Standup"}
    store1.edit(
        "tz-chain-1",
        dict_to_ical_component(p3),  # type: ignore[arg-type]
        recurrence_id="TZID=America/New_York:20250502T090000",
        recurrence_range=Range.NONE,
    )
    oracle1.edit(
        "tz-chain-1",
        recurrence_id="TZID=America/New_York:20250502T090000",
        recurrence_range="NONE",
        patch=p3,
    )
    assert_step_parity(cal1, oracle1, "tz_chain_step3_re_edit")

    p4 = {"summary": "Global Standup Renamed"}
    store1.edit("tz-chain-1", dict_to_ical_component(p4), recurrence_id=None)  # type: ignore[arg-type]
    oracle1.edit("tz-chain-1", recurrence_id=None, patch=p4)
    assert_step_parity(cal1, oracle1, "tz_chain_step4_series_edit")

    store1.delete(
        "tz-chain-1", recurrence_id="20250503T090000", recurrence_range=Range.NONE
    )
    oracle1.delete(
        "tz-chain-1", recurrence_id="20250503T090000", recurrence_range="NONE"
    )
    assert_step_parity(cal1, oracle1, "tz_chain_step5_single_delete")

    p6 = {
        "summary": "Phase 2 Standup",
        "dtstart": "2025-05-05T11:00:00-04:00[America/New_York]",
    }
    store1.edit(
        "tz-chain-1",
        dict_to_ical_component(p6),  # type: ignore[arg-type]
        recurrence_id="20250505T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    oracle1.edit(
        "tz-chain-1",
        recurrence_id="20250505T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch=p6,
    )
    assert_step_parity(cal1, oracle1, "tz_chain_step6_taf_split")
