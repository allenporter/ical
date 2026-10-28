"""Adversarial Differential Regression Tests for ical's EventStore and TodoStore."""

# pylint: disable=duplicate-code,line-too-long

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

from ical.calendar import Calendar
from ical.event import Event
from ical.exceptions import CalendarParseError, StoreError as IcalStoreError
from ical.store import EventStore, TodoStore
from ical.todo import Todo, TodoStatus
from ical.types import Period, Range, Recur

from .ical_bridge import (
    ICAL_POLICY,
    assert_step_parity,
    dict_to_ical_component,
    make_dtstamp_fn,
    setup_ical_calendar,
)
from .reference_oracle import ReferenceStore, StoreError as OracleStoreError


def _setup_resched_split_pair() -> tuple[Calendar, EventStore, ReferenceStore]:
    """Create a 5-day series already split and rescheduled at May 3."""
    base_init = [
        {
            "type": "VEVENT",
            "uid": "resched-split-1",
            "summary": "Phase 1",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": [],
        }
    ]
    patch_split = {"summary": "Phase 2", "dtstart": "2025-05-03T14:00:00"}
    cal, _ = setup_ical_calendar(base_init)
    store = EventStore(cal, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle = ReferenceStore(base_init, policy=ICAL_POLICY)
    store.edit(
        "resched-split-1",
        dict_to_ical_component(patch_split),  # type: ignore[arg-type]
        recurrence_id="20250503T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    oracle.edit(
        "resched-split-1",
        patch=patch_split,
        recurrence_id="20250503T090000",
        recurrence_range="THIS_AND_FUTURE",
    )
    return cal, store, oracle


def test_adversarial_round1_rescheduled_split_segment_start_edit_and_delete() -> None:
    """Adversarial test: THIS_AND_FUTURE edit/delete targeting a rescheduled split segment's start or recurrence_id."""
    for target_rid in ("20250503T140000", "20250503T090000"):
        cal, store, oracle = _setup_resched_split_pair()
        assert_step_parity(cal, oracle, f"resched_split_init_{target_rid}")
        store.delete(
            "resched-split-1",
            recurrence_id=target_rid,
            recurrence_range=Range.THIS_AND_FUTURE,
        )
        oracle.delete(
            "resched-split-1",
            recurrence_id=target_rid,
            recurrence_range="THIS_AND_FUTURE",
        )
        tl_del = assert_step_parity(cal, oracle, f"resched_split_del_{target_rid}")
        assert len(cal.events) == 1
        assert [item["dtstart"] for item in tl_del] == [
            "2025-05-01T09:00:00",
            "2025-05-02T09:00:00",
        ]

        cal2, store2, oracle2 = _setup_resched_split_pair()
        patch_re_edit = {"summary": "Phase 2 Renamed", "dtstart": "2025-05-03T16:00:00"}
        store2.edit(
            "resched-split-1",
            dict_to_ical_component(patch_re_edit),  # type: ignore[arg-type]
            recurrence_id=target_rid,
            recurrence_range=Range.THIS_AND_FUTURE,
        )
        oracle2.edit(
            "resched-split-1",
            patch=patch_re_edit,
            recurrence_id=target_rid,
            recurrence_range="THIS_AND_FUTURE",
        )
        tl_edit = assert_step_parity(cal2, oracle2, f"resched_split_edit_{target_rid}")
        assert len(cal2.events) == 2
        assert [(item["dtstart"], item["summary"]) for item in tl_edit] == [
            ("2025-05-01T09:00:00", "Phase 1"),
            ("2025-05-02T09:00:00", "Phase 1"),
            ("2025-05-03T16:00:00", "Phase 2 Renamed"),
            ("2025-05-04T16:00:00", "Phase 2 Renamed"),
            ("2025-05-05T16:00:00", "Phase 2 Renamed"),
        ]


def test_adversarial_round1_whole_series_edit_preserves_split_segments_and_todo_completed() -> (
    None
):
    """Adversarial test: whole-series metadata/status edit across split segments and overrides."""
    init_todos = [
        {
            "type": "VTODO",
            "uid": "todo-split-series-1",
            "summary": "Daily Chore",
            "dtstart": "2025-05-01T09:00:00Z",
            "due": "2025-05-01T10:00:00Z",
            "status": "NEEDS-ACTION",
            "completed": None,
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": [],
        }
    ]
    cal, _ = setup_ical_calendar(init_todos)
    store = TodoStore(cal, dtstamp_fn=make_dtstamp_fn("2025-05-01T12:00:00Z"))
    oracle = ReferenceStore(init_todos, policy=ICAL_POLICY)

    now_dt = datetime.datetime(2025, 5, 1, 12, 0, tzinfo=datetime.timezone.utc)
    for rid, rng_ical, rng_or, summ in [
        ("20250503T090000Z", Range.THIS_AND_FUTURE, "THIS_AND_FUTURE", "Phase 2 Chore"),
        ("20250504T090000Z", Range.NONE, "NONE", "May 4 Special Chore"),
    ]:
        store.edit(
            "todo-split-series-1",
            Todo(summary=summ, dtstamp=now_dt),
            recurrence_id=rid,
            recurrence_range=rng_ical,
        )
        oracle.edit(
            "todo-split-series-1",
            patch={"summary": summ},
            recurrence_id=rid,
            recurrence_range=rng_or,
            now="2025-05-01T12:00:00Z",
        )
        assert_step_parity(cal, oracle, f"todo_split_{rid}")

    store.edit(
        "todo-split-series-1",
        Todo(summary="All Completed", status=TodoStatus.COMPLETED, dtstamp=now_dt),
        recurrence_id=None,
    )
    oracle.edit(
        "todo-split-series-1",
        patch={"summary": "All Completed", "status": "COMPLETED"},
        recurrence_id=None,
        now="2025-05-01T12:00:00Z",
    )
    tl = assert_step_parity(cal, oracle, "todo_split_step3_whole_series_complete")
    assert len(tl) == 5
    for todo_comp in cal.todos:
        assert todo_comp.status == TodoStatus.COMPLETED
        assert todo_comp.completed == now_dt


def test_adversarial_round1_duration_dtend_period_and_cross_tz_rid() -> None:
    """Adversarial test: switching between duration and dtend, Period RDATE overrides, and cross-TZ recurrence_id."""
    cal = Calendar()
    store = EventStore(cal, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    store.add(
        Event(
            uid="dur-switch-1",
            summary="Duration Event",
            dtstart=datetime.datetime(2025, 5, 1, 9, 0),
            duration=datetime.timedelta(hours=1),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
        )
    )
    store.edit(
        "dur-switch-1",
        Event(
            summary="Explicit End Override", dtend=datetime.datetime(2025, 5, 2, 11, 0)
        ),
        recurrence_id="20250502T090000",
        recurrence_range=Range.NONE,
    )
    assert [e.end for e in cal.timeline] == [
        datetime.datetime(2025, 5, 1, 10, 0),
        datetime.datetime(2025, 5, 2, 11, 0),
        datetime.datetime(2025, 5, 3, 10, 0),
    ]

    cal2 = Calendar()
    store2 = EventStore(cal2, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    store2.add(
        Event(
            uid="period-rdate-1",
            summary="Base 1h Event",
            dtstart=datetime.datetime(2025, 5, 1, 9, 0),
            dtend=datetime.datetime(2025, 5, 1, 10, 0),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=2"),
            rdate=[
                Period(
                    start=datetime.datetime(2025, 5, 3, 14, 0),
                    end=datetime.datetime(2025, 5, 3, 16, 0),
                )
            ],
        )
    )
    store2.edit(
        "period-rdate-1",
        Event(summary="Edited 2h Period RDATE"),
        recurrence_id="20250503T140000",
        recurrence_range=Range.NONE,
    )
    tl2 = list(cal2.timeline)
    assert tl2[2].dtend == datetime.datetime(2025, 5, 3, 16, 0)
    assert tl2[2].summary == "Edited 2h Period RDATE"

    ny_tz = ZoneInfo("America/New_York")
    cal3 = Calendar()
    store3 = EventStore(cal3, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    store3.add(
        Event(
            uid="ny-utc-rid-1",
            summary="NY Morning",
            dtstart=datetime.datetime(2025, 5, 1, 9, 0, tzinfo=ny_tz),
            dtend=datetime.datetime(2025, 5, 1, 10, 0, tzinfo=ny_tz),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
        )
    )
    store3.edit(
        "ny-utc-rid-1",
        Event(summary="NY Day 2 Edited via UTC RID"),
        recurrence_id="20250502T130000Z",
        recurrence_range=Range.NONE,
    )
    tl3 = list(cal3.timeline)
    assert len(tl3) == 3
    assert tl3[1].summary == "NY Day 2 Edited via UTC RID"
    assert tl3[1].dtstart == datetime.datetime(2025, 5, 2, 9, 0, tzinfo=ny_tz)
    assert tl3[1].recurrence_id == "20250502T090000"


def test_adversarial_round2_first_and_segment_start_taf_exdate_cleanup() -> None:
    """Adversarial Round 2: first-instance and split-segment-start THIS_AND_FUTURE exdate cleanup."""
    base_init = [
        {
            "type": "VEVENT",
            "uid": "r2-first-inst-1",
            "summary": "Daily",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": [],
        }
    ]
    cal, _ = setup_ical_calendar(base_init)
    store = EventStore(cal, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle = ReferenceStore(base_init, policy=ICAL_POLICY)

    for rid, rng_ical, rng_or, summ in [
        ("20250503T090000", Range.NONE, "NONE", "May 3 Override"),
        ("20250501T090000", Range.THIS_AND_FUTURE, "THIS_AND_FUTURE", "Reset Series"),
    ]:
        store.edit(
            "r2-first-inst-1",
            Event(summary=summ),
            recurrence_id=rid,
            recurrence_range=rng_ical,
        )
        oracle.edit(
            "r2-first-inst-1",
            patch={"summary": summ},
            recurrence_id=rid,
            recurrence_range=rng_or,
        )
    assert len(assert_step_parity(cal, oracle, "r2_1a_after_first_instance_taf")) == 5

    cal_b, _ = setup_ical_calendar(base_init)
    store_b = EventStore(cal_b, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle_b = ReferenceStore(base_init, policy=ICAL_POLICY)
    for rid, rng_ical, rng_or, summ in [
        ("20250503T090000", Range.THIS_AND_FUTURE, "THIS_AND_FUTURE", "Seg 2"),
        ("20250504T090000", Range.NONE, "NONE", "May 4 Override on Seg 2"),
        ("20250503T090000", Range.THIS_AND_FUTURE, "THIS_AND_FUTURE", "Seg 2 Reset"),
    ]:
        store_b.edit(
            "r2-first-inst-1",
            Event(summary=summ),
            recurrence_id=rid,
            recurrence_range=rng_ical,
        )
        oracle_b.edit(
            "r2-first-inst-1",
            patch={"summary": summ},
            recurrence_id=rid,
            recurrence_range=rng_or,
        )
    assert len(assert_step_parity(cal_b, oracle_b, "r2_1b_after_seg_start_taf")) == 5


def test_adversarial_round2_date_datetime_transitions_and_zero_duration_todo() -> None:
    """Adversarial Round 2: DATE<->DATETIME whole-series transitions and 0-duration VTODO preservation."""
    init_date = [
        {
            "type": "VEVENT",
            "uid": "r2-type-trans-1",
            "summary": "All Day",
            "dtstart": "2025-05-01",
            "dtend": "2025-05-02",
            "rrule": "FREQ=DAILY;UNTIL=20250503",
            "rdate": ["2025-05-05"],
            "exdate": ["2025-05-02"],
        }
    ]
    cal_t, _ = setup_ical_calendar(init_date)
    store_t = EventStore(cal_t, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle_t = ReferenceStore(init_date, policy=ICAL_POLICY)

    store_t.edit(
        "r2-type-trans-1",
        Event(dtstart=datetime.datetime(2025, 5, 1, 9, 0)),
        recurrence_id=None,
    )
    oracle_t.edit(
        "r2-type-trans-1", patch={"dtstart": "2025-05-01T09:00:00"}, recurrence_id=None
    )
    assert len(assert_step_parity(cal_t, oracle_t, "r2_2_date_to_datetime")) == 3

    store_t.edit(
        "r2-type-trans-1", Event(dtstart=datetime.date(2025, 5, 1)), recurrence_id=None
    )
    oracle_t.edit(
        "r2-type-trans-1", patch={"dtstart": "2025-05-01"}, recurrence_id=None
    )
    assert len(assert_step_parity(cal_t, oracle_t, "r2_2_datetime_to_date")) == 3

    init_zero_todo = [
        {
            "type": "VTODO",
            "uid": "r2-zero-todo-1",
            "summary": "Same Day Todo",
            "dtstart": "2025-05-01",
            "due": "2025-05-01",
            "rrule": "FREQ=DAILY;UNTIL=20250503",
        }
    ]
    cal_zt, _ = setup_ical_calendar(init_zero_todo)
    store_zt = TodoStore(cal_zt, dtstamp_fn=make_dtstamp_fn("2025-05-01T00:00:00Z"))
    oracle_zt = ReferenceStore(init_zero_todo, policy=ICAL_POLICY)
    store_zt.edit(
        "r2-zero-todo-1",
        Todo(dtstart=datetime.datetime(2025, 5, 1, 9, 0)),
        recurrence_id=None,
    )
    oracle_zt.edit(
        "r2-zero-todo-1", patch={"dtstart": "2025-05-01T09:00:00"}, recurrence_id=None
    )
    assert len(assert_step_parity(cal_zt, oracle_zt, "r2_2b_zero_dur_todo")) == 3
    assert cal_zt.todos[0].due == datetime.datetime(2025, 5, 1, 9, 0)


def test_adversarial_round2_delete_override_metadata() -> None:
    """Adversarial Round 2: deleting an already-overridden instance (Range.NONE) does not bump master sequence."""
    init_seq = [
        {
            "type": "VEVENT",
            "uid": "r2-del-ov-1",
            "summary": "Daily Seq",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "rrule": "FREQ=DAILY;COUNT=3",
            "exdate": [],
            "sequence": 0,
            "dtstamp": "2025-05-01T00:00:00Z",
        }
    ]
    cal_s, _ = setup_ical_calendar(init_seq)
    store_s = EventStore(cal_s, dtstamp_fn=make_dtstamp_fn("2025-05-01T12:00:00Z"))
    oracle_s = ReferenceStore(init_seq, policy=ICAL_POLICY)

    store_s.edit(
        "r2-del-ov-1",
        Event(
            summary="May 2 Edited",
            dtstamp=datetime.datetime(2025, 5, 1, 12, 0, tzinfo=datetime.timezone.utc),
        ),
        recurrence_id="20250502T090000",
        recurrence_range=Range.NONE,
    )
    oracle_s.edit(
        "r2-del-ov-1",
        patch={"summary": "May 2 Edited"},
        recurrence_id="20250502T090000",
        recurrence_range="NONE",
        now="2025-05-01T12:00:00Z",
    )
    assert_step_parity(cal_s, oracle_s, "r2_3_after_edit")

    store_s.delete(
        "r2-del-ov-1", recurrence_id="20250502T090000", recurrence_range=Range.NONE
    )
    oracle_s.delete(
        "r2-del-ov-1",
        recurrence_id="20250502T090000",
        recurrence_range="NONE",
        now="2025-05-01T12:00:00Z",
    )
    assert len(assert_step_parity(cal_s, oracle_s, "r2_3_after_delete_override")) == 2


def test_ical_invalid_operations_raise_store_error() -> None:
    """Verify invalid operations raise StoreError on both ical and ReferenceStore."""
    init_comps = [
        {
            "type": "VEVENT",
            "uid": "rrule-err-1",
            "summary": "Weekly Sync",
            "dtstart": "2025-05-05T09:00:00",
            "dtend": "2025-05-05T09:30:00",
            "rrule": "FREQ=WEEKLY;COUNT=3",
        }
    ]
    cal, _ = setup_ical_calendar(init_comps)
    store = EventStore(cal)
    oracle = ReferenceStore(init_comps, policy=ICAL_POLICY)

    with pytest.raises(IcalStoreError, match="single instance with rrule"):
        store.edit(
            "rrule-err-1",
            Event(rrule=Recur.from_rrule("FREQ=DAILY;COUNT=2")),
            recurrence_id="20250512T090000",
            recurrence_range=Range.NONE,
        )
    with pytest.raises(OracleStoreError, match="single instance with rrule"):
        oracle.edit(
            "rrule-err-1",
            recurrence_id="20250512T090000",
            recurrence_range="NONE",
            patch={"rrule": "FREQ=DAILY;COUNT=2"},
        )
    assert len(cal.events) == 1

    cal_todo = Calendar()
    todo_store = TodoStore(cal_todo)
    oracle_empty = ReferenceStore(policy=ICAL_POLICY)
    bad_todo = {
        "type": "VTODO",
        "uid": "bad-tz-todo",
        "summary": "Bad TZ task",
        "due": "2025-05-01T10:00:00+02:00",
    }
    with pytest.raises(IcalStoreError):
        todo_store.add(dict_to_ical_component(bad_todo, default_is_todo=True))  # type: ignore[arg-type]
    with pytest.raises(OracleStoreError):
        oracle_empty.add(bad_todo)
    assert len(cal_todo.todos) == 0

    with pytest.raises(IcalStoreError):
        store.delete(
            "rrule-err-1", recurrence_id="20250505", recurrence_range=Range.NONE
        )
    with pytest.raises(OracleStoreError):
        oracle.delete("rrule-err-1", recurrence_id="20250505", recurrence_range="NONE")

    with pytest.raises(CalendarParseError, match="DTSTART had UTC or local"):
        Event(
            summary="Bad UNTIL",
            dtstart=datetime.datetime(
                2025, 5, 1, 9, 0, tzinfo=ZoneInfo("America/New_York")
            ),
            dtend=datetime.datetime(
                2025, 5, 1, 10, 0, tzinfo=ZoneInfo("America/New_York")
            ),
            rrule=Recur.from_rrule("FREQ=DAILY;UNTIL=20250505T090000"),
        )
