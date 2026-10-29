"""Comprehensive verification test suite for the clean-room Reference Store Oracle."""

# pylint: disable=duplicate-code,line-too-long

from __future__ import annotations

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
    execute_scenario,
)
from .schema import (
    FORBIDDEN_IMPLEMENTATION_TERMS,
    RULES_DIR,
    SPEC_DIR as SPEC_ENGINE_DIR,
    load_all_scenarios,
    load_rules_from_path,
    verify_path,
)
from .test_verify_scenarios import verify_scenario

ALL_SCENARIOS = load_all_scenarios()

ALL_POLICY_CONFIGS = [
    PolicyConfig(
        series_edit_override_mode=s_mode,
        this_and_future_split_mode=t_mode,
        single_edit_exdate_mode=e_mode,
    )
    for s_mode, t_mode, e_mode in itertools.product(
        SeriesEditOverrideMode,
        ThisAndFutureSplitMode,
        SingleEditExdateMode,
    )
]


def assert_rfc_invariants(store: ReferenceStore, label: str) -> list[dict[str, Any]]:
    """Expand timeline on store and assert zero RFC structural/mathematical errors via verify_scenario."""
    timeline = store.expand_timeline()
    synthetic_scenario = {
        "name": label,
        "initial_components": [],
        "operation": {"op": "verify_state"},
        "expected_components": store.components,
        "expected_timeline": timeline,
    }
    errors = verify_scenario("ORACLE-INVARIANT", synthetic_scenario)
    assert not errors, f"RFC invariant violations at {label}: {errors}"
    return timeline


def test_scenario_count_and_rule_count() -> None:
    """Ensure all 39 rules and 50 scenarios are discovered."""
    rule_files = list(RULES_DIR.rglob("*.json"))
    assert len(rule_files) == 39
    assert len(ALL_SCENARIOS) == 50


@pytest.mark.parametrize(
    ("rule_id", "scen_idx", "scen_name", "scenario"),
    ALL_SCENARIOS,
    ids=[f"{r}[{i}]-{n}" for r, i, n, _ in ALL_SCENARIOS],
)
def test_all_47_rule_scenarios(
    rule_id: str, scen_idx: int, scen_name: str, scenario: dict[str, Any]
) -> None:
    """Execute each of the 47 MiniScenarioVectors and assert exact component and timeline equality."""
    actual_components, actual_timeline = execute_scenario(scenario)
    assert actual_components == scenario["expected_components"], (
        f"[{rule_id} #{scen_idx} {scen_name}] actual_components != expected_components"
    )
    assert actual_timeline == scenario["expected_timeline"], (
        f"[{rule_id} #{scen_idx} {scen_name}] actual_timeline != expected_timeline"
    )


def test_invalid_operations_raise_store_error_without_mutation() -> None:
    """Verify invalid operations (R-L2-007, R-L5-005, R-L5-006, R-L5-007, R-L1-006) raise StoreError."""
    store = ReferenceStore(
        [
            {
                "type": "VEVENT",
                "uid": "rrule-err-1",
                "summary": "Weekly Sync",
                "dtstart": "2025-05-05T09:00:00",
                "dtend": "2025-05-05T09:30:00",
                "rrule": "FREQ=WEEKLY;COUNT=3",
            }
        ]
    )
    with pytest.raises(StoreError, match="Can't update single instance with rrule"):
        store.edit(
            uid="rrule-err-1",
            recurrence_id="20250512T090000",
            recurrence_range="NONE",
            patch={"rrule": "FREQ=DAILY;COUNT=2"},
        )
    assert len(store.components) == 1

    empty_store = ReferenceStore()
    with pytest.raises(StoreError, match="Fixed-offset datetime"):
        empty_store.add(
            {
                "type": "VTODO",
                "uid": "bad-tz-todo",
                "summary": "Bad TZ task",
                "due": "2025-05-01T10:00:00+02:00",
            }
        )
    assert empty_store.components == []

    with pytest.raises(StoreError, match="Fixed-offset datetime"):
        store.edit(
            uid="rrule-err-1",
            patch={"dtstart": "2025-05-05T09:00:00-05:00"},
        )

    with pytest.raises(StoreError, match="Value type mismatch"):
        store.delete(
            uid="rrule-err-1",
            recurrence_id="20250505",
            recurrence_range="NONE",
        )


@pytest.mark.parametrize(
    "policy",
    ALL_POLICY_CONFIGS,
    ids=[
        f"{p.series_edit_override_mode.value}-{p.this_and_future_split_mode.value}-{p.single_edit_exdate_mode.value}"
        for p in ALL_POLICY_CONFIGS
    ],
)
def test_multi_step_chain_timed_tzid_across_all_8_policy_configs(
    policy: PolicyConfig,
) -> None:
    """Execute a 6-step operation chain on a timezone-aware series across all 8 PolicyConfig combinations."""
    store = ReferenceStore(policy=policy, track_vtimezone=True)
    store.add(
        {
            "type": "VEVENT",
            "uid": "tz-chain-1",
            "summary": "Daily Standup",
            "dtstart": "2025-05-01T09:00:00-04:00[America/New_York]",
            "dtend": "2025-05-01T09:30:00-04:00[America/New_York]",
            "rrule": "FREQ=DAILY;COUNT=6",
            "exdate": [],
            "sequence": 0,
        }
    )
    assert len(assert_rfc_invariants(store, "step1_add")) == 6

    store.edit(
        uid="tz-chain-1",
        recurrence_id="20250502T090000",
        recurrence_range="NONE",
        patch={
            "summary": "May 2 Moved Standup",
            "dtstart": "2025-05-02T10:30:00-04:00[America/New_York]",
            "dtend": "2025-05-02T11:00:00-04:00[America/New_York]",
        },
    )
    assert len(assert_rfc_invariants(store, "step2_single_edit")) == 6
    master = next(
        c
        for c in store.components
        if c.get("uid") == "tz-chain-1" and c.get("recurrence_id") is None
    )
    expected_exdate = (
        ["2025-05-02T09:00:00-04:00[America/New_York]"]
        if policy.single_edit_exdate_mode == SingleEditExdateMode.LEGACY_DUAL_EXDATE
        else []
    )
    assert master["exdate"] == expected_exdate

    store.edit(
        uid="tz-chain-1",
        recurrence_id="TZID=America/New_York:20250502T090000",
        recurrence_range="NONE",
        patch={"summary": "May 2 Re-Edited Standup"},
    )
    assert len(assert_rfc_invariants(store, "step3_re_edit_override")) == 6

    store.edit(
        uid="tz-chain-1",
        recurrence_id=None,
        recurrence_range="NONE",
        patch={"summary": "Global Standup Renamed"},
    )
    assert len(assert_rfc_invariants(store, "step4_whole_series_edit")) == 6
    ov_comp = next(
        c
        for c in store.components
        if c.get("uid") == "tz-chain-1" and c.get("recurrence_id") == "20250502T090000"
    )
    expected_ov_sum = (
        "Global Standup Renamed"
        if policy.series_edit_override_mode == SeriesEditOverrideMode.PROPAGATE_PATCH
        else "May 2 Re-Edited Standup"
    )
    assert ov_comp["summary"] == expected_ov_sum

    store.delete(
        uid="tz-chain-1", recurrence_id="20250503T090000", recurrence_range="NONE"
    )
    assert len(assert_rfc_invariants(store, "step5_single_delete")) == 5

    store.edit(
        uid="tz-chain-1",
        recurrence_id="20250505T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch={
            "summary": "Phase 2 Standup",
            "dtstart": "2025-05-05T11:00:00-04:00[America/New_York]",
        },
    )
    assert len(assert_rfc_invariants(store, "step6_this_and_future_split")) == 5
    uids = {c.get("uid") for c in store.components if c.get("type") != "VTIMEZONE"}
    if policy.this_and_future_split_mode == ThisAndFutureSplitMode.SHARED_UID:
        assert uids == {"tz-chain-1"}
    else:
        assert len(uids) == 2


@pytest.mark.parametrize(
    "policy",
    ALL_POLICY_CONFIGS,
    ids=[
        f"{p.series_edit_override_mode.value}-{p.this_and_future_split_mode.value}-{p.single_edit_exdate_mode.value}"
        for p in ALL_POLICY_CONFIGS
    ],
)
def test_multi_step_chain_allday_overrides_and_relations_across_all_8_policy_configs(
    policy: PolicyConfig,
) -> None:
    """Test all-day series, override purging on split/delete (R-L3-006), and RELATED-TO cascade (R-L5-007/008)."""
    store = ReferenceStore(policy=policy)
    store.add(
        {
            "type": "VEVENT",
            "uid": "allday-parent",
            "summary": "Sprint Day",
            "dtstart": "2025-05-01",
            "dtend": "2025-05-02",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": [],
            "sequence": 0,
        }
    )
    store.add(
        {
            "type": "VEVENT",
            "uid": "allday-child",
            "summary": "Sprint Retro Prep",
            "dtstart": "2025-05-01",
            "dtend": "2025-05-02",
            "related_to": [{"uid": "allday-parent", "reltype": "PARENT"}],
            "sequence": 0,
        }
    )
    assert len(assert_rfc_invariants(store, "allday_step1_add")) == 6

    store.edit(
        uid="allday-parent",
        recurrence_id="20250504",
        recurrence_range="NONE",
        patch={"summary": "Special Sprint Day 4"},
    )
    assert len(assert_rfc_invariants(store, "allday_step2_override")) == 6

    store.delete(
        uid="allday-parent",
        recurrence_id="20250503",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl3 = assert_rfc_invariants(store, "allday_step3_taf_delete")
    assert len(tl3) == 3
    assert any(c.get("uid") == "allday-child" for c in store.components)

    store.delete(
        uid="allday-parent",
        recurrence_id="20250501",
        recurrence_range="THIS_AND_FUTURE",
    )
    tl4 = assert_rfc_invariants(store, "allday_step4_full_delete_cascade")
    assert store.components == []
    assert tl4 == []


def test_series_reschedule_shift_with_series_mode() -> None:
    """Test SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES shifts EXDATE and override RECURRENCE-ID."""
    policy = PolicyConfig(
        series_reschedule_exception_mode=SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES
    )
    store = ReferenceStore(
        [
            {
                "type": "VEVENT",
                "uid": "shift-1",
                "recurrence_id": None,
                "summary": "Standup",
                "dtstart": "2025-05-01T09:00:00",
                "dtend": "2025-05-01T09:30:00",
                "rrule": "FREQ=DAILY;COUNT=4",
                "exdate": ["2025-05-02T09:00:00"],
            },
            {
                "type": "VEVENT",
                "uid": "shift-1",
                "recurrence_id": "20250503T090000",
                "summary": "Custom Day 3",
                "dtstart": "2025-05-03T11:00:00",
                "dtend": "2025-05-03T11:30:00",
                "rrule": None,
            },
        ],
        policy=policy,
    )
    store.edit(
        uid="shift-1", recurrence_id=None, patch={"dtstart": "2025-05-01T10:00:00"}
    )
    tl = assert_rfc_invariants(store, "shift_with_series")
    master = next(c for c in store.components if c.get("recurrence_id") is None)
    ov = next(c for c in store.components if c.get("recurrence_id") is not None)
    assert master["exdate"] == ["2025-05-02T10:00:00"]
    assert (ov["recurrence_id"], ov["dtstart"]) == (
        "20250503T100000",
        "2025-05-03T12:00:00",
    )
    assert [item["dtstart"] for item in tl] == [
        "2025-05-01T10:00:00",
        "2025-05-03T12:00:00",
        "2025-05-04T10:00:00",
    ]


@pytest.mark.parametrize("split_mode", list(ThisAndFutureSplitMode))
def test_split_future_override_migrate_mode(split_mode: ThisAndFutureSplitMode) -> None:
    """Test SplitFutureOverrideMode.MIGRATE_TO_FUTURE_SERIES under SHARED_UID and NEW_UID."""
    policy = PolicyConfig(
        this_and_future_split_mode=split_mode,
        split_future_override_mode=SplitFutureOverrideMode.MIGRATE_TO_FUTURE_SERIES,
    )
    store = ReferenceStore(
        [
            {
                "type": "VEVENT",
                "uid": "mig-1",
                "recurrence_id": None,
                "summary": "Sync",
                "dtstart": "2025-05-01T09:00:00",
                "dtend": "2025-05-01T10:00:00",
                "rrule": "FREQ=DAILY;COUNT=4",
            },
            {
                "type": "VEVENT",
                "uid": "mig-1",
                "recurrence_id": "20250504T090000",
                "summary": "Day 4 Custom",
                "dtstart": "2025-05-04T14:00:00",
                "dtend": "2025-05-04T15:00:00",
                "rrule": None,
            },
        ],
        policy=policy,
    )
    store.edit(
        uid="mig-1",
        recurrence_id="20250502T090000",
        recurrence_range="THIS_AND_FUTURE",
        patch={"dtstart": "2025-05-02T10:00:00"},
    )
    tl = assert_rfc_invariants(store, f"migrate_override_{split_mode.value}")
    ov = next(
        c
        for c in store.components
        if c.get("recurrence_id") is not None and not c.get("rrule")
    )
    assert (ov["recurrence_id"], ov["dtstart"], len(tl)) == (
        "20250504T100000",
        "2025-05-04T15:00:00",
        4,
    )


def test_parent_delete_cascade_modes_and_reltypes() -> None:
    """Test ParentDeleteCascadeMode (CASCADE_DELETE, DETACH_CHILDREN, LEAVE_DANGLING) and R-L5-009."""
    dt0, dt1 = "2025-05-01T09:00:00", "2025-05-01T10:00:00"
    base_comps = [
        {"uid": "p-1", "summary": "Parent", "dtstart": dt0, "dtend": dt1},
        {
            "uid": "c-omitted",
            "summary": "Omitted",
            "dtstart": dt0,
            "dtend": dt1,
            "related_to": [{"uid": "p-1"}],
        },
        {
            "uid": "c-xname",
            "summary": "X-Name",
            "dtstart": dt0,
            "dtend": dt1,
            "related_to": [{"uid": "p-1", "reltype": "X-DEPENDS-ON"}],
        },
        {
            "uid": "s-peer",
            "summary": "Sibling",
            "dtstart": dt0,
            "dtend": dt1,
            "related_to": [{"uid": "p-1", "reltype": "SIBLING"}],
        },
    ]
    st_cascade = ReferenceStore(
        base_comps,
        policy=PolicyConfig(
            parent_delete_cascade_mode=ParentDeleteCascadeMode.CASCADE_DELETE
        ),
    )
    st_cascade.delete("p-1")
    assert [c["uid"] for c in st_cascade.components] == ["s-peer"]

    st_detach = ReferenceStore(
        base_comps,
        policy=PolicyConfig(
            parent_delete_cascade_mode=ParentDeleteCascadeMode.DETACH_CHILDREN
        ),
    )
    st_detach.delete("p-1")
    assert [c["uid"] for c in st_detach.components] == [
        "c-omitted",
        "c-xname",
        "s-peer",
    ]
    assert st_detach.components[0]["related_to"] == []
    assert st_detach.components[1]["related_to"] == []
    assert st_detach.components[2]["related_to"] == [
        {"uid": "p-1", "reltype": "SIBLING"}
    ]

    st_dangling = ReferenceStore(
        base_comps,
        policy=PolicyConfig(
            parent_delete_cascade_mode=ParentDeleteCascadeMode.LEAVE_DANGLING
        ),
    )
    st_dangling.delete("p-1")
    assert len(st_dangling.components) == 3
    assert st_dangling.components[0]["related_to"] == [{"uid": "p-1"}]


def test_clean_room_and_full_rule_citation_coverage() -> None:
    """Verify clean-room oracle modules have 0 forbidden terms and cite all 38 rules."""
    cleanroom_files = [
        "oracle_temporal.py",
        "oracle_base.py",
        "oracle_edit.py",
        "reference_oracle.py",
        "scenario_runner.py",
        "test_verify_scenarios.py",
        "test_reference_oracle.py",
        "test_oracle_redteam.py",
    ]
    combined_oracle_text = ""
    for fname in cleanroom_files:
        fpath = SPEC_ENGINE_DIR / fname
        text = fpath.read_text(encoding="utf-8")
        if not fname.startswith("test_"):
            combined_oracle_text += text
        for term in FORBIDDEN_IMPLEMENTATION_TERMS:
            assert term not in text, (
                f"Clean-room violation in {fname}: forbidden term {term!r}"
            )

    for rule in load_rules_from_path(RULES_DIR):
        assert rule.id in combined_oracle_text, (
            f"Rule ID {rule.id} must be explicitly cited in the clean-room oracle modules"
        )

    num_rules, citation_errors = verify_path(RULES_DIR)
    assert num_rules == 39
    assert not citation_errors
