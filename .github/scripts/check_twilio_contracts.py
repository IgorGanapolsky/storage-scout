#!/usr/bin/env python3
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_RUNTIME_ERROR = 2

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "autonomy" / "tools"
TESTS_DIR = REPO_ROOT / "autonomy" / "tests"

REQUIRED_OUTCOMES = ("spoke", "voicemail", "no_answer", "failed")
REQUIRED_TWILIO_TOOL_FILES = (
    "twilio_autocall.py",
    "twilio_inbox_sync.py",
    "twilio_interest_nudge.py",
    "twilio_sms.py",
    "twilio_tollfree_watchdog.py",
)
REQUIRED_TWILIO_TEST_FILES = (
    "test_twilio_autocall.py",
    "test_twilio_inbox_sync.py",
    "test_twilio_interest_nudge.py",
    "test_twilio_sms.py",
    "test_twilio_tollfree_watchdog.py",
)


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _extract_asserted_outcomes(path: Path) -> tuple[set[str], int]:
    tree = ast.parse(_read_text(path), filename=str(path))
    outcomes: set[str] = set()
    assert_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        assert_count += 1
        for child in ast.walk(node.test):
            if not isinstance(child, ast.Compare):
                continue
            operands = [child.left, *child.comparators]
            has_dynamic_operand = any(
                not (isinstance(op, ast.Constant) and isinstance(op.value, str))
                for op in operands
            )
            if not has_dynamic_operand:
                continue
            for op in operands:
                if isinstance(op, ast.Constant) and isinstance(op.value, str):
                    if op.value in REQUIRED_OUTCOMES:
                        outcomes.add(op.value)
    return outcomes, assert_count


def _has_log_action_calls(path: Path) -> bool:
    tree = ast.parse(_read_text(path), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _dotted_name(node.func)
        if callee == "log_action" or callee.endswith(".log_action"):
            return True
    return False


def main() -> int:
    violations: list[Violation] = []

    for filename in REQUIRED_TWILIO_TOOL_FILES:
        path = TOOLS_DIR / filename
        if not path.exists():
            violations.append(
                Violation(
                    code="GOV101",
                    path=path.relative_to(REPO_ROOT).as_posix(),
                    message="Required Twilio wrapper file is missing.",
                )
            )
            continue
        if not _has_log_action_calls(path):
            violations.append(
                Violation(
                    code="GOV102",
                    path=path.relative_to(REPO_ROOT).as_posix(),
                    message="Twilio wrapper is missing audit logging via log_action(...).",
                )
            )

    asserted_outcomes: set[str] = set()
    total_assert_count = 0
    has_log_action_test_call = False
    for filename in REQUIRED_TWILIO_TEST_FILES:
        path = TESTS_DIR / filename
        if not path.exists():
            violations.append(
                Violation(
                    code="GOV201",
                    path=path.relative_to(REPO_ROOT).as_posix(),
                    message="Required Twilio test file is missing.",
                )
            )
            continue
        outcomes, assert_count = _extract_asserted_outcomes(path)
        asserted_outcomes.update(outcomes)
        total_assert_count += assert_count
        has_log_action_test_call = has_log_action_test_call or _has_log_action_calls(path)

    if total_assert_count == 0:
        violations.append(
            Violation(
                code="GOV204",
                path="autonomy/tests/test_twilio_*.py",
                message="No assert statements found in required Twilio tests.",
            )
        )

    for outcome in REQUIRED_OUTCOMES:
        if outcome not in asserted_outcomes:
            violations.append(
                Violation(
                    code="GOV202",
                    path="autonomy/tests/test_twilio_*.py",
                    message=(
                        f"Canonical outcome `{outcome}` is not covered in Twilio test assertions."
                    ),
                )
            )

    if not has_log_action_test_call:
        violations.append(
            Violation(
                code="GOV203",
                path="autonomy/tests/test_twilio_*.py",
                message="No Twilio tests call `log_action(...)` for audit-path coverage.",
            )
        )

    if not violations:
        print("Twilio governance contracts PASSED: 0 violations.")
        print(
            f"Checked {len(REQUIRED_TWILIO_TOOL_FILES)} wrappers and "
            f"{len(REQUIRED_TWILIO_TEST_FILES)} test files."
        )
        return EXIT_OK

    print(f"Twilio governance contracts FAILED: {len(violations)} violation(s).")
    for violation in violations:
        print(f"  - [{violation.code}] {violation.path}: {violation.message}")
    return EXIT_VIOLATIONS


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Twilio governance contracts runtime error: {type(exc).__name__}: {exc}")
        raise SystemExit(EXIT_RUNTIME_ERROR)
