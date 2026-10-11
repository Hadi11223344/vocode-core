#!/usr/bin/env python3
"""Architecture fitness rules — grep-based checks for boundary violations.

Complements import-linter with pattern-based checks that import-linter
cannot express (e.g. "class X must only be instantiated in directory Y").

Exit code 0 = all checks pass, 1 = violations found.

Usage:
    python scripts/check_architecture.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "voice_platform"


def _glob_python_files(base: Path, pattern: str = "**/*.py") -> list[Path]:
    return sorted(base.rglob(pattern))


def _grep_files(files: list[Path], pattern: str) -> list[tuple[Path, int, str]]:
    compiled = re.compile(pattern)
    hits: list[tuple[Path, int, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                hits.append((f, i, line.strip()))
    return hits


def check_no_api_imports_in_lower_layers() -> list[str]:
    """B3: No 'from voice_platform.api' imports in runtime, flow, events, agents, etc."""
    forbidden_dirs = [
        "runtime",
        "flow",
        "events",
        "transport",
        "observability",
        "agents",
        "telephony",
        "actions",
        "integrations",
        "middleware",
        "utils",
    ]
    violations: list[str] = []
    for dir_name in forbidden_dirs:
        dir_path = ROOT / dir_name
        if not dir_path.exists():
            continue
        py_files = _glob_python_files(dir_path)
        hits = _grep_files(py_files, r"^\s*from\s+voice_platform\.api\b")
        for f, lineno, line in hits:
            rel = f.relative_to(ROOT.parent)
            violations.append(f"  {rel}:{lineno}: {line}")
    return violations


def check_class_instantiation_locations() -> list[str]:
    """B2: Verify certain classes are only instantiated in expected directories."""
    rules = [
        ("compile_flow\\(", ["runtime/session/", "flow/", "agents/"], "compile_flow() must only be called in runtime/session/, flow/, or agents/"),
        ("ConversationSession\\(", ["runtime/session/", "api/", "agents/"], "ConversationSession() must only be instantiated in runtime/session/, api/, or agents/"),
        ("LangGraphFlowExecutor\\(", ["runtime/session/", "flow/"], "LangGraphFlowExecutor() must only be instantiated in runtime/session/ or flow/"),
    ]
    violations: list[str] = []
    for pattern, allowed_prefixes, msg in rules:
        all_files = _glob_python_files(ROOT)
        hits = _grep_files(all_files, pattern)
        for f, lineno, line in hits:
            rel = f.relative_to(ROOT.parent)
            rel_str = str(rel).replace("\\", "/")
            if any(rel_str.startswith(f"voice_platform/{p}") for p in allowed_prefixes):
                continue
            if "test_" in f.name:
                continue
            violations.append(f"  {rel}:{lineno}: {line}  [{msg}]")
    return violations


def check_is_safe_url_single_definition() -> list[str]:
    """Acceptance criterion 5: _is_safe_url defined in exactly one file."""
    all_files = _glob_python_files(ROOT)
    hits = _grep_files(all_files, r"^\s*def _is_safe_url\b")
    if len(hits) <= 1:
        return []
    return [
        f"  {f.relative_to(ROOT.parent)}:{lineno}: {line}"
        for f, lineno, line in hits
    ]


def main() -> int:
    errors: list[str] = []

    # B3: Upward-import verification
    api_violations = check_no_api_imports_in_lower_layers()
    if api_violations:
        errors.append("FAIL: 'from voice_platform.api' imports found in lower layers:")
        errors.extend(api_violations)

    # B2: Class instantiation fitness rules
    class_violations = check_class_instantiation_locations()
    if class_violations:
        errors.append("FAIL: Class instantiation boundary violations:")
        errors.extend(class_violations)

    # Acceptance criterion 5: _is_safe_url single definition
    ssrf_violations = check_is_safe_url_single_definition()
    if ssrf_violations:
        errors.append("FAIL: _is_safe_url defined in multiple files (should be only utils/ssrf.py):")
        errors.extend(ssrf_violations)

    if errors:
        print("\n".join(errors))
        return 1

    print("OK: All architecture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
