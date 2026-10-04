"""Lint exceptions are named inherited findings, not whole-file exclusions."""

from pathlib import Path

from scripts.maintenance.lint_gate import classify


def test_lint_exceptions_do_not_hide_new_codes_or_symbols():
    root = Path("/fixture")
    findings = [
        {"filename": "/fixture/src/llm/recovery.py", "code": "UP047",
         "message": "Generic function `_attempt_cancellable` should use type parameters"},
        {"filename": "/fixture/src/llm/recovery.py", "code": "F401",
         "message": "Unused `_attempt_cancellable` import"},
        {"filename": "/fixture/src/llm/recovery.py", "code": "UP047",
         "message": "Generic function `new_function` should use type parameters"},
    ]
    inherited, new = classify(findings, root)
    assert inherited == findings[:1]
    assert new == findings[1:]
