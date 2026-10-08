"""Real temporary-profile package observations through the named core surface."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.core import CoreService
from src.desktop.package_state import PackageStateError, PackageUpgrade, compatibility
from src.desktop.resource_cleanup import ResourceCleanupError
from src.version import get_version
from tests.test_desktop_core_lifecycle import connect, profile, receive, request
from tests.test_desktop_management_core import TemporaryKeyring


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import aiohttp

    def refused(*args, **kwargs):
        raise AssertionError("Package status must not fetch release metadata")

    monkeypatch.setattr(aiohttp, "ClientSession", refused)


@asynccontextmanager
async def running(paths, socket_path, token_file, **kwargs):
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring(), **kwargs)
    writer = None
    def close_parent():
        nonlocal write_fd
        os.close(write_fd)
        write_fd = None

    try:
        await core.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        yield core, reader, writer, welcome, close_parent
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        core.release_runtime()
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


async def test_package_identity_is_profile_bound_and_incarnation_fenced(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    identities = []
    for _ in range(2):
        async with running(paths, socket_path, token_file) as (core, reader, writer, welcome, _):
            package = (await request(reader, writer, "status.get"))["result"]["package"]
            identities.append(package["identity"])
            assert package["identity"] == {
                "product": "odin-desktop", "package_version": get_version(),
                "installation_id": core.authority.installation_id,
                "profile_id": paths.profile_id,
                "core_instance_id": welcome["core"]["instance_id"],
            }
            assert package["compatibility"] == compatibility()
            assert package["profile_state"] == {
                "state": "committed", "package_version": get_version(),
                "evidence": "startup_compatibility_and_migration_barriers",
            }
    assert identities[0]["installation_id"] == identities[1]["installation_id"]
    assert identities[0]["core_instance_id"] != identities[1]["core_instance_id"]
    assert core.package_status.snapshot()["identity"] == identities[1]


async def test_package_reads_are_notice_only_without_receipts_or_cleanup_effects(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file) as (core, reader, writer, welcome, _):
        before = {p: p.read_bytes() for p in (
            paths.data_dir / "package-state.json", paths.data_dir / "resource-cleanup.json")}
        high = core.events.high
        for _ in range(2):
            package = (await request(reader, writer, "status.get"))["result"]["package"]
            assert package["update"] == {
                "mode": "notice_only", "state": "not_checked", "owner": "app_release_notice",
                "reason": "release_metadata_not_checked_by_core", "apply_available": False,
            }
            handoff = package["handoff"]
            assert handoff["state"] == "running" and handoff["admitting"]
            assert handoff["ownership_current"] and handoff["profile_runtime_owned"]
            assert not handoff["core_quiesced"] and not handoff["replacement_safe"]
            assert handoff["effects_undone"] is False and handoff["replay"] is False
        assert core.events.high == high
        receipts = core.store.connection.execute("SELECT count(*) FROM command_receipts").fetchone()
        assert receipts[0] == 0
        assert {p: p.read_bytes() for p in before} == before
        assert not {"package.apply", "update.apply", "package.status", "rpc"} & set(
            welcome["capabilities"])
        for method in ("package.apply", "update.apply", "package.status", "rpc"):
            rejected = await request(reader, writer, method)
            assert rejected["error"]["code"] == "capability_unavailable"
        assert core.lifetime.admitting


async def test_shutdown_acceptance_is_not_quiescence_and_event_never_claims_ready(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file) as (core, reader, writer, _, _):
        await request(reader, writer, "events.subscribe", {"after": None})
        accepted = await request(reader, writer, "runtime.shutdown", {
            "reason": "package-manager exit"})
        assert accepted["result"] == {"disposition": "accepted"}
        event = await receive(reader)
        handoff = event["payload"]["package"]["handoff"]
        assert handoff["state"] == "quiescing" and not handoff["admitting"]
        assert not handoff["core_quiesced"] and not handoff["replacement_safe"]
        assert "core_close_not_complete" in handoff["blockers"]
        assert "shutdown_not_requested" not in handoff["blockers"]
        assert core.package_status.snapshot()["handoff"]["stop_reason"] == "runtime.shutdown"
        late = await request(reader, writer, "conversations.create", {"title": "late"})
        assert late["error"]["code"] == "busy"


async def test_package_handoff_waits_for_producers_close_and_external_ownership(
    tmp_path, monkeypatch,
):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file, release_runtime_on_close=False) as (
        core, reader, writer, _, _,
    ):
        entered, release = asyncio.Event(), asyncio.Event()
        original = core.engine.close

        async def blocked_close():
            entered.set()
            await release.wait()
            await original()

        monkeypatch.setattr(core.engine, "close", blocked_close)
        await request(reader, writer, "runtime.shutdown", {"reason": "exit"})
        closing = asyncio.create_task(core.close())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            pending = core.package_status.snapshot()["handoff"]
            assert core._closed and not pending["core_close_complete"]
            assert not pending["core_quiesced"] and not pending["replacement_safe"]
            assert "producers_not_quiesced" in pending["blockers"]
        finally:
            release.set()
            await asyncio.wait_for(closing, 15)
        closed = core.package_status.snapshot()["handoff"]
        assert closed["state"] == "core_closed" and closed["core_quiesced"]
        assert closed["core_close_complete"] and closed["producers_quiesced"]
        assert closed["cleanup"]["state"] == "complete"
        assert closed["profile_runtime_owned"] and not closed["replacement_safe"]
        contender = OwnerAuthority(paths)
        with pytest.raises(BlockingIOError):
            contender.acquire_runtime()
        core.release_runtime()  # Test owner release, not process containment qualification.
        after = core.package_status.snapshot()["handoff"]
        assert after["core_quiesced"] and not after["profile_runtime_owned"]
        assert not after["replacement_safe"]
        assert after["blockers"] == ["external_package_ownership_barrier_required"]
        contender.acquire_runtime()
        contender.release_runtime()


async def test_parent_loss_uses_same_package_handoff(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file) as (core, _, _, _, close_parent):
        close_parent()
        await asyncio.wait_for(core.lifetime.wait(), 2)
        handoff = core.package_status.snapshot()["handoff"]
        assert handoff["stop_reason"] == "parent_eof"
        assert handoff["state"] == "quiescing" and not handoff["core_quiesced"]


async def test_unknown_cleanup_survives_successful_close_and_restart(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    # Establish the actual profile identity before retained cleanup evidence.
    async with running(paths, socket_path, token_file):
        pass
    receipt = paths.data_dir / "resource-cleanup.json"
    receipt.write_text(json.dumps({"version": 1, "state": "unknown", "at": "prior",
                                   "resources": {"computer": {"state": "unknown"}}}))
    receipt.chmod(0o600)
    for _ in range(2):
        async with running(paths, socket_path, token_file) as (core, reader, writer, _, _):
            handoff = (await request(reader, writer, "status.get"))["result"]["package"]["handoff"]
            assert handoff["state"] == "cleanup_unknown"
            assert handoff["cleanup"]["previous_unknown"]["resources"] == {
                "computer": {"state": "unknown"}}
            assert "cleanup_reconciliation_required" in handoff["blockers"]
            assert handoff["replay"] is False and not handoff["replacement_safe"]
        closed = core.package_status.snapshot()["handoff"]
        assert closed["core_close_complete"] and closed["cleanup"]["state"] == "complete"
        assert not closed["core_quiesced"] and not closed["replacement_safe"]


async def test_cleanup_storage_failure_does_not_turn_closed_guard_into_success(
    tmp_path, monkeypatch,
):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file) as (core, _, _, _, _):
        def unavailable():
            raise ResourceCleanupError("harmless test storage failure")

        monkeypatch.setattr(core.resource_cleanup, "_write", unavailable)
        with pytest.raises(ResourceCleanupError):
            await core.close()
        handoff = core.package_status.snapshot()["handoff"]
        assert core._closed and not handoff["core_close_complete"]
        assert not handoff["core_quiesced"] and not handoff["replacement_safe"]
        assert "core_close_not_complete" in handoff["blockers"]


async def test_replaced_runtime_lock_is_not_valid_package_fencing(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file) as (core, _, _, _, _):
        lock = paths.config_dir / ".core.lock"
        lock.rename(paths.config_dir / ".old-core.lock")
        lock.write_text("")
        lock.chmod(0o600)
        handoff = core.package_status.snapshot()["handoff"]
        assert handoff["state"] == "ownership_unavailable"
        assert not handoff["admitting"] and not handoff["ownership_current"]
        assert "ownership_unavailable" in handoff["blockers"]
        assert not handoff["core_quiesced"] and not handoff["replacement_safe"]
        await core.close()
        after = core.package_status.snapshot()["handoff"]
        assert after["state"] == "ownership_unavailable"
        assert not after["profile_runtime_owned"] and not after["core_quiesced"]
        assert "ownership_unavailable" in after["blockers"]


async def test_listener_close_failure_does_not_attest_successful_core_close(tmp_path, monkeypatch):
    paths, socket_path, token_file = profile(tmp_path)
    async with running(paths, socket_path, token_file) as (core, _, _, _, _):
        original = core.server.close_listener

        async def unavailable():
            await original()
            raise RuntimeError("harmless test listener failure")

        monkeypatch.setattr(core.server, "close_listener", unavailable)
        with pytest.raises(RuntimeError):
            await core.close()
        handoff = core.package_status.snapshot()["handoff"]
        assert handoff["cleanup"]["state"] == "complete"
        assert not handoff["core_close_complete"] and not handoff["core_quiesced"]
        assert not handoff["replacement_safe"]


async def test_failed_package_commit_keeps_pending_startup_status(tmp_path, monkeypatch):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring())

    def unavailable(self):
        raise PackageStateError("harmless test commit failure")

    monkeypatch.setattr(PackageUpgrade, "commit", unavailable)
    try:
        with pytest.raises(PackageStateError):
            await core.start(read_fd)
        package = core.package_status.snapshot()
        assert package["profile_state"]["state"] == "pending"
        assert json.loads((paths.data_dir / "package-state.json").read_text())["state"] == "pending"
        assert not socket_path.exists()
        assert package["handoff"]["state"] == "starting"
        assert not package["handoff"]["admitting"] and not package["handoff"]["replacement_safe"]
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


def _app_version():
    import json
    from pathlib import Path
    package = Path(__file__).resolve().parents[1] / "app" / "package.json"
    return json.loads(package.read_text())["version"]


def test_product_version_reads_the_launched_bundle_manifest(tmp_path, monkeypatch):
    import json

    from src.desktop.package_status import product_version
    runtime = tmp_path / "resources" / "runtime"
    runtime.mkdir(parents=True)
    (tmp_path / "resources" / "bundle-manifest.json").write_text(json.dumps(
        {"product": {"name": "odin-desktop", "version": "9.8.7"}}))
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(runtime))
    assert product_version() == "9.8.7"


@pytest.mark.parametrize("manifest", [
    '{"product": {"version": "not a version"}}', "{", '{"product": 1}', None])
def test_product_version_falls_back_to_the_app_package(tmp_path, monkeypatch, manifest):
    from src.desktop.package_status import product_version
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    if manifest is not None:
        (tmp_path / "bundle-manifest.json").write_text(manifest)
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(runtime))
    assert product_version() == _app_version()
    monkeypatch.delenv("ODIN_DESKTOP_BUNDLE_ROOT")
    assert product_version() == _app_version()


def test_product_version_last_resort_is_the_engine_version(tmp_path, monkeypatch):
    import src.desktop.package_status as package_status
    from src.version import get_version
    monkeypatch.delenv("ODIN_DESKTOP_BUNDLE_ROOT", raising=False)
    elsewhere = tmp_path / "a" / "b" / "package_status.py"
    monkeypatch.setattr(package_status, "__file__", str(elsewhere))
    assert package_status.product_version() == get_version()


def test_core_reports_the_product_version_not_the_engine_build():
    from src.desktop.core import VERSION
    assert VERSION == _app_version()
