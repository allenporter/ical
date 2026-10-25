"""Tests for the PolicyMode registry and rule/scenario mode scoping."""

from __future__ import annotations

import dataclasses
import enum

import pytest

from .oracle_temporal import PolicyConfig
from .schema import (
    MiniScenarioVector,
    RULES_DIR,
    SpecRule,
    effective_scenario_modes,
    load_modes,
    load_rules_from_path,
    mode_coverage,
    verify_mode,
    verify_mode_scoping,
)

MODES = load_modes()
RULES = load_rules_from_path(RULES_DIR)


@pytest.mark.parametrize("mode_id", sorted(MODES))
def test_mode_definition_is_valid(mode_id: str) -> None:
    """Every mode is well-formed and its citations are grounded in the bundled RFCs."""
    assert not verify_mode(MODES[mode_id])


def test_policy_config_matches_mode_registry() -> None:
    """The oracle's PolicyConfig exposes exactly the registered modes and options."""
    fields = {f.name: f for f in dataclasses.fields(PolicyConfig)}
    assert set(fields) == set(MODES)
    for mode_id, mode in MODES.items():
        field = fields[mode_id]
        enum_cls = type(field.default)
        assert issubclass(enum_cls, enum.Enum)
        assert {m.value for m in enum_cls} == {opt.id for opt in mode.options}


def test_every_mode_is_referenced_by_a_rule() -> None:
    """Each recorded mode is relevant to at least one rule or scenario."""
    coverage = mode_coverage(RULES, MODES)
    unreferenced = [
        mode_id for mode_id, options in coverage.items() if not any(options.values())
    ]
    assert not unreferenced


def _rule(**kwargs: object) -> SpecRule:
    base = RULES[0].model_dump()
    base.update(kwargs)
    return SpecRule.model_validate(base)


def _scenario(modes: dict[str, str]) -> MiniScenarioVector:
    return RULES[0].scenarios[0].model_copy(update={"modes": modes})


def test_scoping_rejects_unknown_mode_and_option() -> None:
    """Typos in mode or option ids are reported."""
    rule = _rule(applies_under={"no_such_mode": ["X"]})
    assert any("unknown mode" in e for e in verify_mode_scoping(rule, MODES))
    rule = _rule(applies_under={"this_and_future_split_mode": ["NOPE"]})
    assert any("unknown options" in e for e in verify_mode_scoping(rule, MODES))


def test_scoping_rejects_redundant_all_options() -> None:
    """Listing every option is equivalent to mode-independence and must be omitted."""
    rule = _rule(
        applies_under={"this_and_future_split_mode": ["SHARED_UID", "NEW_UID"]}
    )
    assert any("lists every option" in e for e in verify_mode_scoping(rule, MODES))


def test_scoping_rejects_scenario_pin_outside_rule_scope() -> None:
    """A scenario cannot pin an option its rule does not apply under."""
    rule = _rule(applies_under={"this_and_future_split_mode": ["SHARED_UID"]})
    rule.scenarios = [_scenario({"this_and_future_split_mode": "NEW_UID"})]
    assert any(
        "outside the rule's applies_under" in e
        for e in verify_mode_scoping(rule, MODES)
    )


def test_effective_scenario_modes_combines_rule_and_scenario() -> None:
    """Scenario pins narrow the rule's scope; other modes remain as the rule declares."""
    rule = _rule(
        applies_under={
            "parent_delete_cascade_mode": [
                "CASCADE_DELETE",
                "DETACH_CHILDREN",
            ]
        }
    )
    scen = _scenario(
        {
            "parent_delete_cascade_mode": "CASCADE_DELETE",
            "this_and_future_split_mode": "SHARED_UID",
        }
    )
    assert effective_scenario_modes(rule, scen) == {
        "parent_delete_cascade_mode": ["CASCADE_DELETE"],
        "this_and_future_split_mode": ["SHARED_UID"],
    }
