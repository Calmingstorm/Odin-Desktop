"""Immutable accessibility/runtime cases placed at their real worker seam.

The original suite stubs native effects and GI modules before every test. Its
code, assertions, parameters and no-native-effects fixture stay unchanged.
Worker eligibility is the only new fixture placement required by step 6A.
"""
import importlib.util
from pathlib import Path

import pytest

from src.computer.runtime import dependency_resolver

spec = importlib.util.spec_from_file_location(
    "_retained_accessibility_runtime_cases",
    Path(__file__).with_name("test_computer_runtime_coverage_r10.py"))
retained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)
no_native_effects = retained.no_native_effects


@pytest.fixture(autouse=True)
def worker_placement(monkeypatch):
    monkeypatch.setattr(dependency_resolver, "_worker_process", lambda: True)


for name in dir(retained):
    if name.startswith("test_"):
        globals()[name] = getattr(retained, name)
