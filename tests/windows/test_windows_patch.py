"""apply_patch on this Windows computer: Odin's transaction over held handles (phase 3 plan C4)."""
from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from src.desktop.platform.windows_files import dacl_is_private
from src.desktop.platform.windows_tools import handle_apply_patch
from tests.windows.test_windows_adversarial import security_of


class Lease:
    def __init__(self, address):
        self.target = SimpleNamespace(address=address, ssh_user="u")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


def tool(address="127.0.0.1", allowed=True):
    sent = []

    async def remote(address, command, ssh_user, target=None):
        sent.append(command)
        return 0, '{"ok":true,"changed":["remote"]}'

    fake = SimpleNamespace(
        config=SimpleNamespace(command_timeout_seconds=60),
        _resolve_host=lambda alias: (address, "u", "windows"),
        _acquire_host=lambda alias: Lease(address),
        _govern_command=lambda command, host: (allowed, "Error: refused by the governor", ""),
        _exec_command=remote)
    return fake, sent


def patch(*body: str) -> str:
    return "\n".join(["*** Begin Patch", *body, "*** End Patch"]) + "\n"


async def apply(root, text, **fake_options):
    fake, sent = tool(**fake_options)
    result = await handle_apply_patch(fake, {"host": "localhost", "root": str(root),
                                             "patch_text": text})
    return result, sent


async def test_add_update_move_and_delete_in_one_transaction(tmp_path):
    (tmp_path / "keep.txt").write_bytes(b"alpha\nbeta\n")
    (tmp_path / "old.txt").write_bytes(b"one\ntwo\n")
    (tmp_path / "gone.txt").write_bytes(b"bye\n")
    (text, code), _ = await apply(tmp_path, patch(
        "*** Add File: deep/er/new.txt", "+héllo ✓",
        "*** Update File: keep.txt", "@@", " alpha", "-beta", "+gamma",
        "*** Update File: old.txt", "*** Move to: moved/new-name.txt", "@@", " one", "-two",
        "+three",
        "*** Delete File: gone.txt"))
    assert code == 0, text
    assert (tmp_path / "deep" / "er" / "new.txt").read_bytes() == "héllo ✓\n".encode()
    assert (tmp_path / "keep.txt").read_bytes() == b"alpha\ngamma\n"
    assert (tmp_path / "moved" / "new-name.txt").read_bytes() == b"one\nthree\n"
    assert not (tmp_path / "old.txt").exists() and not (tmp_path / "gone.txt").exists()
    leftovers = [p.name for p in tmp_path.rglob(".odin-patch-*")]
    assert leftovers == []


async def test_a_failing_operation_changes_nothing(tmp_path):
    (tmp_path / "keep.txt").write_bytes(b"alpha\n")
    (text, code), _ = await apply(tmp_path, patch(
        "*** Add File: fresh/new.txt", "+x",
        "*** Update File: keep.txt", "@@", "-alpha", "+changed",
        "*** Update File: missing.txt", "@@", "-a", "+b"))
    assert code == 1 and "without changing the final file set" in text
    assert (tmp_path / "keep.txt").read_bytes() == b"alpha\n"
    assert not (tmp_path / "fresh").exists()


async def test_a_commit_that_fails_midway_rolls_back(tmp_path):
    (tmp_path / "keep.txt").write_bytes(b"alpha\n")
    (tmp_path / "locked.txt").write_bytes(b"in use\n")
    with open(tmp_path / "locked.txt", "rb"):  # held without delete sharing, as editors do
        (text, code), _ = await apply(tmp_path, patch(
            "*** Update File: keep.txt", "@@", "-alpha", "+changed",
            "*** Delete File: locked.txt"))
    # keep.txt was published first; the second rename hit the editor's handle and the
    # transaction put keep.txt back.
    assert code == 1 and text.startswith("Error: apply_patch failed without changing")
    assert "WinError 32" in text  # the sharing violation, in the commit phase
    assert (tmp_path / "keep.txt").read_bytes() == b"alpha\n"
    assert (tmp_path / "locked.txt").read_bytes() == b"in use\n"
    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt", "locked.txt"]


def junction(link, target):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True,
                   capture_output=True)


async def test_links_are_refused_at_the_root_and_below_it(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "f.txt").write_bytes(b"a\n")
    junction(tmp_path / "root-link", real)
    (text, code), _ = await apply(tmp_path / "root-link", patch("*** Delete File: f.txt"))
    assert code == 1 and "root must be an existing non-symlink directory" in text
    project = tmp_path / "project"
    project.mkdir()
    junction(project / "sub", real)
    (text, code), _ = await apply(project, patch("*** Delete File: sub/f.txt"))
    assert code == 1 and "symlink" in text
    assert (real / "f.txt").exists()


@pytest.mark.parametrize("name", ["data.txt:hidden", "CON", "trailing.", "aux.txt"])
async def test_names_windows_would_reinterpret_are_refused(tmp_path, name):
    (text, code), _ = await apply(tmp_path, patch(f"*** Add File: {name}", "+x"))
    assert code == 1 and "can't be used as written on Windows" in text
    assert list(tmp_path.iterdir()) == []


async def test_roots_are_absolute_local_paths(tmp_path):
    fake, _ = tool()
    assert await handle_apply_patch(fake, {"host": "localhost", "root": "relative",
                                           "patch_text": patch("*** Delete File: x")}) == (
        "Error: 'root' must be an absolute path for apply_patch.", 1)
    (text, code), _ = await apply("/home/user/project", patch("*** Delete File: x"))
    assert code == 1 and "root must be an absolute path" in text


async def test_the_governor_and_a_remote_host_keep_their_paths(tmp_path):
    (text, code), _ = await apply(tmp_path, patch("*** Add File: x.txt", "+x"), allowed=False)
    assert (text, code) == ("Error: refused by the governor", 1)
    fake, sent = tool(address="192.0.2.10")
    result = await handle_apply_patch(fake, {"host": "server", "root": "/srv/app",
                                             "patch_text": patch("*** Add File: x.txt", "+x")})
    assert result == ("Applied patch successfully:\n- remote", 0)
    assert sent and sent[0].startswith("runner=$(mktemp)")


# --- Privacy, rollback and the root, in this process (Odin's 3a review, B1-B4) ---------------

EVERYONE = "S-1-1-0"
INHERITED = 0x10  # INHERITED_ACE


def shared(folder):
    """A folder whose new entries inherit read access for everyone."""
    folder.mkdir()
    subprocess.run(["icacls", str(folder), "/grant", f"*{EVERYONE}:(OI)(CI)R"], check=True,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return folder


def acl(path, *, directory=False):
    found = security_of(path, directory=directory)
    return found.protected, sorted(found.aces, key=repr)


@pytest.fixture
def transaction(monkeypatch):
    """apply_patch in this process with the Windows primitives the child installs."""
    from src.desktop.platform import windows_dirfd
    from src.tools import apply_patch

    shim = windows_dirfd.WindowsOs()
    monkeypatch.setattr(apply_patch, "os", shim)
    monkeypatch.setattr(apply_patch._DirectoryRegistry, "__init__",
                        windows_dirfd.directory_registry_init)
    monkeypatch.setattr(apply_patch._DirectoryRegistry, "display",
                        windows_dirfd.directory_registry_display)

    def run(root, text, rename=windows_dirfd.rename_noreplace):
        return apply_patch.apply_plan(str(root), apply_patch.parse_patch(text),
                                      rename_noreplace=rename)

    return SimpleNamespace(shim=shim, run=run, apply_patch=apply_patch)


def test_stages_are_private_as_they_are_created(tmp_path, transaction):
    root = shared(tmp_path / "shared")
    (root / "keep.txt").write_bytes(b"alpha\n")
    created = []
    real_open = transaction.shim.open

    def watched_open(path, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if dir_fd is not None and flags & transaction.shim.O_CREAT:  # before any byte or fchmod
            created.append(dacl_is_private(security_of(transaction.shim.folder(dir_fd) / path)))
        return fd

    transaction.shim.open = watched_open
    transaction.run(root, patch("*** Add File: new.txt", "+x",
                                "*** Update File: keep.txt", "@@", "-alpha", "+beta"))
    assert created == [True, True]


def test_the_original_is_private_before_it_moves_to_recovery(tmp_path, transaction):
    from src.desktop.platform import windows_dirfd

    root = shared(tmp_path / "shared")
    (root / "keep.txt").write_bytes(b"alpha\n")
    seen = []

    def rename(source, destination, *, src_dir_fd, dst_dir_fd):
        if destination.startswith(".odin-patch-recovery-"):
            seen.append(dacl_is_private(security_of(transaction.shim.folder(src_dir_fd) / source)))
        windows_dirfd.rename_noreplace(source, destination, src_dir_fd=src_dir_fd,
                                       dst_dir_fd=dst_dir_fd)

    transaction.run(root, patch("*** Update File: keep.txt", "@@", "-alpha", "+beta"), rename)
    assert seen == [True]


def test_new_and_changed_files_take_the_folders_acl(tmp_path, transaction):
    root = shared(tmp_path / "shared")
    (root / "keep.txt").write_bytes(b"alpha\n")
    transaction.run(root, patch("*** Add File: deep/new.txt", "+x",
                                "*** Update File: keep.txt", "@@", "-alpha", "+beta"))
    for path, directory in ((root / "deep", True), (root / "deep" / "new.txt", False),
                            (root / "keep.txt", False)):
        protected, aces = acl(path, directory=directory)
        assert not protected and aces and all(flags & INHERITED for _, flags, _, _ in aces), path
        assert any(sid == EVERYONE for *_, sid in aces), path


async def test_rollback_gives_the_original_its_own_acl_back(tmp_path):
    root = shared(tmp_path / "shared")
    (root / "keep.txt").write_bytes(b"alpha\n")
    (root / "locked.txt").write_bytes(b"in use\n")
    subprocess.run(["icacls", str(root / "keep.txt"), "/grant", "*S-1-5-32-545:(M)"],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    before = acl(root / "keep.txt")
    with open(root / "locked.txt", "rb"):  # the second rename fails: keep.txt is rolled back
        (text, code), _ = await apply(root, patch(
            "*** Update File: keep.txt", "@@", "-alpha", "+changed",
            "*** Delete File: locked.txt"))
    assert code == 1 and "without changing" in text
    assert (root / "keep.txt").read_bytes() == b"alpha\n"
    assert acl(root / "keep.txt") == before


def test_a_failed_privacy_repair_is_reported_with_the_rollback(tmp_path, transaction,
                                                               monkeypatch):
    from src.desktop.platform import windows_dirfd, windows_patch

    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"original\n")
    real_private = windows_dirfd.win32.set_private_dacl
    real_rename = windows_dirfd.rename_noreplace
    state = {"rollback": False}

    def private(handle):
        if state["rollback"]:  # the retained artifact's repair is refused
            raise PermissionError(5, "Access is denied")
        real_private(handle)

    def rename(source, destination, *, src_dir_fd, dst_dir_fd):
        if source.startswith(".odin-patch-stage-"):  # publication fails ...
            state["rollback"] = True
            raise OSError(5, "publication refused")
        if source.startswith(".odin-patch-recovery-"):  # ... and so does restoring the original
            raise OSError(5, "restoration refused")
        real_rename(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(windows_dirfd.win32, "set_private_dacl", private)
    plan = patch("*** Update File: a.txt", "@@", "-original", "+changed")
    monkeypatch.setattr(windows_dirfd, "rename_noreplace", rename)
    result = windows_patch.envelope(transaction.apply_patch, transaction.shim, str(root),
                                    json.dumps(transaction.apply_patch.parse_patch(plan)))
    assert result["ok"] is False and result["rollback_failed"] is True
    failures = " ".join(result["rollback_failures"])
    assert "restoration refused" in failures and "could not be made private" in failures
    (recovery,) = [path for path in result["recovery_artifacts"] if ".odin-patch-recovery-" in path]
    assert not (root / "a.txt").exists()
    assert (root / recovery.rsplit("\\", 1)[1]).read_bytes() == b"original\n"


def test_the_admitted_root_cant_be_swapped_while_it_resolves(tmp_path, transaction,
                                                             monkeypatch):
    from src.desktop.platform import windows_dirfd

    root = tmp_path / "root"
    root.mkdir()
    attempts = []
    real_canonical = windows_dirfd.canonical

    def swapping(path):
        try:  # someone tries to move the admitted folder aside before it resolves
            os.rename(root, tmp_path / "aside")
            attempts.append("moved")
        except PermissionError:
            attempts.append("refused")
        return real_canonical(path)

    monkeypatch.setattr(windows_dirfd, "canonical", swapping)
    assert transaction.run(root, patch("*** Add File: new.txt", "+x")) == ["new.txt"]
    assert attempts == ["refused"] and (root / "new.txt").exists()


def test_a_root_that_resolves_to_another_folder_is_refused(tmp_path, transaction, monkeypatch):
    from src.desktop.platform import windows_dirfd

    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    monkeypatch.setattr(windows_dirfd, "canonical", lambda path: other)
    with pytest.raises(transaction.apply_patch.PatchError, match="root changed while"):
        transaction.run(root, patch("*** Add File: new.txt", "+x"))
    assert list(other.iterdir()) == [] and list(root.iterdir()) == []


async def test_a_failure_while_the_child_runs_ends_it(tmp_path, monkeypatch):
    from src.desktop.platform import windows_exec, windows_patch
    from tests.windows.test_windows_exec import PYTHON, alive

    real_spawn = windows_exec.spawn
    started = []

    async def spawn(argv, **kwargs):  # a child that would keep going, whose pipe then fails
        running = await real_spawn([PYTHON, "-I", "-S", "-c", "import time; time.sleep(60)"],
                                   **kwargs)
        started.append(running.pid)

        async def broken(*args):
            raise OSError(232, "The pipe is being closed")

        running.process.communicate = broken
        return running

    monkeypatch.setattr(windows_exec, "spawn", spawn)
    code, text = await windows_patch.run_patch(str(tmp_path), "{}", timeout=30)
    assert code == 1 and "its outcome is unknown" in text and "pipe" in text.lower()
    assert not alive(started[0])
