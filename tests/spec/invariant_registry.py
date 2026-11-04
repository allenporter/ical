"""Registry and runners for the executable invariant predicates.

Maps each `SpecInvariant.check` key to its predicate and provides helpers that apply a
set of invariants to a calendar state or a transition.
"""

from __future__ import annotations

from collections.abc import Iterable

from .invariant_calendar import CALENDAR_CHECKS
from .invariant_common import CheckContext, Component, Transition, items
from .invariant_component import COMPONENT_CHECKS
from .invariant_schema import InvariantExample, InvariantScope, SpecInvariant
from .invariant_transition import TRANSITION_CHECKS

REGISTRY_SCOPES: dict[str, InvariantScope] = {
    **{k: InvariantScope.COMPONENT for k in COMPONENT_CHECKS},
    **{k: InvariantScope.CALENDAR for k in CALENDAR_CHECKS},
    **{k: InvariantScope.TRANSITION for k in TRANSITION_CHECKS},
}


def run_state_check(
    inv: SpecInvariant, components: list[Component], ctx: CheckContext
) -> list[str]:
    """Apply one COMPONENT or CALENDAR invariant to a calendar state."""
    if inv.scope == InvariantScope.COMPONENT:
        check = COMPONENT_CHECKS[inv.check]
        return [e for comp in items(components) for e in check(comp, ctx)]
    if inv.scope == InvariantScope.CALENDAR:
        return CALENDAR_CHECKS[inv.check](components, ctx)
    return []


def run_transition_check(inv: SpecInvariant, transition: Transition) -> list[str]:
    """Apply one TRANSITION invariant to a transition."""
    if inv.scope != InvariantScope.TRANSITION:
        return []
    return TRANSITION_CHECKS[inv.check](transition)


def check_state(
    invariants: Iterable[SpecInvariant],
    components: list[Component],
    ctx: CheckContext | None = None,
    *,
    vector: bool = False,
) -> list[str]:
    """Apply every state invariant; `vector=True` honours `applies_to_scenario_vectors`."""
    eff_ctx = ctx or CheckContext()
    return [
        f"[{inv.id}] {err}"
        for inv in invariants
        if not vector or inv.applies_to_scenario_vectors
        for err in run_state_check(inv, components, eff_ctx)
    ]


def check_transition(
    invariants: Iterable[SpecInvariant], transition: Transition
) -> list[str]:
    """Apply every TRANSITION invariant to one transition."""
    return [
        f"[{inv.id}] {err}"
        for inv in invariants
        for err in run_transition_check(inv, transition)
    ]


def run_example(inv: SpecInvariant, example: InvariantExample) -> list[str]:
    """Evaluate one positive/negative example of an invariant; returns its violations."""
    if inv.scope == InvariantScope.TRANSITION:
        transition = Transition(
            before=example.before or [],
            operation=example.operation or {},
            after=example.after or [],
            failed=example.failed,
            permuted_afters=list(example.permuted_afters),
        )
        return run_transition_check(inv, transition)
    ctx = CheckContext(legacy_input=example.legacy_input)
    return run_state_check(inv, example.components or [], ctx)
