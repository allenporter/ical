"""Automated Readability & Modularity Rubric unit tests for ical and tests/spec/."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_DIR = REPO_ROOT / "tests" / "spec"

ICAL_MODIFIED_FILES = [
    REPO_ROOT / "ical" / "store.py",
    REPO_ROOT / "ical" / "recur_adapter.py",
    REPO_ROOT / "ical" / "component.py",
    REPO_ROOT / "ical" / "types" / "recur.py",
]

MAX_SPEC_FILE_LINES = 500
MAX_PROD_FUNC_LINES = 80
MAX_TEST_FUNC_LINES = 100
MAX_ELIF_BRANCHES = 8

REQUIRED_SPEC_MODULES = {
    "schema.py",
    "oracle_temporal.py",
    "oracle_base.py",
    "oracle_edit.py",
    "test_modes.py",
    "test_verify_scenarios.py",
    "reference_oracle.py",
    "scenario_runner.py",
    "ical_bridge.py",
    "test_reference_oracle.py",
    "test_oracle_redteam.py",
    "test_ical_compliance.py",
    "test_ical_adversarial.py",
    "test_readability.py",
}

CLEANROOM_MODULES = {
    "schema.py",
    "oracle_temporal.py",
    "oracle_base.py",
    "oracle_edit.py",
    "test_modes.py",
    "test_verify_scenarios.py",
    "reference_oracle.py",
    "scenario_runner.py",
    "test_reference_oracle.py",
    "test_oracle_redteam.py",
}


def count_elif_branches(node: ast.If) -> int:
    """Count the number of branches in an if/elif chain."""
    count = 1
    curr = node
    while len(curr.orelse) == 1 and isinstance(curr.orelse[0], ast.If):
        count += 1
        curr = curr.orelse[0]
    return count


def check_file(
    py_file: Path, *, check_file_length: bool, is_test_file: bool, check_cleanroom: bool
) -> list[str]:
    """Check a single Python file against the Readability & Modularity Rubric."""
    errors: list[str] = []
    rel = py_file.relative_to(REPO_ROOT)
    text = py_file.read_text(encoding="utf-8")
    lines = text.splitlines()

    if check_file_length and len(lines) > MAX_SPEC_FILE_LINES:
        errors.append(
            f"{rel}: {len(lines)} lines exceeds max {MAX_SPEC_FILE_LINES} lines"
        )

    tree = ast.parse(text, filename=str(py_file))

    if check_cleanroom:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ical" or alias.name.startswith("ical."):
                        errors.append(
                            f"{rel}:{node.lineno} clean-room violation: imports '{alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "ical" or node.module.startswith("ical."):
                    errors.append(
                        f"{rel}:{node.lineno} clean-room violation: imports from '{node.module}'"
                    )

    nested_ifs: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and len(node.orelse) == 1
            and isinstance(node.orelse[0], ast.If)
        ):
            nested_ifs.add(id(node.orelse[0]))

    max_func_lines = MAX_TEST_FUNC_LINES if is_test_file else MAX_PROD_FUNC_LINES
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if func_lines > max_func_lines:
                errors.append(
                    f"{rel}:{node.lineno} function '{node.name}' is {func_lines} lines (max {max_func_lines})"
                )
        if isinstance(node, ast.If) and id(node) not in nested_ifs:
            branches = count_elif_branches(node)
            if branches > MAX_ELIF_BRANCHES:
                errors.append(
                    f"{rel}:{node.lineno} if/elif chain has {branches} branches (max {MAX_ELIF_BRANCHES})"
                )

    return errors


@pytest.mark.parametrize(
    "py_file",
    ICAL_MODIFIED_FILES,
    ids=[str(p.relative_to(REPO_ROOT)) for p in ICAL_MODIFIED_FILES],
)
def test_modified_ical_files_readability(py_file: Path) -> None:
    """Ensure modified ical/ files obey function length and branching limits."""
    errors = check_file(
        py_file,
        check_file_length=False,
        is_test_file=False,
        check_cleanroom=False,
    )
    assert not errors, f"Readability rubric violations in {py_file}: {errors}"


def test_spec_modules_readability_and_modularity() -> None:
    """Ensure all tests/spec/ modules obey file length, function length, branching, and clean-room limits."""
    spec_files = sorted(SPEC_DIR.glob("*.py"))
    found_names = {p.name for p in spec_files}
    missing = REQUIRED_SPEC_MODULES - found_names
    assert not missing, (
        f"Missing required separated modules in tests/spec/: {sorted(missing)}"
    )

    all_errors: list[str] = []
    for py_file in spec_files:
        is_test = py_file.name.startswith("test_")
        is_cleanroom = py_file.name in CLEANROOM_MODULES
        all_errors.extend(
            check_file(
                py_file,
                check_file_length=True,
                is_test_file=is_test,
                check_cleanroom=is_cleanroom,
            )
        )
    assert not all_errors, f"Readability rubric violations in tests/spec/: {all_errors}"
