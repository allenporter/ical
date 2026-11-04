"""Pydantic schema, loader and verifier for first-class specification invariants.

An invariant (`invariants/I-*.json`) is a property that MUST hold for every calendar
state or every operation, as opposed to a rule's example scenarios which only pin
individual outputs. Each invariant names an executable clean-room predicate (`check`)
and carries positive examples (MUST pass) and negative examples (MUST fail) so that no
predicate can be vacuous. Citations are verified byte-for-byte exactly like rules.

Id scheme: `I-C-###` component scope, `I-K-###` calendar scope, `I-T-###` transition
scope.
"""

from __future__ import annotations

from enum import StrEnum
import pathlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .operation_schema import validate_operation_dict
from .schema import (
    FORBIDDEN_IMPLEMENTATION_TERMS,
    SPEC_DIR,
    AuthorityLevel,
    RfcCitation,
    verify_citation,
)

INVARIANTS_DIR = SPEC_DIR / "invariants"

_ID_PREFIX = {"COMPONENT": "I-C-", "CALENDAR": "I-K-", "TRANSITION": "I-T-"}


class InvariantScope(StrEnum):
    """What an invariant's predicate is evaluated over."""

    COMPONENT = "COMPONENT"  # every VEVENT/VTODO in a state
    CALENDAR = "CALENDAR"  # a whole calendar state
    TRANSITION = "TRANSITION"  # (before, operation, after) of one operation


class InvariantExample(BaseModel):
    """A minimal input that MUST pass (positive) or MUST fail (negative) the check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    # COMPONENT / CALENDAR scope: the calendar state.
    components: list[dict[str, Any]] | None = None
    # State flagged as legacy shared-UID input (see R-L3-009).
    legacy_input: bool = False
    # TRANSITION scope.
    before: list[dict[str, Any]] | None = None
    operation: dict[str, Any] | None = None
    after: list[dict[str, Any]] | None = None
    failed: bool = False
    permuted_afters: list[list[dict[str, Any]] | None] = Field(default_factory=list)

    @field_validator("operation")
    @classmethod
    def _check_operation_schema(
        cls, val: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        return validate_operation_dict(val) if val is not None else None


class SpecInvariant(BaseModel):
    """A clean-room, machine-checkable invariant over calendar states or operations."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    scope: InvariantScope
    authority: AuthorityLevel
    citations: list[RfcCitation] = Field(default_factory=list)
    statement: str
    rationale: str
    check: str  # registry key of the executable predicate
    # False when scenario vectors elide the data the check needs (documented per
    # invariant); the check still applies to every complete store state.
    applies_to_scenario_vectors: bool = True
    positive_examples: list[InvariantExample]
    negative_examples: list[InvariantExample]
    audit_notes: list[str] = Field(default_factory=list)


def load_invariants(path: pathlib.Path = INVARIANTS_DIR) -> list[SpecInvariant]:
    """Load every invariant from `invariants/I-*.json`, sorted by id."""
    invariants: list[SpecInvariant] = []
    for child in sorted(path.glob("I-*.json")):
        inv = SpecInvariant.model_validate_json(child.read_text(encoding="utf-8"))
        if inv.id != child.stem:
            raise ValueError(f"Invariant file {child.name} declares id {inv.id!r}")
        invariants.append(inv)
    return invariants


def _verify_examples(inv: SpecInvariant) -> list[str]:
    errors: list[str] = []
    if not inv.positive_examples:
        errors.append(f"{inv.id}: needs at least one positive example")
    if not inv.negative_examples:
        errors.append(f"{inv.id}: needs at least one negative example")
    for ex in [*inv.positive_examples, *inv.negative_examples]:
        is_transition = ex.before is not None or ex.operation is not None
        if (inv.scope == InvariantScope.TRANSITION) != is_transition:
            errors.append(f"{inv.id}/{ex.name}: example shape does not match scope")
        if inv.scope == InvariantScope.TRANSITION and ex.after is None:
            errors.append(f"{inv.id}/{ex.name}: transition example needs 'after'")
        if inv.scope != InvariantScope.TRANSITION and ex.components is None:
            errors.append(f"{inv.id}/{ex.name}: state example needs 'components'")
    return errors


def verify_invariant(
    inv: SpecInvariant, registry: dict[str, InvariantScope]
) -> list[str]:
    """Verify id/scope consistency, citations, clean-room text, examples and registry."""
    errors: list[str] = []
    if not re.fullmatch(re.escape(_ID_PREFIX[inv.scope.value]) + r"\d{3}", inv.id):
        errors.append(
            f"{inv.id}: id must be {_ID_PREFIX[inv.scope.value]}### for {inv.scope}"
        )
    if inv.authority != AuthorityLevel.STORE_POLICY and not inv.citations:
        errors.append(f"{inv.id}: authority {inv.authority} requires citations")
    for cit in inv.citations:
        errors.extend(f"{inv.id}: {e}" for e in verify_citation(cit))
    for field, text in (("statement", inv.statement), ("rationale", inv.rationale)):
        if len(text.strip()) < 40:
            errors.append(f"{inv.id}: {field} is too brief (<40 chars)")
    serialized = inv.model_dump_json()
    errors.extend(
        f"{inv.id}: forbidden implementation term {term!r}"
        for term in FORBIDDEN_IMPLEMENTATION_TERMS
        if term in serialized
    )
    if registry.get(inv.check) != inv.scope:
        errors.append(f"{inv.id}: check {inv.check!r} is not a {inv.scope} predicate")
    errors.extend(_verify_examples(inv))
    return errors


def verify_invariants(
    invariants: list[SpecInvariant], registry: dict[str, InvariantScope]
) -> list[str]:
    """Verify all invariants plus registry bijection (every check used exactly once)."""
    errors: list[str] = []
    ids = [inv.id for inv in invariants]
    if len(ids) != len(set(ids)):
        errors.append(f"duplicate invariant ids: {ids}")
    for inv in invariants:
        errors.extend(verify_invariant(inv, registry))
    used = [inv.check for inv in invariants]
    if unused := sorted(set(registry) - set(used)):
        errors.append(f"registry predicates without an invariant: {unused}")
    if dupes := sorted({c for c in used if used.count(c) > 1}):
        errors.append(f"predicates referenced by several invariants: {dupes}")
    return errors
