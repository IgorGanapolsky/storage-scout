#!/usr/bin/env python3
from __future__ import annotations

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
        text = _read_text(path)
        if "log_action(" not in text:
            violations.append(
                Violation(
                    code="GOV102",
                    path=path.relative_to(REPO_ROOT).as_posix(),
                    message="Twilio wrapper is missing audit logging via log_action(...).",
                )
            )

    twilio_test_text_parts: list[str] = []
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
        twilio_test_text_parts.append(_read_text(path))

    combined_test_text = "\n".join(twilio_test_text_parts)
    for outcome in REQUIRED_OUTCOMES:
        if outcome not in combined_test_text:
            violations.append(
                Violation(
                    code="GOV202",
                    path="autonomy/tests/test_twilio_*.py",
                    message=f"Canonical outcome `{outcome}` is not covered in Twilio tests.",
                )
            )

    if "log_action(" not in combined_test_text:
        violations.append(
            Violation(
                code="GOV203",
                path="autonomy/tests/test_twilio_*.py",
                message="No Twilio tests reference audit logging behavior (`log_action(...)`).",
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
