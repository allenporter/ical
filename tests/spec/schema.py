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
"""

# pylint: disable=line-too-long

from __future__ import annotations

from enum import StrEnum
import functools
import gzip
import pathlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SPEC_DIR = pathlib.Path(__file__).resolve().parent
RULES_DIR = SPEC_DIR / "rules"
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
    initial_components: list[dict[str, Any]]
    operation: dict[str, Any]
    expected_components: list[dict[str, Any]]
    expected_timeline: list[dict[str, Any]]


class SpecRule(BaseModel):
    """A clean-room, machine-verifiable specification rule for recurrence editing."""

    model_config = ConfigDict(extra="forbid")

    id: str  # e.g., "R-L1-001"
    title: str
    layer: RuleLayer
    authority: AuthorityLevel
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


def verify_rule(rule: SpecRule) -> list[str]:
    """Verify all clean-room, structural, and citation requirements on a SpecRule."""
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
    return errors


def save_rule_json(rule: SpecRule, path: pathlib.Path) -> None:
    """Serialize a single SpecRule object to its own JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rule.model_dump_json(indent=2) + "\n", encoding="utf-8")


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
    except Exception as exc:  # pylint: disable=broad-except
        return 0, [str(exc)]
    all_errors: list[str] = []
    seen_ids: set[str] = set()
    for r in rules:
        if r.id in seen_ids:
            all_errors.append(f"Duplicate rule ID: {r.id}")
        seen_ids.add(r.id)
        all_errors.extend(f"[{r.id}] {e}" for e in verify_rule(r))
    return len(rules), all_errors
