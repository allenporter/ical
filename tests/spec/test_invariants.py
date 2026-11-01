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

from .invariant_harness import ALL_INVARIANTS, CheckedStore, check_scenario_vectors
from .invariant_registry import REGISTRY_SCOPES, run_example
from .invariant_schema import InvariantExample, SpecInvariant, verify_invariants
from .oracle_policy import StoreError, policy_from_modes
from .scenario_runner import dispatch_scenario_operation
from .schema import FORBIDDEN_IMPLEMENTATION_TERMS, SPEC_DIR, load_all_scenarios

ALL_SCENARIOS = load_all_scenarios()

# Scenarios that violate an invariant before the NEW_UID split model is adopted
# (all are SHARED_UID splits failing I-C-006). Removed by the NEW_UID change.
KNOWN_VIOLATIONS: frozenset[str] = frozenset(
    {
        "R-L3-001[0]",
        "R-L3-004[0]",
        "R-L3-004[1]",
        "R-L3-004[2]",
        "R-L3-005[0]",
        "R-L3-005[1]",
        "R-L3-008[0]",
    }
)

INVARIANT_MODULES = [
    "invariant_common.py",
    "invariant_timeline.py",
    "invariant_component.py",
    "invariant_calendar.py",
    "invariant_transition.py",
    "invariant_registry.py",
    "invariant_schema.py",
    "invariant_harness.py",
]


def _scenario_params() -> list[Any]:
    params = []
    for rule_id, idx, name, scen in ALL_SCENARIOS:
        key = f"{rule_id}[{idx}]"
        marks = (
            [pytest.mark.xfail(reason="SHARED_UID split violates I-C-006", strict=True)]
            if key in KNOWN_VIOLATIONS
            else []
        )
        params.append(pytest.param(scen, id=f"{key}-{name}", marks=marks))
    return params


def _examples(positive: bool) -> list[Any]:
    return [
        pytest.param(inv, ex, id=f"{inv.id}-{ex.name}")
        for inv in ALL_INVARIANTS
        for ex in (inv.positive_examples if positive else inv.negative_examples)
    ]


def test_invariant_definitions_verify() -> None:
    """All invariants validate, cite correctly, are clean-room and cover the registry."""
    assert len(ALL_INVARIANTS) == 25
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
