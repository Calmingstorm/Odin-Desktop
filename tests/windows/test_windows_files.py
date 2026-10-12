"""The Windows private-storage contract (phase 2 plan A2 and A5), on real NTFS."""
from __future__ import annotations

import _winapi
import errno
import os
import subprocess
import sys
import threading
import time

import pytest

from src.desktop.platform import win32, windows_files
from src.desktop.platform.windows_files import (
    HeldChain,
    dacl_is_private,
    ensure_private,
    flush_object,
    held,
    open_file,
    private_directory,
    publish,
    read_file,
    remove,
    retire,
    tombstones,
)


def security_of(path, *, directory):
    flags = win32.FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= win32.FILE_FLAG_BACKUP_SEMANTICS
    share = win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE
    handle = win32.create_file(path, win32.READ_CONTROL | win32.FILE_READ_ATTRIBUTES, share,
                               win32.OPEN_EXISTING, flags)
    try:
        return win32.object_security(handle)
    finally:
        win32.close(handle)


def test_private_directory_creates_every_namespace_folder_private(profile_root):
    target = profile_root / "data" / "secrets"
    private_directory(target)
    for path in (profile_root.parent, profile_root, profile_root / "data", target):
        security = security_of(path, directory=True)
        assert security.owner in windows_files.own_sids()
        assert dacl_is_private(security)


def test_existing_broad_namespace_folder_is_repaired(profile_root, sddl):
    folder = profile_root / "data"
    folder.mkdir(parents=True)
    sddl(folder, "D:P(A;OICI;FA;;;WD)(A;OICI;FA;;;OW)", directory=True)
    assert not dacl_is_private(security_of(folder, directory=True))
    private_directory(folder)
    assert dacl_is_private(security_of(folder, directory=True))


def test_null_dacl_namespace_folder_is_repaired_and_never_private(profile_root, sddl):
    folder = profile_root / "cache"
    folder.mkdir(parents=True)
    sddl(folder, "D:NO_ACCESS_CONTROL", directory=True)
    security = security_of(folder, directory=True)
    assert not security.dacl_present and not dacl_is_private(security)
    private_directory(folder)
    assert dacl_is_private(security_of(folder, directory=True))


def test_empty_dacl_is_not_a_null_dacl():
    empty = win32.ObjectSecurity(windows_files.user_sid(), True, True, ())
    null = win32.ObjectSecurity(windows_files.user_sid(), False, False, ())
    assert dacl_is_private(empty) and not dacl_is_private(null)


@pytest.mark.parametrize("ace", [
    (5, 0, 1, None),                                   # an object ACE: unreadable here
    (9, 0, 1, None),                                   # a callback ACE
    (win32.ACCESS_ALLOWED_ACE_TYPE, 0, 1, "S-1-1-0"),  # Everyone
])
def test_unsupported_or_foreign_grants_fail_closed(ace):
    assert not dacl_is_private(win32.ObjectSecurity(windows_files.user_sid(), True, True, (ace,)))


@pytest.mark.parametrize("ace", [
    (win32.ACCESS_DENIED_ACE_TYPE, 0, 1, "S-1-1-0"),
    (win32.ACCESS_ALLOWED_ACE_TYPE, win32.INHERIT_ONLY_ACE, 1, "S-1-1-0"),
    (win32.ACCESS_ALLOWED_ACE_TYPE, 0, 0, "S-1-1-0"),
])
def test_entries_that_grant_nothing_here_are_harmless(ace):
    assert dacl_is_private(win32.ObjectSecurity(windows_files.user_sid(), True, True, (ace,)))


def test_held_chain_blocks_renaming_any_ancestor(profile_root):
    target = profile_root / "data"
    private_directory(target)
    with held(target):
        with pytest.raises(PermissionError):
            os.rename(profile_root, profile_root.with_name("moved"))
        with pytest.raises(PermissionError):
            os.rename(target, target.with_name("moved"))
    os.rename(target, target.with_name("moved"))


def test_held_chain_refuses_a_junction_substituted_for_a_folder(profile_root, tmp_path):
    private_directory(profile_root / "real")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _winapi.CreateJunction(str(elsewhere), str(profile_root / "link"))
    # A junction in the requested path is resolved once (Linux's realpath), so the
    # held chain names the real folder; one met while holding is refused.
    chain = HeldChain(profile_root / "link")
    try:
        assert os.path.normcase(str(chain.path)) == os.path.normcase(str(elsewhere.resolve()))
    finally:
        chain.close()
    handle = win32.create_file(
        profile_root / "link", win32.READ_CONTROL | win32.FILE_READ_ATTRIBUTES,
        win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE, win32.OPEN_EXISTING,
        win32.FILE_FLAG_BACKUP_SEMANTICS | win32.FILE_FLAG_OPEN_REPARSE_POINT)
    try:
        with pytest.raises(OSError, match="link"):
            windows_files._verify_directory(handle, profile_root / "link", namespace=True,
                                            kind="profile")
    finally:
        win32.close(handle)


def test_private_state_needs_a_local_drive(monkeypatch):
    def contacted(path, *args, **kwargs):
        raise AssertionError("a network path was resolved")

    monkeypatch.setattr(os.path, "realpath", contacted)
    with pytest.raises(PermissionError, match="local fixed NTFS"):
        windows_files.canonical(r"\\server\share\odin-desktop\test")


def test_long_path_drives_count_as_local_and_relative_paths_are_refused():
    assert windows_files._local_drive("\\\\?\\C:\\Users\\x")
    assert not windows_files._local_drive("\\\\server\\share\\x")
    with pytest.raises(ValueError, match="absolute"):
        windows_files.canonical("relative\\odin-desktop")


def test_publish_replaces_flushes_and_leaves_no_temporary(profile_root):
    private_directory(profile_root)
    with held(profile_root) as chain:
        assert publish(chain, "state.json", b"one") is True
        assert publish(chain, "state.json", b"two") is True
        assert read_file(chain, "state.json") == b"two"
    assert sorted(os.listdir(profile_root)) == ["state.json"]
    assert dacl_is_private(security_of(profile_root / "state.json", directory=False))


def test_publish_waits_out_a_reader_without_delete_sharing(profile_root):
    private_directory(profile_root)
    with held(profile_root) as chain:
        publish(chain, "state.json", b"old")
        reader = open(profile_root / "state.json", "rb")  # noqa: SIM115 - held across the replace
        releaser = threading.Timer(0.2, reader.close)
        releaser.start()
        try:
            assert publish(chain, "state.json", b"new") is True
        finally:
            releaser.join()
        assert read_file(chain, "state.json") == b"new"


def test_publish_failure_before_the_rename_keeps_the_old_value(profile_root, monkeypatch):
    private_directory(profile_root)
    with held(profile_root) as chain:
        publish(chain, "state.json", b"old")

        def broken(handle, data):
            raise OSError("disk full")

        monkeypatch.setattr(win32, "write_all", broken)
        with pytest.raises(OSError, match="disk full"):
            publish(chain, "state.json", b"new")
        assert read_file(chain, "state.json") == b"old"
    assert os.listdir(profile_root) == ["state.json"]


def test_publish_failed_final_flush_is_committed_but_unproven(profile_root, monkeypatch):
    private_directory(profile_root)
    calls = []
    real = win32.flush

    def second_fails(handle):
        calls.append(handle)
        if len(calls) == 2:
            raise OSError("flush failed")
        real(handle)

    with held(profile_root) as chain:
        monkeypatch.setattr(win32, "flush", second_fails)
        assert publish(chain, "state.json", b"new") is False
        monkeypatch.setattr(win32, "flush", real)
        assert read_file(chain, "state.json") == b"new"


def test_publish_refuses_to_replace_a_hard_linked_target(profile_root):
    private_directory(profile_root)
    with held(profile_root) as chain:
        publish(chain, "state.json", b"old")
        os.link(profile_root / "state.json", profile_root / "alias.json")
        with pytest.raises(PermissionError):
            open_file(chain, "state.json")


def test_retire_renames_to_a_tombstone_then_flushes(profile_root):
    private_directory(profile_root)
    with held(profile_root) as chain:
        publish(chain, "audit.log.repair-required", b"pending\n")
        tombstone = retire(chain, "audit.log.repair-required")
        assert not (profile_root / "audit.log.repair-required").exists()
        assert tombstones(chain, "audit.log.repair-required") == [tombstone]
        remove(chain, tombstone)
        assert tombstones(chain, "audit.log.repair-required") == []


def test_retire_with_a_failed_flush_leaves_the_tombstone(profile_root, monkeypatch):
    private_directory(profile_root)
    with held(profile_root) as chain:
        publish(chain, "marker", b"x")

        def failing(handle):
            raise OSError("flush failed")

        monkeypatch.setattr(win32, "flush", failing)
        with pytest.raises(OSError, match="flush failed"):
            retire(chain, "marker")
        monkeypatch.undo()
        assert not (profile_root / "marker").exists()
        assert len(tombstones(chain, "marker")) == 1


def test_tombstone_recognition_is_exact(profile_root):
    private_directory(profile_root)
    for name in ("marker.retiring-" + "a" * 31, "marker.retiring-" + "A" * 32,
                 "markerx.retiring-" + "a" * 32, "marker.retiring-" + "a" * 32 + ".tmp"):
        (profile_root / name).write_bytes(b"")
    (profile_root / ("marker.retiring-" + "b" * 32)).write_bytes(b"")
    with held(profile_root) as chain:
        assert tombstones(chain, "marker") == ["marker.retiring-" + "b" * 32]


def test_flush_object_needs_the_file_and_writes_nothing(profile_root):
    private_directory(profile_root)
    with held(profile_root) as chain:
        publish(chain, "history.jsonl", b"line\n")
        flush_object(chain, "history.jsonl")
        assert read_file(chain, "history.jsonl") == b"line\n"
        with pytest.raises(FileNotFoundError):
            flush_object(chain, "missing")


def test_ensure_private_repairs_a_broad_child_acl(profile_root, sddl):
    private_directory(profile_root)
    path = profile_root / "turns.sqlite3"
    path.write_bytes(b"")
    sddl(path, "D:PAI(A;;FA;;;WD)(A;;FA;;;OW)", directory=False)
    assert not dacl_is_private(security_of(path, directory=False))
    with held(profile_root) as chain:
        ensure_private(chain, "turns.sqlite3")
    assert dacl_is_private(security_of(path, directory=False))


def test_partial_failure_releases_every_held_handle(profile_root, monkeypatch):
    private_directory(profile_root / "data")
    opened, closed = [], []
    real_create, real_close = win32.create_file, win32.close

    def counting_create(*args, **kwargs):
        handle = real_create(*args, **kwargs)
        opened.append(handle)
        return handle

    def counting_close(handle):
        closed.append(handle)
        real_close(handle)

    def boom(*args, **kwargs):
        raise OSError("verification failed")

    monkeypatch.setattr(win32, "create_file", counting_create)
    monkeypatch.setattr(win32, "close", counting_close)
    monkeypatch.setattr(windows_files, "_verify_directory", boom)
    with pytest.raises(OSError, match="verification failed"):
        HeldChain(profile_root / "data")
    assert opened and sorted(opened) == sorted(closed)


def test_another_process_cannot_rename_a_held_folder(profile_root):
    target = profile_root / "data"
    private_directory(target)
    script = ("import os, sys\n"
              "try:\n    os.rename(sys.argv[1], sys.argv[2])\n"
              "except PermissionError:\n    sys.exit(3)\n")
    with held(target):
        result = subprocess.run(
            [sys.executable, "-c", script, str(target), str(target.with_name("moved"))],
            timeout=60)
    assert result.returncode == 3
    assert target.exists()


def test_rename_retry_gives_up_after_its_bound(profile_root, monkeypatch):
    private_directory(profile_root)
    attempts = []

    def always_shared(handle, name, *, replace):
        attempts.append(name)
        raise win32.error(win32.ERROR_SHARING_VIOLATION)

    monkeypatch.setattr(win32, "rename_by_handle", always_shared)
    monkeypatch.setattr(windows_files, "_RENAME_RETRY_SECONDS", 0)
    started = time.monotonic()
    with held(profile_root) as chain, pytest.raises(PermissionError):
        publish(chain, "state.json", b"x")
    assert len(attempts) == windows_files._RENAME_RETRIES
    assert time.monotonic() - started < 30
    assert os.listdir(profile_root) == []


def test_a_posted_image_keeps_a_private_copy_and_refuses_a_link(tmp_path):
    """The image and screenshot tools' local copy, as production calls it
    (``services.retain_generated_copy``). Linux's version needs ``os.O_DIRECTORY``,
    which escaped those tools as an AttributeError after their post."""
    from pathlib import Path

    from src.desktop.services import retain_generated_copy

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    saved = Path(retain_generated_copy(str(workspace), "generated-images", "a.png", b"png-a"))
    assert saved == workspace / "generated-images" / "a.png"
    assert saved.read_bytes() == b"png-a"
    assert dacl_is_private(security_of(saved, directory=False))
    assert dacl_is_private(security_of(saved.parent, directory=True))
    again = Path(retain_generated_copy(str(workspace), "generated-images", "b.png", b"png-b"))
    assert (again.read_bytes(), saved.read_bytes()) == (b"png-b", b"png-a")
    with pytest.raises(FileExistsError):  # a taken name is never replaced (Linux: O_EXCL)
        retain_generated_copy(str(workspace), "generated-images", "a.png", b"png-other")
    assert saved.read_bytes() == b"png-a"
    outside = tmp_path / "outside"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(workspace / "screenshots"))
    with pytest.raises(OSError):
        retain_generated_copy(str(workspace), "screenshots", "c.png", b"png-c")
    assert os.listdir(outside) == []


def _around_folder_open(monkeypatch, folder, *, before=None, after=None):
    """Run ``before`` and ``after`` around the copy folder's own open, which the copy makes by name
    under the held workspace (Linux: open with O_NOFOLLOW)."""
    real = windows_files._open_directory

    def opening(path, *args, **kwargs):
        mine = os.path.normcase(str(path)) == os.path.normcase(str(folder))
        if mine and before:
            before()
        handle = real(path, *args, **kwargs)
        if mine and after:
            after()
        return handle

    monkeypatch.setattr(windows_files, "_open_directory", opening)


def test_a_copy_folder_swapped_for_a_junction_before_its_open_is_refused(tmp_path, monkeypatch):
    """A plain copy folder replaced by a junction just before use: the folder is opened as itself, so
    the open meets the junction and refuses it, and nothing lands where the junction points."""
    from src.desktop.services import retain_generated_copy

    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    folder = workspace / "generated-images"
    folder.mkdir(parents=True)
    outside.mkdir()

    def swap():
        folder.rmdir()
        _winapi.CreateJunction(str(outside), str(folder))

    _around_folder_open(monkeypatch, folder, before=swap)
    with pytest.raises(OSError) as refused:
        retain_generated_copy(str(workspace), "generated-images", "a.png", b"png-a")
    assert refused.value.errno == errno.ELOOP
    assert os.listdir(outside) == []


def test_an_open_copy_folder_cant_be_swapped_until_the_copy_is_written(tmp_path, monkeypatch):
    """Once opened, the copy folder is held without delete sharing: renaming it away, to put a
    junction in its place, fails, and the copy lands in the folder that was checked."""
    from src.desktop.services import retain_generated_copy

    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    folder = workspace / "generated-images"
    attempts = []

    def swap():
        try:
            os.rename(folder, workspace / "moved")
        except PermissionError as exc:
            attempts.append(exc.winerror)
        else:
            attempts.append("renamed")
            _winapi.CreateJunction(str(outside), str(folder))

    _around_folder_open(monkeypatch, folder, after=swap)
    retain_generated_copy(str(workspace), "generated-images", "a.png", b"png-a")
    assert attempts == [32]  # ERROR_SHARING_VIOLATION
    assert (folder / "a.png").read_bytes() == b"png-a"
    assert os.listdir(outside) == []
    assert not (workspace / "moved").exists()


@pytest.mark.parametrize("descriptor", [
    "D:P(A;OICI;FA;;;WD)(A;OICI;FA;;;OW)",  # everyone, and inherited by every new file
    "D:P(A;OICI;FA;;;OW)(A;;FR;;;WD)",  # private for new files; everyone on the folder alone
])
def test_an_existing_shared_copy_folder_is_refused(tmp_path, sddl, descriptor):
    """An existing copy folder must be the user's own private folder, wherever the workspace is
    (Linux: st_uid and mode 0700). A broad grant refuses it, inheritable or not; nothing is
    written in it and its DACL is left as it was."""
    from src.desktop.services import retain_generated_copy

    folder = tmp_path / "workspace" / "generated-images"
    folder.mkdir(parents=True)
    sddl(folder, descriptor, directory=True)
    before = security_of(folder, directory=True).aces
    with pytest.raises(PermissionError):
        retain_generated_copy(str(tmp_path / "workspace"), "generated-images", "a.png", b"png-a")
    assert os.listdir(folder) == []
    assert security_of(folder, directory=True).aces == before
