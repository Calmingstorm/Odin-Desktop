"""Odin 4.23.0 (PR #735, #733) in Desktop: the 4.23.0 versions of superseded frozen cases.

Odin 4.23.0's run_ssh_command asks the pool for the master it acquired
(``SSHConnectionPool.master_process``), so a pooled call whose master has ended is known to
have lost its connection. Six pooled cases of tests/test_campaign_process_final_coverage.py
build an inert stand-in pool without that method, so the plan no longer selects them. Their
4.23.0 forms run here: the frozen module's own test bodies, with Odin 4.23.0's stand-in,
which answers ``master_process`` with None (no master of this pool's to watch).
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

import tests.test_campaign_process_final_coverage as frozen

# The frozen module's own autouse OS boundary (blocked process spawns and kills).
inert_os_boundary = frozen.inert_os_boundary
_frozen_inert_pool = frozen.inert_pool


def _inert_pool_4230(events):
    pool = _frozen_inert_pool(events)
    pool.master_process = Mock(return_value=None)
    return pool


@pytest.fixture(autouse=True)
def odin_4230_pool(monkeypatch):
    monkeypatch.setattr(frozen, "inert_pool", _inert_pool_4230)


test_pooled_timeout_retry_reaps_before_next_dispatch_and_releases = (
    frozen.test_pooled_timeout_retry_reaps_before_next_dispatch_and_releases)
test_pooled_cancel_releases_only_acquired_lease_and_reaps_child = (
    frozen.test_pooled_cancel_releases_only_acquired_lease_and_reaps_child)
test_pooled_registration_error_reaps_client_and_releases_without_retry = (
    frozen.test_pooled_registration_error_reaps_client_and_releases_without_retry)
test_pooled_exhausted_timeout_registers_legacy_master_and_releases = (
    frozen.test_pooled_exhausted_timeout_registers_legacy_master_and_releases)
test_pooled_backoff_cancel_prevents_another_dispatch_and_releases = (
    frozen.test_pooled_backoff_cancel_prevents_another_dispatch_and_releases)
