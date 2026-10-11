"""The installed Windows app's package lease (phase 4, P8): the bundled guardian's Windows half.

The app and the core each hold a shared ``LockFileEx`` lease on one byte of a private file
outside the install tree; a replacement takes it exclusively and is refused while either holds
it. An admitted lifetime leaves a receipt naming this user's SID and this boot, and a lifetime
that ended without finishing clean keeps refusing a replacement even after its lock is gone.
"""
from __future__ import annotations

import _winapi
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARDIAN = ROOT / "app" / "packaging" / "ownership.py"


@pytest.fixture
def ownership(monkeypatch, tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    spec = importlib.util.spec_from_file_location("odin_ownership_under_test", GUARDIAN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def cleanup(tmp_path):
    return tmp_path / "app-cleanup.json", tmp_path / "core-cleanup.json"


def test_app_and_core_share_the_lease_and_a_replacement_waits_for_both(ownership, tmp_path):
    paths = ownership.ownership_paths("nsis")
    local = Path(os.environ["LOCALAPPDATA"])
    assert paths.lease == local / "odin-desktop" / "install-ownership" / "nsis" / "lease"
    with ownership.acquire_lifetime(paths, "app", *cleanup(tmp_path), provisional=True), \
            ownership.acquire_lifetime(paths, "core", *cleanup(tmp_path), provisional=True):
        with pytest.raises(ownership.OwnershipError, match="Exit both app and core"):
            with ownership.replacement_guard(paths, check_receipts=False):
                pass
    with ownership.replacement_guard(paths):  # both gone, nothing admitted: it proceeds
        pass


def test_this_boot_is_known_to_a_standard_user(ownership):
    current = ownership._boot_id()
    assert current is not None and ownership._WINDOWS_BOOT_ID_SHAPE.fullmatch(current)
    assert ownership._earlier_boot("windows-0", current) is (current != "windows-0")
    assert ownership._earlier_boot(current, current) is False


def test_an_unfinished_lifetime_keeps_refusing_after_its_lock_is_gone(ownership, tmp_path):
    paths = ownership.ownership_paths("nsis")
    lease = ownership.acquire_lifetime(paths, "core", *cleanup(tmp_path), provisional=True)
    try:
        lease.begin()
        receipt = json.loads(lease.receipt.read_text(encoding="utf-8"))
        assert receipt["state"] == "running" and receipt["role"] == "core"
        assert receipt["uid"].startswith("S-1-5-")  # the SID is recorded; the name stays short
        assert lease.receipt.name.endswith("-core.json") and len(lease.receipt.name) == 42
        assert receipt["boot_id"] == ownership._boot_id()
    finally:
        lease.close()  # gone without finishing clean, as after a crash
    with pytest.raises(ownership.OwnershipError, match="Unresolved lifetime evidence"):
        with ownership.replacement_guard(paths):
            pass


def test_a_lease_file_others_can_read_is_refused(ownership, sddl):
    from src.desktop.platform.windows_files import user_sid

    paths = ownership.ownership_paths("nsis")
    ownership._close(ownership._open(paths))
    sddl(paths.lease, f"D:P(A;;FA;;;{user_sid()})(A;;FR;;;WD)", directory=False)
    with pytest.raises(OSError):
        ownership._open(paths)


def test_a_junction_to_the_lease_folder_contends_for_the_same_lease(ownership, tmp_path):
    paths = ownership.ownership_paths("nsis")
    with ownership.acquire_lifetime(paths, "app", *cleanup(tmp_path), provisional=True):
        alias = tmp_path / "alias"
        _winapi.CreateJunction(str(paths.directory), str(alias))
        with pytest.raises(ownership.OwnershipError, match="Exit both app and core"):
            with ownership.replacement_guard(ownership.OwnershipPaths(alias), check_receipts=False):
                pass


def test_a_killed_guardian_frees_the_lock_but_its_receipt_still_refuses(ownership, tmp_path):
    paths = ownership.ownership_paths("nsis")
    app_cleanup, core_cleanup = cleanup(tmp_path)
    guardian = subprocess.Popen(
        [sys.executable, "-I", "-B", str(GUARDIAN), "hold", "--kind", "nsis", "--role", "app",
         "--app-cleanup", str(app_cleanup), "--core-cleanup", str(core_cleanup)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert guardian.stdout.readline() == "READY\n"
        guardian.stdin.write("ADMIT\n")
        guardian.stdin.flush()
        assert guardian.stdout.readline() == "ADMITTED\n"
        with pytest.raises(ownership.OwnershipError, match="Exit both app and core"):
            with ownership.replacement_guard(paths, check_receipts=False):
                pass
    finally:
        guardian.kill()
        guardian.communicate(timeout=30)
    with ownership.replacement_guard(paths, check_receipts=False):  # the kernel released the lock
        pass
    with pytest.raises(ownership.OwnershipError, match="Unresolved lifetime evidence"):
        with ownership.replacement_guard(paths):
            pass
