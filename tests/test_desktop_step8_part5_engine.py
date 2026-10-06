"""Exact inherited engine definitions, never a replacement smoke suite."""

import pytest

from tests.desktop_adapters.step8_part5_engine import (
    export_suite,
    selected_tree,
    selection,
    source_cases,
    verified_tree,
)
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest.fixture(autouse=True)
def step8_part5_engine_owner(tmp_path):
    with owner_fixture(tmp_path):
        yield


for _suite in ("test_fd_health", "test_local_workspace", "test_main_exit_codes", "test_restart"):
    export_suite(globals(), _suite)


@pytest.mark.parametrize("suite", (
    "test_fd_health", "test_local_workspace", "test_main_exit_codes", "test_restart",
))
def test_step8_part5_engine_exact_provenance(suite):
    """Exercises the inverse-AST guard and exact selection, not prose wording."""
    original, _, _ = verified_tree(suite)
    selected, _ = selected_tree(suite)
    assert set(source_cases(selected)) == selection(suite, original)
