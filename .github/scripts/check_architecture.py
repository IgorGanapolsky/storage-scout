#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
import re

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_RUNTIME_ERROR = 2

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "autonomy" / "tools"

# Twilio integrations are intentionally centralized here.
APPROVED_TWILIO_WRAPPER_FILES = frozenset(
    {
        "twilio_autocall.py",
        "twilio_inbox_sync.py",
        "twilio_interest_nudge.py",
        "twilio_sms.py",
        "twilio_tollfree_watchdog.py",
    }
)

TWILIO_ENDPOINT_RE = re.compile(
    r"https://(?:api|messaging|lookups|verify|video|taskrouter|studio)\.twilio\.com",
    re.IGNORECASE,
)

FORBIDDEN_TWILIO_HTTP_CALLS = frozenset(
    {
        "urllib.request.Request",
        "urllib.request.urlopen",
        "http.client.HTTPConnection",
        "http.client.HTTPSConnection",
        "urllib3.PoolManager",
        "urllib3.request",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.patch",
        "requests.delete",
        "requests.request",
        "requests.Session",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.patch",
        "httpx.delete",
        "httpx.request",
        "httpx.Client",
        "httpx.AsyncClient",
        "aiohttp.ClientSession",
    }
)

TRANSPORT_FACTORY_CALLS = frozenset(
    {
        "urllib.request.build_opener",
        "requests.Session",
        "httpx.Client",
        "httpx.AsyncClient",
        "urllib3.PoolManager",
        "aiohttp.ClientSession",
    }
)

TRANSPORT_METHOD_NAMES = frozenset(
    {"open", "request", "send", "get", "post", "put", "patch", "delete"}
)


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    line: int
    message: str
    snippet: str


def _dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _attribute_root_name(node: ast.AST) -> str:
    cursor = node
    while isinstance(cursor, ast.Attribute):
        cursor = cursor.value
    if isinstance(cursor, ast.Name):
        return cursor.id
    return ""


def _safe_line(lines: list[str], lineno: int) -> str:
    if lineno < 1 or lineno > len(lines):
        return ""
    return lines[lineno - 1].strip()


def _find_twilio_endpoint_lines(lines: Iterable[str]) -> list[int]:
    hit_lines: list[int] = []
    for idx, line in enumerate(lines, start=1):
        if TWILIO_ENDPOINT_RE.search(line):
            hit_lines.append(idx)
    return hit_lines


def _resolve_alias_dotted_name(
    dotted_name: str, import_alias_map: Mapping[str, str]
) -> str:
    if not dotted_name:
        return dotted_name
    root, sep, rest = dotted_name.partition(".")
    if root not in import_alias_map:
        return dotted_name
    mapped_root = import_alias_map[root]
    return f"{mapped_root}.{rest}" if sep else mapped_root


def _is_forbidden_transport_call(
    node: ast.Call, import_alias_map: Mapping[str, str]
) -> str | None:
    callee = _dotted_name(node.func)
    if not callee:
        return None
    resolved = _resolve_alias_dotted_name(callee, import_alias_map)
    if resolved in FORBIDDEN_TWILIO_HTTP_CALLS:
        return resolved
    if resolved.startswith("urllib.request.") and resolved != "urllib.request.urlencode":
        return resolved
    return None


def _is_request_json_call(
    node: ast.Call, import_alias_map: Mapping[str, str]
) -> bool:
    callee = _dotted_name(node.func)
    if not callee:
        return False
    resolved = _resolve_alias_dotted_name(callee, import_alias_map)
    return resolved == "autonomy.tools.agent_commerce.request_json"


def _iter_assigned_names(target: ast.AST) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        for child in target.elts:
            yield from _iter_assigned_names(child)


def _collect_transport_client_vars(
    tree: ast.AST, import_alias_map: Mapping[str, str]
) -> set[str]:
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            factory = _resolve_alias_dotted_name(
                _dotted_name(node.value.func),
                import_alias_map,
            )
            if factory in TRANSPORT_FACTORY_CALLS:
                for target in node.targets:
                    names.update(_iter_assigned_names(target))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            factory = _resolve_alias_dotted_name(
                _dotted_name(node.value.func),
                import_alias_map,
            )
            if factory in TRANSPORT_FACTORY_CALLS:
                names.update(_iter_assigned_names(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if not isinstance(item.context_expr, ast.Call):
                    continue
                factory = _resolve_alias_dotted_name(
                    _dotted_name(item.context_expr.func),
                    import_alias_map,
                )
                if factory in TRANSPORT_FACTORY_CALLS and item.optional_vars is not None:
                    names.update(_iter_assigned_names(item.optional_vars))

    return names


def _analyze_file(py_file: Path) -> list[Violation]:
    source = py_file.read_text(encoding="utf-8")
    lines = source.splitlines()
    rel_path = py_file.relative_to(REPO_ROOT).as_posix()
    violations: list[Violation] = []

    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as exc:
        lineno = int(exc.lineno or 1)
        violations.append(
            Violation(
                code="ARCH900",
                path=rel_path,
                line=lineno,
                message="Unable to parse Python file; architecture checks cannot run on this file.",
                snippet=_safe_line(lines, lineno),
            )
        )
        return violations

    is_approved_wrapper = py_file.name in APPROVED_TWILIO_WRAPPER_FILES
    twilio_module_aliases: set[str] = set()
    twilio_imported_symbols: set[str] = set()
    import_line_nos: set[int] = set()
    import_alias_map: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.strip()
                alias_name = (alias.asname or mod).strip()
                if alias_name:
                    import_alias_map[alias_name] = mod
                if mod.startswith("twilio"):
                    import_line_nos.add(int(node.lineno))
                    alias_name = (alias.asname or mod.split(".", 1)[0]).strip()
                    if alias_name:
                        twilio_module_aliases.add(alias_name)
                    if not is_approved_wrapper:
                        violations.append(
                            Violation(
                                code="ARCH001",
                                path=rel_path,
                                line=int(node.lineno),
                                message=(
                                    "Direct Twilio SDK import is not allowed in this file. "
                                    "Use approved Twilio wrapper modules instead."
                                ),
                                snippet=_safe_line(lines, int(node.lineno)),
                            )
                        )
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").strip()
            if mod:
                for alias in node.names:
                    alias_name = (alias.asname or alias.name).strip()
                    if alias_name:
                        import_alias_map[alias_name] = f"{mod}.{alias.name}"
            if mod.startswith("twilio"):
                import_line_nos.add(int(node.lineno))
                for alias in node.names:
                    imported_name = (alias.asname or alias.name).strip()
                    if imported_name:
                        twilio_imported_symbols.add(imported_name)
                if not is_approved_wrapper:
                    violations.append(
                        Violation(
                            code="ARCH001",
                            path=rel_path,
                            line=int(node.lineno),
                            message=(
                                "Direct Twilio SDK import is not allowed in this file. "
                                "Use approved Twilio wrapper modules instead."
                            ),
                            snippet=_safe_line(lines, int(node.lineno)),
                        )
                    )

    if not is_approved_wrapper:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                root = _attribute_root_name(node)
                if root and (root == "twilio" or root in twilio_module_aliases):
                    violations.append(
                        Violation(
                            code="ARCH002",
                            path=rel_path,
                            line=int(node.lineno),
                            message="Direct Twilio SDK usage is not allowed in this file.",
                            snippet=_safe_line(lines, int(node.lineno)),
                        )
                    )
            elif isinstance(node, ast.Name):
                if int(node.lineno) in import_line_nos:
                    continue
                if node.id in twilio_imported_symbols:
                    violations.append(
                        Violation(
                            code="ARCH002",
                            path=rel_path,
                            line=int(node.lineno),
                            message="Direct Twilio SDK usage is not allowed in this file.",
                            snippet=_safe_line(lines, int(node.lineno)),
                        )
                    )

    twilio_endpoint_lines = _find_twilio_endpoint_lines(lines)
    if twilio_endpoint_lines and not is_approved_wrapper:
        for lineno in twilio_endpoint_lines:
            violations.append(
                Violation(
                    code="ARCH101",
                    path=rel_path,
                    line=lineno,
                    message=(
                        "Twilio REST endpoint found outside approved wrappers. "
                        "Route Twilio calls through approved wrapper modules."
                    ),
                    snippet=_safe_line(lines, lineno),
                )
            )

    if is_approved_wrapper:
        transport_client_vars = _collect_transport_client_vars(tree, import_alias_map)
        has_request_json_call = any(
            _is_request_json_call(node, import_alias_map)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        )
        if twilio_endpoint_lines and not has_request_json_call:
            violations.append(
                Violation(
                    code="ARCH201",
                    path=rel_path,
                    line=twilio_endpoint_lines[0],
                    message=(
                        "Twilio REST endpoint usage in wrapper without shared helper call. "
                        "Use autonomy.tools.agent_commerce.request_json."
                    ),
                    snippet=_safe_line(lines, twilio_endpoint_lines[0]),
                )
            )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            forbidden_call = _is_forbidden_transport_call(node, import_alias_map)
            if forbidden_call:
                violations.append(
                    Violation(
                        code="ARCH202",
                        path=rel_path,
                        line=int(node.lineno),
                        message=(
                            f"Direct HTTP transport call `{forbidden_call}` is not allowed for Twilio flows. "
                            "Use request_json helper."
                        ),
                        snippet=_safe_line(lines, int(node.lineno)),
                        )
                    )
                continue

            if isinstance(node.func, ast.Attribute):
                call_attr = node.func.attr
                if call_attr in TRANSPORT_METHOD_NAMES:
                    root = _attribute_root_name(node.func)
                    if root in transport_client_vars:
                        violations.append(
                            Violation(
                                code="ARCH203",
                                path=rel_path,
                                line=int(node.lineno),
                                message=(
                                    "Detected direct transport client usage for Twilio flow. "
                                    "Use autonomy.tools.agent_commerce.request_json."
                                ),
                                snippet=_safe_line(lines, int(node.lineno)),
                            )
                        )
                        continue

                    if isinstance(node.func.value, ast.Call):
                        factory = _resolve_alias_dotted_name(
                            _dotted_name(node.func.value.func),
                            import_alias_map,
                        )
                        if factory in TRANSPORT_FACTORY_CALLS:
                            violations.append(
                                Violation(
                                    code="ARCH203",
                                    path=rel_path,
                                    line=int(node.lineno),
                                    message=(
                                        "Detected direct transport factory usage for Twilio flow. "
                                        "Use autonomy.tools.agent_commerce.request_json."
                                    ),
                                    snippet=_safe_line(lines, int(node.lineno)),
                                )
                            )

    deduped = {
        (v.code, v.path, v.line, v.message, v.snippet): v
        for v in violations
    }
    return sorted(
        deduped.values(),
        key=lambda v: (v.path, v.line, v.code, v.message),
    )


def _target_files() -> list[Path]:
    return sorted(TOOLS_DIR.rglob("*.py"), key=lambda p: p.as_posix())


def main() -> int:
    files = _target_files()
    if not files:
        print("Architecture gate runtime error: no files matched autonomy/tools/**/*.py")
        return EXIT_RUNTIME_ERROR

    violations: list[Violation] = []
    for py_file in files:
        violations.extend(_analyze_file(py_file))

    if not violations:
        print("Architecture gate PASSED: 0 violations.")
        print(f"Checked {len(files)} files under autonomy/tools/**/*.py")
        return EXIT_OK

    print(f"Architecture gate FAILED: {len(violations)} violation(s).")
    print("Approved Twilio wrappers:")
    for filename in sorted(APPROVED_TWILIO_WRAPPER_FILES):
        print(f"  - autonomy/tools/{filename}")
    print("Violations:")
    for violation in violations:
        print(
            f"  - [{violation.code}] {violation.path}:{violation.line} "
            f"{violation.message}"
        )
        if violation.snippet:
            print(f"      {violation.snippet}")
    return EXIT_VIOLATIONS


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive guardrail for CI reliability
        print(f"Architecture gate runtime error: {type(exc).__name__}: {exc}")
        raise SystemExit(EXIT_RUNTIME_ERROR)
