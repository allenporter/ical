"""Core Pydantic schema and automated clean-room + citation verifier for RFC recurrence rules.

Every rule is stored in its own standalone JSON file (`rules/<layer>/<rule_id>.json`) and MUST pass
`verify_rule(rule)` which enforces:
1. CLEAN-ROOM INDEPENDENCE: No rule may reference `ical`'s internal implementation files, classes,
   or private functions (`store.py`, `_apply_edit`, `_prepare_update`, `EventStore`, etc.).
   Rules must be 100% implementation-independent specifications of abstract calendar semantics.
2. BYTE-FOR-BYTE CITATION GROUNDING: All RFC/draft citations point to a real document in `rfcs/`
   (`*.txt.gz`), and `verbatim_quote` exists within the cited `line_start..line_end` window of
   that document.
3. HONEST AUTHORITY TAGGING: `RFC_5545`, `RFC_5546`, `RFC_8984_CALEXT`, or `STORE_POLICY`.
4. DUAL-OUTPUT SCENARIO VECTORS: Every rule includes at least one `MiniScenarioVector` with
   `initial_components`, `operation`, `expected_components`, and `expected_timeline`.
5. EXPLICIT POLICY MODE SCOPING: Where the RFCs are silent or conflict, the reasonable
   alternatives are recorded as `PolicyMode` files (`modes/<mode_id>.json`). A rule whose
   normative text depends on one of those choices declares it in `applies_under`, and a
   scenario whose expected output depends on a choice pins it in `modes`. Rules and scenarios
   with no declaration are mode-independent and MUST hold under every option.
"""

# pylint: disable=line-too-long

from __future__ import annotations

from enum import StrEnum
import functools
import gzip
import json
import pathlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SPEC_DIR = pathlib.Path(__file__).resolve().parent
RULES_DIR = SPEC_DIR / "rules"
MODES_DIR = SPEC_DIR / "modes"
RFC_DIR = SPEC_DIR / "rfcs"

AVAILABLE_DOCS = {
    "rfc5545.txt": RFC_DIR / "rfc5545.txt.gz",
    "rfc5546.txt": RFC_DIR / "rfc5546.txt.gz",
    "rfc8984.txt": RFC_DIR / "rfc8984.txt.gz",
    "draft-ietf-calext-jscalendar-icalendar.txt": RFC_DIR
    / "draft-ietf-calext-jscalendar-icalendar.txt.gz",
}

FORBIDDEN_IMPLEMENTATION_TERMS = [
    "store.py",
    "test_store.py",
    "iter.py",
    "component.py",
    "recur_adapter.py",
    "_apply_edit",
    "_apply_delete",
    "_prepare_update",
    "_match_item",
    "_match_items",
    "_prune_invalid_exdates",
    "_ensure_timezone",
    "RulesetIterable",
    "FilteredRecurrenceIterable",
    "GenericStore",
    "EventStore",
    "TodoStore",
    "copy_and_validate",
]


class AuthorityLevel(StrEnum):
    """Authority level of a specification rule."""

    RFC_5545 = "RFC_5545"  # Hard requirement in RFC 5545
    RFC_5546 = "RFC_5546"  # Hard requirement in RFC 5546 (iTIP)
    RFC_8984_CALEXT = (
        "RFC_8984_CALEXT"  # Formal model in RFC 8984 / jscalendar-icalendar
    )
    STORE_POLICY = (
        "STORE_POLICY"  # Abstract store design contract (where RFCs are silent)
    )


class RuleLayer(StrEnum):
    """Logical layer in the recurrence editing state machine."""

    L1_RECURRENCE_SET_AND_BOUNDS = "L1_RECURRENCE_SET_AND_BOUNDS"
    L2_SINGLE_INSTANCE_EDIT_DELETE = "L2_SINGLE_INSTANCE_EDIT_DELETE"
    L3_THIS_AND_FUTURE_SPLIT = "L3_THIS_AND_FUTURE_SPLIT"
    L4_MASTER_EDIT_AND_EXCEPTIONS = "L4_MASTER_EDIT_AND_EXCEPTIONS"
    L5_METADATA_TIMEZONE_RELATIONS = "L5_METADATA_TIMEZONE_RELATIONS"


class AuditStatus(StrEnum):
    """Lifecycle status of a rule in the hill-climbing pipeline."""

    PROPOSED = "PROPOSED"
    CITATION_VERIFIED = "CITATION_VERIFIED"
    ADVERSARIALLY_VETTED = "ADVERSARIALLY_VETTED"
    NEEDS_REVISION = "NEEDS_REVISION"


class RfcCitation(BaseModel):
    """Exact citation to a local RFC or IETF draft text file."""

    model_config = ConfigDict(extra="forbid")

    doc: str  # Key in AVAILABLE_DOCS
    section: str  # e.g., "Section 3.8.4.4"
    line_start: int = Field(ge=1)  # 1-based inclusive start line in doc
    line_end: int = Field(ge=1)  # 1-based inclusive end line in doc
    verbatim_quote: str  # Exact substring from that line window


class MiniScenarioVector(BaseModel):
    """A self-contained, declarative micro-scenario illustrating the rule."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    # Policy mode choices this scenario's expected output depends on ({mode_id: option_id}).
    # Empty means the expected output is identical under every option of every mode.
    modes: dict[str, str] = Field(default_factory=dict)
    initial_components: list[dict[str, Any]]
    operation: dict[str, Any]
    expected_components: list[dict[str, Any]]
    expected_timeline: list[dict[str, Any]]


class ModeOption(BaseModel):
    """One reasonable alternative for a decision the RFCs leave open."""

    model_config = ConfigDict(extra="forbid")

    id: str  # e.g., "NEW_UID"
    summary: str
    consequences: list[str] = Field(default_factory=list)
    # RFC text supporting this option, if any.
    citations: list[RfcCitation] = Field(default_factory=list)


class PolicyMode(BaseModel):
    """A first-order store design decision where the RFCs are silent or in conflict.

    Modes are recorded (not decided) so that rules can be scoped to the option(s) they assume
    and the choice can be made later with the consequences of each option visible.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # snake_case; matches the corresponding `PolicyConfig` field in the oracle
    title: str
    question: str
    spec_gap: str  # Why the RFCs do not settle this question
    # Evidence of the gap (or of a conflicting recommendation).
    citations: list[RfcCitation]
    options: list[ModeOption] = Field(min_length=2)
    open_questions: list[str] = Field(default_factory=list)


class SpecRule(BaseModel):
    """A clean-room, machine-verifiable specification rule for recurrence editing."""

    model_config = ConfigDict(extra="forbid")

    id: str  # e.g., "R-L1-001"
    title: str
    layer: RuleLayer
    authority: AuthorityLevel
    # Policy mode options under which this rule's normative text holds ({mode_id: [option_id]}).
    # Modes not listed are irrelevant to the rule (it holds under every option).
    applies_under: dict[str, list[str]] = Field(default_factory=dict)
    citations: list[RfcCitation]
    rationale: (
        str  # Step-by-step derivation from citation(s) to rule (no implementation refs)
    )
    store_implication: (
        str  # Abstract requirement on calendar component & timeline state
    )
    edge_cases_and_counterexamples: list[str] = Field(default_factory=list)
    scenarios: list[MiniScenarioVector] = Field(default_factory=list)
    audit_status: AuditStatus = AuditStatus.PROPOSED
    audit_notes: list[str] = Field(default_factory=list)


_RULE_LIST_ADAPTER = TypeAdapter(list[SpecRule])


def _normalize_rfc_text(text: str) -> str:
    """Strip RFC page headers/footers and collapse whitespace for quote verification."""
    cleaned_lines: list[str] = []
    skip_post_ff = False
    for line in text.splitlines():
        if "\x0c" in line:
            skip_post_ff = True
            continue
        if skip_post_ff:
            if line.strip() == "":
                continue
            skip_post_ff = False
            continue
        if re.search(r"\[Page \d+\]\s*$", line):
            continue
        cleaned_lines.append(line)
    return re.sub(r"\s+", " ", " ".join(cleaned_lines)).strip()


@functools.lru_cache(maxsize=8)
def _load_rfc_lines(doc: str) -> list[str]:
    """Decompress and cache the lines of an RFC document from tests/spec/rfcs/*.txt.gz."""
    path = AVAILABLE_DOCS[doc]
    text = gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")
    return text.splitlines()


def verify_citation(citation: RfcCitation) -> list[str]:
    """Verify a single RfcCitation byte-for-byte against the full RFC in tests/spec/rfcs/."""
    if citation.doc not in AVAILABLE_DOCS:
        return [
            f"Unknown doc '{citation.doc}'. Must be one of {list(AVAILABLE_DOCS.keys())}"
        ]
    path = AVAILABLE_DOCS[citation.doc]
    if not path.exists():
        return [f"Doc file missing on disk: {path}"]

    all_lines = _load_rfc_lines(citation.doc)
    total_lines = len(all_lines)
    if citation.line_end > total_lines:
        return [
            f"{citation.doc}: line range {citation.line_start}..{citation.line_end} "
            f"out of bounds (1..{total_lines})"
        ]
    if citation.line_start > citation.line_end:
        return [
            f"{citation.doc}: line_start ({citation.line_start}) > line_end ({citation.line_end})"
        ]

    errors: list[str] = []
    if len(citation.verbatim_quote.strip()) < 20:
        errors.append(
            f"{citation.doc} ({citation.section}): verbatim_quote is too short (<20 chars)"
        )

    window_text = "\n".join(all_lines[citation.line_start - 1 : citation.line_end])
    norm_window = _normalize_rfc_text(window_text)
    norm_quote = _normalize_rfc_text(citation.verbatim_quote)
    if norm_quote not in norm_window:
        errors.append(
            f"{citation.doc} ({citation.section}, L{citation.line_start}-L{citation.line_end}): "
            f"verbatim_quote not found in specified line window.\n"
            f"  Quote (normalized): {norm_quote!r}\n"
            f"  Window (normalized): {norm_window[:300]!r}..."
        )
    return errors


def verify_clean_room(rule: SpecRule) -> list[str]:
    """Ensure the rule contains zero references to ical implementation files or symbols."""
    serialized = rule.model_dump_json()
    return [
        f"Clean-room violation: rule contains forbidden implementation term {term!r}. "
        "Spec rules must be 100% implementation-independent."
        for term in FORBIDDEN_IMPLEMENTATION_TERMS
        if term in serialized
    ]


def verify_rule(
    rule: SpecRule, modes: dict[str, PolicyMode] | None = None
) -> list[str]:
    """Verify all clean-room, structural, citation, and mode-scoping requirements on a SpecRule."""
    errors: list[str] = []
    if rule.authority != AuthorityLevel.STORE_POLICY and not rule.citations:
        errors.append(
            f"Rule {rule.id} has authority {rule.authority} but no RFC citations."
        )
    for cit in rule.citations:
        errors.extend(verify_citation(cit))
    if len(rule.rationale.strip()) < 40:
        errors.append(f"Rule {rule.id}: rationale is too brief (<40 chars).")
    if len(rule.store_implication.strip()) < 40:
        errors.append(f"Rule {rule.id}: store_implication is too brief (<40 chars).")
    if not rule.scenarios:
        errors.append(f"Rule {rule.id}: must include at least 1 MiniScenarioVector.")
    errors.extend(verify_clean_room(rule))
    errors.extend(verify_mode_scoping(rule, load_modes() if modes is None else modes))
    return errors


def load_modes(modes_dir: pathlib.Path = MODES_DIR) -> dict[str, PolicyMode]:
    """Load every PolicyMode from `modes/<mode_id>.json`, keyed by mode id."""
    modes: dict[str, PolicyMode] = {}
    for child in sorted(modes_dir.glob("*.json")):
        mode = PolicyMode.model_validate_json(child.read_text(encoding="utf-8"))
        if mode.id != child.stem:
            raise ValueError(
                f"Mode file {child.name} declares mismatched id {mode.id!r}"
            )
        if mode.id in modes:
            raise ValueError(f"Duplicate mode id: {mode.id}")
        modes[mode.id] = mode
    return modes


def verify_mode(mode: PolicyMode) -> list[str]:
    """Verify a PolicyMode's structure and citations."""
    errors: list[str] = []
    if not re.fullmatch(r"[a-z][a-z0-9_]*", mode.id):
        errors.append(f"Mode {mode.id!r}: id must be snake_case")
    option_ids = [opt.id for opt in mode.options]
    if len(option_ids) != len(set(option_ids)):
        errors.append(f"Mode {mode.id}: duplicate option ids {option_ids}")
    for opt_id in option_ids:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", opt_id):
            errors.append(
                f"Mode {mode.id}: option id {opt_id!r} must be UPPER_SNAKE_CASE"
            )
    if len(mode.spec_gap.strip()) < 40:
        errors.append(f"Mode {mode.id}: spec_gap is too brief (<40 chars).")
    if not mode.citations:
        errors.append(f"Mode {mode.id}: must cite the RFC text that leaves the gap.")
    for cit in mode.citations:
        errors.extend(f"Mode {mode.id}: {e}" for e in verify_citation(cit))
    for opt in mode.options:
        for cit in opt.citations:
            errors.extend(f"Mode {mode.id}/{opt.id}: {e}" for e in verify_citation(cit))
    return errors


def verify_mode_scoping(rule: SpecRule, modes: dict[str, PolicyMode]) -> list[str]:
    """Verify `applies_under` and scenario `modes` reference real modes/options consistently."""
    errors: list[str] = []
    for mode_id, option_ids in rule.applies_under.items():
        if mode_id not in modes:
            errors.append(
                f"Rule {rule.id}: applies_under references unknown mode {mode_id!r}"
            )
            continue
        valid = {opt.id for opt in modes[mode_id].options}
        if not option_ids:
            errors.append(f"Rule {rule.id}: applies_under[{mode_id}] is empty")
        if unknown := sorted(set(option_ids) - valid):
            errors.append(
                f"Rule {rule.id}: applies_under[{mode_id}] has unknown options {unknown}"
            )
        if len(option_ids) != len(set(option_ids)):
            errors.append(f"Rule {rule.id}: applies_under[{mode_id}] has duplicates")
        if set(option_ids) == valid:
            errors.append(
                f"Rule {rule.id}: applies_under[{mode_id}] lists every option; "
                "omit the mode instead (the rule is mode-independent)"
            )
    for scen in rule.scenarios:
        for mode_id, option_id in scen.modes.items():
            if mode_id not in modes:
                errors.append(
                    f"Rule {rule.id} scenario {scen.name!r}: unknown mode {mode_id!r}"
                )
                continue
            if option_id not in {opt.id for opt in modes[mode_id].options}:
                errors.append(
                    f"Rule {rule.id} scenario {scen.name!r}: unknown option "
                    f"{option_id!r} for mode {mode_id!r}"
                )
            elif (
                mode_id in rule.applies_under
                and option_id not in rule.applies_under[mode_id]
            ):
                errors.append(
                    f"Rule {rule.id} scenario {scen.name!r}: pins {mode_id}={option_id}, "
                    f"outside the rule's applies_under {rule.applies_under[mode_id]}"
                )
    return errors


def effective_scenario_modes(
    rule: SpecRule, scenario: MiniScenarioVector
) -> dict[str, list[str]]:
    """Return the mode options a scenario's expected output is valid under.

    Combines the rule's `applies_under` with the scenario's own pins. Modes that are absent
    from the result are irrelevant to the scenario.
    """
    effective = {mode_id: list(opts) for mode_id, opts in rule.applies_under.items()}
    for mode_id, option_id in scenario.modes.items():
        effective[mode_id] = [option_id]
    return effective


def mode_coverage(
    rules: list[SpecRule], modes: dict[str, PolicyMode]
) -> dict[str, dict[str, list[str]]]:
    """Map mode_id -> option_id -> ids of rules/scenarios that specify behavior for it.

    An option with an empty list has no rule describing its behavior yet; that is expected
    for options that have been recorded but not yet specified.
    """
    coverage = {
        mode_id: {opt.id: [] for opt in mode.options} for mode_id, mode in modes.items()
    }
    for rule in rules:
        for mode_id, option_ids in rule.applies_under.items():
            for option_id in option_ids:
                coverage.get(mode_id, {}).setdefault(option_id, []).append(rule.id)
        for scen in rule.scenarios:
            for mode_id, option_id in scen.modes.items():
                coverage.get(mode_id, {}).setdefault(option_id, []).append(
                    f"{rule.id}::{scen.name}"
                )
    return coverage


def save_rule_json(rule: SpecRule, path: pathlib.Path) -> None:
    """Serialize a single SpecRule object to its own JSON file.

    Empty `applies_under` and scenario `modes` are omitted so mode-independent
    rules stay terse.
    """
    data = rule.model_dump(mode="json")
    if not data["applies_under"]:
        del data["applies_under"]
    for scen in data["scenarios"]:
        if not scen["modes"]:
            del scen["modes"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_rules_from_path(path: pathlib.Path) -> list[SpecRule]:
    """Load SpecRule(s) from a single-rule JSON file, multi-rule JSON file, or directory."""
    if path.is_dir():
        rules: list[SpecRule] = []
        for child in sorted(path.rglob("*.json")):
            rules.extend(load_rules_from_path(child))
        return rules
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return _RULE_LIST_ADAPTER.validate_json(text)
    return [SpecRule.model_validate_json(text)]


def load_all_scenarios(
    rules_dir: pathlib.Path = RULES_DIR,
) -> list[tuple[str, int, str, dict[str, Any]]]:
    """Load all (rule_id, scenario_idx, scenario_name, scenario_dict) tuples via Pydantic."""
    scenarios: list[tuple[str, int, str, dict[str, Any]]] = []
    for rule in load_rules_from_path(rules_dir):
        for idx, scen in enumerate(rule.scenarios):
            scenarios.append((rule.id, idx, scen.name, scen.model_dump()))
    return scenarios


def verify_path(path: pathlib.Path) -> tuple[int, list[str]]:
    """Verify all rules in a file or directory. Returns (num_rules, list_of_errors)."""
    try:
        rules = load_rules_from_path(path)
        modes = load_modes()
    except Exception as exc:  # pylint: disable=broad-except
        return 0, [str(exc)]
    all_errors: list[str] = []
    for mode in modes.values():
        all_errors.extend(f"[mode {mode.id}] {e}" for e in verify_mode(mode))
    seen_ids: set[str] = set()
    for r in rules:
        if r.id in seen_ids:
            all_errors.append(f"Duplicate rule ID: {r.id}")
        seen_ids.add(r.id)
        all_errors.extend(f"[{r.id}] {e}" for e in verify_rule(r, modes))
    return len(rules), all_errors
