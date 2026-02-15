from __future__ import annotations

import ast
import py_compile
import re
from pathlib import Path


CRITICAL_MODULES = [
    Path("app/handlers/planner.py"),
    Path("app/handlers/orders.py"),
    Path("app/handlers/files.py"),
    Path("app/handlers/ui_callbacks.py"),
    Path("app/server.py"),
    Path("app/bot.py"),
]

DANGEROUS_EMPTY_FALLBACK_RE = re.compile(r"\bor\s*(?:\"\"|'')")


def test_critical_modules_compile() -> None:
    for module_path in CRITICAL_MODULES:
        py_compile.compile(str(module_path), doraise=True)


def test_no_empty_string_fallback_inside_fstring_expression() -> None:
    offenders: list[str] = []

    for py_file in Path("app").rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))

        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            for value in node.values:
                if not isinstance(value, ast.FormattedValue):
                    continue
                expression = ast.get_source_segment(source, value.value) or ""
                if DANGEROUS_EMPTY_FALLBACK_RE.search(expression):
                    offenders.append(f"{py_file}:{value.lineno}:{expression.strip()}")

    assert not offenders, "Avoid `or \"\"` / `or ''` in f-string expressions:\n" + "\n".join(offenders)
