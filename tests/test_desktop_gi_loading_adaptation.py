"""Run the exact immutable GI cases with the new worker-only discovery seam.

The original cases patch all external imports/path probes before any load. Only
their module-under-test and worker eligibility are adapted, not their assertions.
"""
import importlib.util
from pathlib import Path

import pytest

from src.computer.runtime import dependency_resolver

spec = importlib.util.spec_from_file_location(
    "_retained_gi_loading_cases", Path(__file__).with_name("test_gi_support_loading.py"))
retained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)
retained.gi_support = dependency_resolver


@pytest.fixture
def fallback(monkeypatch):
    monkeypatch.setattr(dependency_resolver, "_worker_process", lambda: True)
    return retained.fallback.__wrapped__(monkeypatch)


for name in dir(retained):
    if name.startswith("test_"):
        globals()[name] = getattr(retained, name)
