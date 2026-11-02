"""Harness applying the `I-*` invariants to scenario vectors and live store states.

* `check_scenario_vectors` applies COMPONENT/CALENDAR invariants to a scenario's
  `initial_components` and `expected_components`, and TRANSITION invariants to
  (initial -> expected) for simple operations.
* `CheckedStore` wraps `ReferenceStore` (or any pluggable `StoreBackend` factory in
  Phase 2) and checks every state and transition invariant around each operation,
  including failure atomicity and input-permutation order independence.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from typing import Any, Protocol

from .invariant_common import (
    CheckContext,
    Component,
    Transition,
    is_legacy_segment,
    is_override,
)
from .invariant_registry import check_state, check_transition
from .invariant_schema import SpecInvariant, load_invariants
from .oracle_canonical import DEFAULT_DTSTAMP
from .oracle_policy import PolicyConfig, StoreError
from .reference_oracle import ReferenceStore

ALL_INVARIANTS: list[SpecInvariant] = load_invariants()
_SIMPLE_OPS = {"add": "add", "add_todo": "add", "edit": "edit", "delete": "delete"}


class StoreBackend(Protocol):
    """Minimal store protocol checked by `CheckedStore` (ReferenceStore or real store)."""

    components: list[dict[str, Any]]

    def add(self, item: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        """Add a component to the store."""

    def edit(self, uid: str, patch: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        """Edit a component or recurrence scope in the store."""

    def delete(self, uid: str, *args: Any, **kwargs: Any) -> Any:
        """Delete a component or recurrence scope from the store."""


def _swap_main_and_override(components: list[Component]) -> list[Component] | None:
    """Swap the first main component with one of its overrides when main precedes it."""
    for i, comp in enumerate(components):
        if comp.get("type") == "VTIMEZONE" or comp.get("recurrence_id") is not None:
            continue
        for j in range(i + 1, len(components)):
            if components[j].get("uid") == comp.get("uid") and is_override(
                components[j]
            ):
                swapped = list(components)
                swapped[i], swapped[j] = swapped[j], swapped[i]
                return swapped
    return None


def _permutations(components: list[Component]) -> list[list[Component]]:
    """Return deterministic non-identity permutations of a component list."""
    if len(components) < 2:
        return []
    candidates = [list(reversed(components))]
    if len(components) > 2:
        candidates.append(components[1:] + components[:1])
    if (swapped := _swap_main_and_override(components)) is not None:
        candidates.append(swapped)
    unique: list[list[Component]] = []
    for perm in candidates:
        if perm != components and perm not in unique:
            unique.append(perm)
    return unique


def _new_legacy_segments(before: list[Component], after: list[Component]) -> list[str]:
    return [
        f"[I-C-006] write produced legacy shared-UID segment uid={c.get('uid')!r}"
        for c in after
        if is_legacy_segment(c) and c not in before
    ]


class CheckedStore(ReferenceStore):
    """Store harness asserting all state and transition invariants on every write."""

    def __init__(
        self,
        initial_components: list[dict[str, Any]] | None = None,
        policy: PolicyConfig | None = None,
        *,
        legacy_input: bool = False,
        strict: bool = True,
        store_factory: Callable[[list[dict[str, Any]]], StoreBackend] | None = None,
        error_types: tuple[type[Exception], ...] = (StoreError,),
    ) -> None:
        self._store_factory = store_factory
        self._error_types = error_types
        self._backend: StoreBackend | None = None
        if store_factory is not None:
            super().__init__([], policy)
            self._backend = store_factory(copy.deepcopy(initial_components or []))
            self.components = self._backend.components
        else:
            super().__init__(initial_components, policy)
        self.legacy_input = legacy_input
        self.strict = strict
        self.violations: list[str] = []
        self._report(check_state(ALL_INVARIANTS, self._current_state(), self._ctx()))

    def _current_state(self) -> list[Component]:
        if self._backend is not None:
            self.components = self._backend.components
        return self.components

    def _ctx(self) -> CheckContext:
        return CheckContext(legacy_input=self.legacy_input)

    def _report(self, errors: list[str]) -> None:
        self.violations.extend(errors)
        if errors and self.strict:
            raise AssertionError(f"Invariant violations: {errors}")

    def _make_peer(self, components: list[Component]) -> StoreBackend:
        cloned = copy.deepcopy(components)
        if self._store_factory is not None:
            return self._store_factory(cloned)
        return ReferenceStore(cloned, policy=self.policy)

    def _replay(
        self, components: list[Component], call: Callable[[StoreBackend], Any]
    ) -> list[Component] | None:
        try:
            other = self._make_peer(components)
            call(other)
        except self._error_types:
            return None
        return other.components

    def _checked(
        self, operation: dict[str, Any], call: Callable[[StoreBackend], Any]
    ) -> Any:
        target: StoreBackend = self._backend if self._backend is not None else self
        before = copy.deepcopy(self._current_state())
        failure: Exception | None = None
        result: Any = None
        try:
            result = call(target)
        except self._error_types as exc:
            failure = exc
        after = copy.deepcopy(self._current_state())
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
            lambda s: (
                ReferenceStore.add(s, item, default_type=default_type, now=now)
                if isinstance(s, ReferenceStore)
                else s.add(item, default_type=default_type, now=now)
            ),
        )

    def edit(self, uid: str, patch: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        """Edit a component, checking invariants."""
        op = _op_dict("edit", uid, *args, patch=patch, **kwargs)
        self._checked(
            op,
            lambda s: (
                ReferenceStore.edit(s, uid, patch, *args, **kwargs)
                if isinstance(s, ReferenceStore)
                else s.edit(uid, patch, *args, **kwargs)
            ),
        )

    def delete(self, uid: str, *args: Any, **kwargs: Any) -> None:
        """Delete a component or occurrences, checking invariants."""
        op = _op_dict("delete", uid, *args, **kwargs)
        self._checked(
            op,
            lambda s: (
                ReferenceStore.delete(s, uid, *args, **kwargs)
                if isinstance(s, ReferenceStore)
                else s.delete(uid, *args, **kwargs)
            ),
        )


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
                CheckContext(legacy_input=legacy),
                vector=True,
            )
        )
        errors.extend(f"expected: {e}" for e in _new_legacy_segments(initial, expected))
    if (
        expected is not None
        and op.get("op") in _SIMPLE_OPS
        and not op.get("expect_error")
    ):
        transition = Transition(
            before=initial,
            operation={**op, "op": _SIMPLE_OPS[op["op"]]},
            after=expected,
            partial_after=True,
        )
        errors.extend(
            f"transition: {e}" for e in check_transition(ALL_INVARIANTS, transition)
        )
    return errors
