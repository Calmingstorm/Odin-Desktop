"""Exercise thin desktop boundary modules with disposable, inert dependencies."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.desktop import package_ownership, profile, schedule_recovery, x11_probe
from src.desktop.package_state import PackageStateError


def test_fresh_profile_rejects_nonselected_profile_before_provisioning(monkeypatch):
    selected = object()
    provision = Mock(side_effect=AssertionError("must not touch another profile"))
    monkeypatch.setattr(profile, "runtime_profile_paths", lambda: selected)
    monkeypatch.setattr("src.desktop.provisioning.provision_fresh_profile", provision)
    with pytest.raises(ValueError, match="selected desktop profile"):
        profile.provision_fresh_profile(object())
    provision.assert_not_called()
    provision.side_effect = None
    assert profile.provision_fresh_profile(selected) is provision.return_value
    provision.assert_called_once_with(selected)


def test_development_core_requires_no_installed_package_lease(tmp_path):
    assert package_ownership.acquire_core_lease(
        object(), source_file=tmp_path / "src" / "desktop" / "core.py") is None


def test_installed_package_cannot_load_symlinked_ownership(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "ownership.py").symlink_to(tmp_path / "missing.py")
    with pytest.raises(PackageStateError, match="startup refused"):
        package_ownership.acquire_core_lease(
            object(), source_file=resources / "runtime" / "src" / "core.py")


@pytest.mark.parametrize("kind", ["appimage", "deb"])
def test_installed_core_uses_shipped_module_and_provisional_cleanup_lease(
        tmp_path, monkeypatch, kind):
    resources = Path("/opt/Odin/resources") if kind == "deb" else tmp_path / "resources"
    paths = SimpleNamespace(config_dir=tmp_path / "config" / "default",
                            data_dir=tmp_path / "data", profile_id="default")
    acquire = Mock(return_value="lease")
    owned = Mock(return_value="ownership paths")
    module = SimpleNamespace(acquire_lifetime=acquire, ownership_paths=owned)
    loader = SimpleNamespace(exec_module=Mock())
    spec = SimpleNamespace(name="odin_package_ownership", loader=loader)
    load_spec = Mock(return_value=spec)
    monkeypatch.setattr(package_ownership.importlib.util, "spec_from_file_location", load_spec)
    monkeypatch.setattr(package_ownership.importlib.util, "module_from_spec", lambda _: module)
    # Preserve the ambient module registry even if another test loaded a real module.
    monkeypatch.setitem(package_ownership.sys.modules, spec.name, module)
    assert package_ownership.acquire_core_lease(
        paths, source_file=resources / "runtime" / "src" / "core.py") == "lease"
    load_spec.assert_called_once_with(spec.name, resources / "ownership.py")
    loader.exec_module.assert_called_once_with(module)
    owned.assert_called_once_with(kind)
    acquire.assert_called_once_with("ownership paths", "core",
        tmp_path / "config" / "default-cleanup-state.json",
        tmp_path / "data" / "resource-cleanup.json", provisional=True)


@pytest.mark.parametrize("patch", [
    {}, {"next_run": "invalid"}, {"next_run": 123},
    {"next_run": "2026-10-07T12:00:00+00:00", "paused": True},
    {"next_run": "2026-10-07T12:00:00+00:00", "retry_at": "pending"},
])
def test_recovery_skips_missing_invalid_paused_and_retrying_schedule(patch):
    schedule = dict(patch)
    assert schedule_recovery.recover_due(schedule, datetime(2026, 10, 7, 13, tzinfo=UTC)) is False
    assert schedule == patch


def test_recovery_grace_clears_stale_notice_without_consuming_run():
    now = datetime(2026, 10, 7, 13, tzinfo=UTC)
    due = (now - timedelta(seconds=60)).isoformat()
    schedule = {"next_run": due, "missed_run": {"old": True}}
    assert schedule_recovery.recover_due(schedule, now) is False
    assert schedule == {"next_run": due}


def test_reminder_recovery_coalesces_and_preserves_original_slot():
    now = datetime(2026, 10, 7, 13, tzinfo=UTC)
    due = (now - timedelta(minutes=3)).isoformat()
    schedule = {"next_run": due, "cron": "* * * * *", "action": "reminder"}
    assert schedule_recovery.recover_due(schedule, now) is False
    assert schedule["next_run"] == due
    assert schedule["missed_run"] == {
        "due_at": due, "observed_at": now.isoformat(), "lateness_seconds": 180,
        "missed_count": 4, "omitted_count": 3, "count_truncated": False,
        "policy": "coalesced", "workflow_catchup_limit": 0,
    }
    assert "recovery_required" not in schedule


@pytest.mark.parametrize("cron", [None, "* * * * *"])
def test_missed_workflow_requires_manual_run_and_never_replays(cron):
    now = datetime(2026, 10, 7, 13, tzinfo=UTC)
    schedule = {"next_run": (now - timedelta(days=3)).isoformat(), "action": "workflow"}
    if cron:
        schedule["cron"] = cron
        schedule["timezone"] = "America/New_York"
    assert schedule_recovery.recover_due(schedule, now, count_limit=2) is True
    missed = schedule["missed_run"]
    assert missed["policy"] == "manual" and missed["workflow_catchup_limit"] == 0
    assert schedule["recovery_required"].endswith("No effects were replayed.")
    if cron:
        assert missed["missed_count"] == 2 and missed["count_truncated"] is True
        assert schedule["next_run"] == (now + timedelta(minutes=1)).isoformat()
    else:
        assert missed["missed_count"] == 1 and missed["count_truncated"] is False
        assert "next_run" not in schedule


@pytest.mark.parametrize("failure", [False, True])
def test_monitor_probe_reads_names_and_always_closes_inert_capture(monkeypatch, capsys, failure):
    capture = Mock()
    capture.topology.return_value = SimpleNamespace(monitors=[
        SimpleNamespace(identity=(41,)), SimpleNamespace(identity=(42,))])
    capture._connection._display.get_atom_name.side_effect = (
        RuntimeError("fixture probe failed") if failure else ["left", "right"])
    constructor = Mock(return_value=capture)
    monkeypatch.setattr(x11_probe, "X11MonitorCapture", constructor)
    monkeypatch.setattr(x11_probe.sys, "argv", ["probe", ":fixture"])
    if failure:
        with pytest.raises(RuntimeError, match="fixture probe failed"):
            x11_probe.main()
    else:
        x11_probe.main()
        assert capsys.readouterr().out == '["left", "right"]\n'
    constructor.assert_called_once_with(":fixture", enabled=True)
    capture.close.assert_called_once_with()
