"""Tests for the first-class invariant layer (`invariants/I-*.json`).

* Every invariant validates, cites the bundled RFCs byte-for-byte, and maps 1:1 onto
  an executable clean-room predicate.
* Every positive example passes and every negative example fails its predicate.
* COMPONENT/CALENDAR invariants hold for every scenario's initial and expected
  components; TRANSITION invariants hold for every scenario's (initial -> expected).
* All invariants hold on the live oracle state for every scenario (including
  atomicity on failure and order-independence via permuted replays).
"""

from __future__ import annotations

from typing import Any

import pytest

from .invariant_common import Transition
from .invariant_harness import ALL_INVARIANTS, CheckedStore, check_scenario_vectors
from .invariant_registry import REGISTRY_SCOPES, check_transition, run_example
from .invariant_schema import InvariantExample, SpecInvariant, verify_invariants
from .invariant_timeline import expand_occurrences
from .oracle_policy import StoreError, policy_from_modes
from .reference_oracle import ReferenceStore
from .scenario_runner import dispatch_scenario_operation
from .schema import FORBIDDEN_IMPLEMENTATION_TERMS, SPEC_DIR, load_all_scenarios
from .test_reference_oracle import ALL_48_POLICIES

ALL_SCENARIOS = load_all_scenarios()

INVARIANT_MODULES = [
    "invariant_common.py",
    "invariant_timeline.py",
    "invariant_component.py",
    "invariant_calendar.py",
    "invariant_transition.py",
    "invariant_registry.py",
    "invariant_schema.py",
    "invariant_harness.py",
    "operation_schema.py",
    "oracle_duration.py",
    "oracle_tz.py",
    "oracle_temporal.py",
    "oracle_canonical.py",
    "oracle_schedule.py",
    "oracle_base.py",
    "oracle_split.py",
    "oracle_edit.py",
    "oracle_policy.py",
    "reference_oracle.py",
    "scenario_runner.py",
]


def _scenario_params() -> list[Any]:
    return [
        pytest.param(scen, id=f"{rule_id}[{idx}]-{name}")
        for rule_id, idx, name, scen in ALL_SCENARIOS
    ]


def _examples(positive: bool) -> list[Any]:
    return [
        pytest.param(inv, ex, id=f"{inv.id}-{ex.name}")
        for inv in ALL_INVARIANTS
        for ex in (inv.positive_examples if positive else inv.negative_examples)
    ]


def test_invariant_definitions_verify() -> None:
    """All invariants validate, cite correctly, are clean-room and cover the registry."""
    assert len(ALL_INVARIANTS) == 29
    assert not verify_invariants(ALL_INVARIANTS, REGISTRY_SCOPES)


def test_registry_and_invariants_are_in_bijection() -> None:
    """Every `check` exists in the registry and every registry predicate is used once."""
    used = [inv.check for inv in ALL_INVARIANTS]
    assert sorted(used) == sorted(REGISTRY_SCOPES)
    for inv in ALL_INVARIANTS:
        assert REGISTRY_SCOPES[inv.check] == inv.scope


@pytest.mark.parametrize(("inv", "example"), _examples(positive=True))
def test_positive_example_passes(inv: SpecInvariant, example: InvariantExample) -> None:
    """A positive example MUST satisfy its invariant."""
    assert not run_example(inv, example)


@pytest.mark.parametrize(("inv", "example"), _examples(positive=False))
def test_negative_example_fails(inv: SpecInvariant, example: InvariantExample) -> None:
    """A negative example MUST violate its invariant (no check is vacuous)."""
    assert run_example(inv, example)


@pytest.mark.parametrize("scenario", _scenario_params())
def test_scenario_vectors_satisfy_invariants(scenario: dict[str, Any]) -> None:
    """Initial/expected components and initial->expected satisfy every invariant."""
    errors = check_scenario_vectors(scenario)
    assert not errors, errors


@pytest.mark.parametrize("scenario", _scenario_params())
def test_oracle_states_satisfy_invariants(scenario: dict[str, Any]) -> None:
    """The live oracle state satisfies every invariant before and after the operation."""
    store = CheckedStore(
        scenario["initial_components"],
        policy_from_modes(scenario.get("modes")),
        legacy_input=bool(scenario.get("legacy_input")),
        strict=False,
    )
    try:
        dispatch_scenario_operation(store, scenario["operation"])
    except StoreError:
        pass
    assert not store.violations, store.violations


@pytest.mark.parametrize("fname", INVARIANT_MODULES)
def test_invariant_modules_are_clean_room(fname: str) -> None:
    """Invariant predicates import nothing from `ical` and name no implementation symbol."""
    text = (SPEC_DIR / fname).read_text(encoding="utf-8")
    assert "import ical" not in text
    assert "from ical" not in text
    for term in FORBIDDEN_IMPLEMENTATION_TERMS:
        assert term not in text, f"{fname}: forbidden term {term!r}"


def test_floating_and_zoned_series_transitions_satisfy_invariants() -> None:
    """Whole-series floating <-> TZID transitions satisfy I-K-004 and I-T-005 under all 48 policies."""
    for policy in ALL_48_POLICIES:
        store = CheckedStore(policy=policy)
        store.add(
            {
                "uid": "fl-tz-1",
                "summary": "Standup",
                "dtstart": "2025-05-01T09:00:00",
                "dtend": "2025-05-01T09:30:00",
                "rrule": "FREQ=DAILY;UNTIL=20250503T090000",
                "rdate": ["2025-05-05T09:00:00"],
            }
        )
        store.delete("fl-tz-1", "20250502T090000", "NONE")
        store.edit("fl-tz-1", {"summary": "Ov"}, recurrence_id="20250503T090000")
        store.edit(
            "fl-tz-1",
            {
                "dtstart": "2025-05-01T09:00:00-04:00[America/New_York]",
                "dtend": "2025-05-01T09:30:00-04:00[America/New_York]",
            },
        )
        assert len(store.expand_timeline()) == 3
        store.edit("fl-tz-1", {"summary": "Zoned Ov"}, recurrence_id="20250502T090000")
        store.edit(
            "fl-tz-1",
            {"dtstart": "2025-05-01T10:00:00", "dtend": "2025-05-01T10:30:00"},
        )
        assert len(store.expand_timeline()) == 2


def test_canonical_rrule_duration_and_minted_uid_avoid_false_positives() -> None:
    """Serializer re-ordering (RRULE/DURATION) and fresh split UUIDs pass transitions."""
    before = [
        {
            "type": "VEVENT",
            "uid": "u1",
            "summary": "Sync",
            "dtstart": "2025-05-05T09:00:00",
            "duration": "PT60M",
            "rrule": "FREQ=WEEKLY;BYDAY=WE,MO;COUNT=4",
            "sequence": 0,
            "created": "2025-05-01T00:00:00Z",
            "dtstamp": "2025-05-01T00:00:00Z",
        }
    ]
    after = [
        {
            **before[0],
            "duration": "PT1H",
            "rrule": "COUNT=4;BYDAY=MO,WE;FREQ=WEEKLY",
        }
    ]
    assert not check_transition(
        ALL_INVARIANTS,
        Transition(before=before, operation={"op": "edit", "uid": "u1"}, after=after),
    )

    split_before = [
        {
            "type": "VEVENT",
            "uid": "s1",
            "summary": "Daily",
            "dtstart": "2025-05-01T09:00:00",
            "duration": "PT1H",
            "rrule": "FREQ=DAILY;COUNT=5",
            "exdate": ["2025-05-02T09:00:00", "2025-05-03T09:00:00"],
            "sequence": 0,
        }
    ]

    def _split_state(new_uid: str, exdates: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "type": "VEVENT",
                "uid": "s1",
                "summary": "Daily",
                "dtstart": "2025-05-01T09:00:00",
                "duration": "PT1H",
                "rrule": "FREQ=DAILY;UNTIL=20250504T085959",
                "exdate": exdates,
                "sequence": 1,
                "related_to": [{"uid": new_uid, "reltype": "NEXT"}],
            },
            {
                "type": "VEVENT",
                "uid": new_uid,
                "summary": "Renamed",
                "dtstart": "2025-05-04T09:00:00",
                "duration": "PT1H",
                "rrule": "FREQ=DAILY;COUNT=2",
                "sequence": 0,
                "related_to": [{"uid": "s1", "reltype": "FIRST"}],
            },
        ]

    t_split = Transition(
        before=split_before,
        operation={
            "op": "edit",
            "uid": "s1",
            "recurrence_id": "20250504T090000",
            "range": "THIS_AND_FUTURE",
            "patch": {"summary": "Renamed"},
        },
        after=_split_state(
            "uuid-run-1", ["2025-05-02T09:00:00", "2025-05-03T09:00:00"]
        ),
        permuted_afters=[
            _split_state("uuid-run-2", ["2025-05-03T09:00:00", "2025-05-02T09:00:00"])
        ],
    )
    assert not check_transition(ALL_INVARIANTS, t_split)


def test_live_transition_rejects_stripped_metadata_and_missing_override_dtstart() -> (
    None
):
    """Stripping SEQUENCE/CREATED/DTSTAMP on live transitions or override DTSTART fails."""
    before = [
        {
            "type": "VEVENT",
            "uid": "u1",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
            "sequence": 2,
            "created": "2025-05-01T00:00:00Z",
            "dtstamp": "2025-05-01T00:00:00Z",
        }
    ]
    stripped = [
        {
            "type": "VEVENT",
            "uid": "u1",
            "dtstart": "2025-05-01T09:00:00",
            "dtend": "2025-05-01T10:00:00",
        }
    ]
    errs = check_transition(
        ALL_INVARIANTS,
        Transition(
            before=before, operation={"op": "edit", "uid": "u1"}, after=stripped
        ),
    )
    assert any("I-T-005" in e and "sequence decreased" in e for e in errs)
    assert any("I-T-005" in e and "created changed" in e for e in errs)
    assert any("I-T-006" in e and "dtstamp removed" in e for e in errs)

    with pytest.raises(StoreError, match="missing dtstart"):
        expand_occurrences(
            [
                {
                    "type": "VEVENT",
                    "uid": "s1",
                    "dtstart": "2025-05-01T09:00:00",
                    "duration": "PT1H",
                    "rrule": "FREQ=DAILY;COUNT=2",
                },
                {
                    "type": "VEVENT",
                    "uid": "s1",
                    "recurrence_id": "20250502T09:00:00",
                },
            ]
        )


def test_checked_store_supports_pluggable_store_factory() -> None:
    """CheckedStore can wrap an external store factory without inheriting its state."""
    store = CheckedStore(store_factory=lambda comps: ReferenceStore(comps))
    store.add(
        {
            "uid": "ext-1",
            "summary": "Pluggable",
            "dtstart": "2025-05-01T09:00:00Z",
            "dtend": "2025-05-01T10:00:00Z",
            "rrule": "FREQ=DAILY;COUNT=3",
        }
    )
    store.edit("ext-1", {"summary": "One"}, recurrence_id="20250502T090000Z")
    store.delete("ext-1", "20250503T090000Z", "NONE")
    assert not store.violations
    assert len(store.components) == 2
