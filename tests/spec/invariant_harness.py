"""Harness applying the `I-*` invariants to scenario vectors and live oracle states.

* `check_scenario_vectors` applies COMPONENT/CALENDAR invariants to a scenario's
  `initial_components` and `expected_components`, and TRANSITION invariants to
  (initial -> expected) for simple operations.
* `CheckedStore` is a `ReferenceStore` that checks every state invariant after each
  operation and every TRANSITION invariant for each operation, including atomicity on
  failure and order-independence (by replaying the operation on permuted input).
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from typing import Any

from .invariant_common import CheckContext, Component, Transition, is_legacy_segment
from .invariant_registry import check_state, check_transition
from .invariant_schema import SpecInvariant, load_invariants
from .oracle_canonical import DEFAULT_DTSTAMP
from .oracle_policy import PolicyConfig, StoreError
from .reference_oracle import ReferenceStore

ALL_INVARIANTS: list[SpecInvariant] = load_invariants()
_SIMPLE_OPS = {"add": "add", "add_todo": "add", "edit": "edit", "delete": "delete"}


def _permutations(components: list[Component]) -> list[list[Component]]:
    """Return deterministic non-identity permutations of a component list."""
    if len(components) < 2:
        return []
    perms = [list(reversed(components))]
    if len(components) > 2:
        perms.append(components[1:] + components[:1])
    return perms


def _new_legacy_segments(before: list[Component], after: list[Component]) -> list[str]:
    return [
        f"[I-C-006] write produced legacy shared-UID segment uid={c.get('uid')!r}"
        for c in after
        if is_legacy_segment(c) and c not in before
    ]


class CheckedStore(ReferenceStore):
    """ReferenceStore that asserts all invariants around every operation."""

    def __init__(
        self,
        initial_components: list[dict[str, Any]] | None = None,
        policy: PolicyConfig | None = None,
        *,
        legacy_input: bool = False,
        strict: bool = True,
    ) -> None:
        super().__init__(initial_components, policy)
        self.legacy_input = legacy_input
        self.strict = strict
        self.violations: list[str] = []
        self._report(check_state(ALL_INVARIANTS, self.components, self._ctx()))

    def _ctx(self) -> CheckContext:
        return CheckContext(legacy_input=self.legacy_input)

    def _report(self, errors: list[str]) -> None:
        self.violations.extend(errors)
        if errors and self.strict:
            raise AssertionError(f"Invariant violations: {errors}")

    def _replay(
        self, components: list[Component], call: Callable[[ReferenceStore], Any]
    ) -> list[Component] | None:
        try:
            other = ReferenceStore(copy.deepcopy(components), policy=self.policy)
            call(other)
        except StoreError:
            return None
        return other.components

    def _checked(
        self, operation: dict[str, Any], call: Callable[[ReferenceStore], Any]
    ) -> Any:
        before = copy.deepcopy(self.components)
        failure: StoreError | None = None
        result: Any = None
        try:
            result = call(self)
        except StoreError as exc:
            failure = exc
        after = copy.deepcopy(self.components)
        transition = Transition(
            before=before,
            operation=operation,
            after=after,
            failed=failure is not None,
            permuted_afters=[self._replay(p, call) for p in _permutations(before)],
        )
        self._report(
            [
                *check_state(ALL_INVARIANTS, after, self._ctx()),
                *_new_legacy_segments(before, after),
                *check_transition(ALL_INVARIANTS, transition),
            ]
        )
        if failure is not None:
            raise failure
        return result

    def add(
        self,
        item: dict[str, Any],
        default_type: str | None = None,
        now: str = DEFAULT_DTSTAMP,
    ) -> dict[str, Any]:
        """Add a component, checking invariants."""
        return self._checked(
            {"op": "add", "item": item},
            lambda s: ReferenceStore.add(s, item, default_type=default_type, now=now),
        )

    def edit(self, uid: str, patch: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        """Edit a component, checking invariants."""
        op = _op_dict("edit", uid, *args, patch=patch, **kwargs)
        self._checked(op, lambda s: ReferenceStore.edit(s, uid, patch, *args, **kwargs))

    def delete(self, uid: str, *args: Any, **kwargs: Any) -> None:
        """Delete a component or occurrences, checking invariants."""
        op = _op_dict("delete", uid, *args, **kwargs)
        self._checked(op, lambda s: ReferenceStore.delete(s, uid, *args, **kwargs))


def _op_dict(kind: str, uid: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Build the canonical declarative operation dict from call arguments."""
    names = ["recurrence_id", "range", "now", "new_uid"]
    op: dict[str, Any] = {"op": kind, "uid": uid, **dict(zip(names, args))}
    for key, val in kwargs.items():
        op["range" if key == "recurrence_range" else key] = val
    return op


def check_scenario_vectors(scenario: dict[str, Any]) -> list[str]:
    """Apply state invariants to a scenario's vectors and transitions to initial->expected."""
    op = scenario.get("operation") or {}
    legacy = bool(scenario.get("legacy_input"))
    initial = scenario.get("initial_components") or []
    expected = scenario.get("expected_components")
    errors = [
        f"initial: {e}"
        for e in check_state(
            ALL_INVARIANTS, initial, CheckContext(legacy_input=legacy), vector=True
        )
    ]
    if expected is not None:
        errors.extend(
            f"expected: {e}"
            for e in check_state(
                ALL_INVARIANTS,
                expected,
                CheckContext(legacy_input=False),
                vector=True,
            )
        )
    if (
        expected is not None
        and op.get("op") in _SIMPLE_OPS
        and not op.get("expect_error")
    ):
        transition = Transition(
            before=initial,
            operation={**op, "op": _SIMPLE_OPS[op["op"]]},
            after=expected,
        )
        errors.extend(
            f"transition: {e}" for e in check_transition(ALL_INVARIANTS, transition)
        )
    return errors
