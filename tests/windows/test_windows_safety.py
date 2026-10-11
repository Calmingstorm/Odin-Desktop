"""Native classification-only fixtures, never shell execution."""
# ruff: noqa: F401, I001, E501
import sys

import pytest

from tests.test_desktop_windows_safety import (
    test_destructive_critical,
    test_exfil_critical,
    test_high,
    test_safe_data,
    test_encoded_wrapper,
    test_active_wrappers,
    test_local_route_retains_settings_stats_and_admin_warning,
    test_direct_local_address_validation_route,
    test_literal_review_root_wrappers,
    test_literal_review_exfil_only_policy,
    test_literal_download_then_launch,
    test_registry_provider_and_cmd_credential_read,
    test_cmd_attached_wrapper,
    test_sensitive_directory_endpoint_and_literal_data_raw,
    test_policy_matches_original,
    test_remote_target_alias_spelled_localhost_is_remote,
    test_opaque_or_bounds,
    test_git_force_still_non_overridable,
    test_exact_lifted_check,
    test_medium,
    test_remote_unknown_and_disabled_routes,
    test_lease_address_wins_registry,
    test_review_b1_counterparts,
    test_review_b1_sql_text_floor,
    test_review_b1_nonmutating_forms,
    test_review_p3_download_spellings,
    test_review_p3_download_data_not_execution,
    test_review_p3_root_spellings,
    test_review_p3_nonroot_spellings,
    test_review_p3_profile_secret_store,
    test_review_p3_secret_store_nonaccess,
    test_review_p3_icm_alias,
    test_review_r2_package_aliases,
    test_review_r2_service_start,
    test_review_r2_account_modification,
    test_review_r2_msiexec_dash,
    test_review_r2_false_positive_controls,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="native Windows routing")


def test_native_decorator_installed():
    from src.tools.executor import ToolExecutor
    assert ToolExecutor._govern_command.windows_target == "src.desktop.platform.windows_safety:govern_command"


def test_native_decorator_executes_local_variant_and_remote_original():
    from types import SimpleNamespace
    from src.tools.executor import ToolExecutor
    from src.tools.risk_classifier import CommandGovernor
    target = SimpleNamespace(alias="fixture", address="127.0.0.1")
    executor = SimpleNamespace(command_governor=CommandGovernor(), _current_user_id="fixture",
                               _permission_manager=None,
                               host_registry=SimpleNamespace(get=lambda *a, **k: target))
    assert not ToolExecutor._govern_command(executor, "Stop-Computer", "fixture")[0]
    target.address = "192.0.2.1"
    assert ToolExecutor._govern_command(executor, "Stop-Computer", "fixture") == (
        ToolExecutor._govern_command.linux_original(executor, "Stop-Computer", "fixture"))
