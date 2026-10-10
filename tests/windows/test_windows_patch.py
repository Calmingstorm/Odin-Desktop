"""apply_patch on this Windows computer: Odin's transaction over held handles (phase 3 plan C4)."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from src.desktop.platform.windows_tools import handle_apply_patch


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
