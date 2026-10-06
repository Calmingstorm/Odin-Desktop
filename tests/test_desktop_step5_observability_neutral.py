"""Whole frozen recovery/pool suites over authentic temporary owners."""

import pytest

from src.tools import builtin_policy
from tests.desktop_adapters.step5_observability_neutral import (
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    FIXTURE_CAPABILITIES,
    SUITES,
    load,
    owner_fixture,
)


@pytest.fixture(autouse=True)
def _temporary_authenticated_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(builtin_policy, "PHASE1_EXECUTOR_TOOL_NAMES",
                        builtin_policy.PHASE1_EXECUTOR_TOOL_NAMES | FIXTURE_CAPABILITIES)
    with owner_fixture(tmp_path):
        yield


load(globals())


def test_frozen_suite_metadata_is_complete():
    assert set(CORPUS_SELECTIONS) == {"test_recovery", "test_connection_pools"}
    assert all(selection is None for selection in CORPUS_SELECTIONS.values())
    assert set(SUITES) == set(CORPUS_SELECTIONS)
    assert CORPUS_EXCLUSIONS == {}
    assert all(len(digest) == 64 for digest in SUITES.values())


