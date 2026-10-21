"""A local Windows read of a directory, or of a link to one, prints Odin's directory guard.

Since Odin 4.20.0 the read_file command refuses a directory before awk runs. A local read on
Windows never runs that command: the Python port opens the path itself, and Windows can't open
a folder, so the read failed as a permission problem ("cannot open ...: Permission denied",
exit 2) and the model was offered sudo. Found in the 1.4.0 Legion battery. A differential on
Linux: the command the handler builds runs under /bin/sh, the port runs on the same path, and
Windows' refusal to open a folder is reproduced where the port opens files.
"""
from __future__ import annotations

import asyncio
import builtins
import errno
import os
import subprocess
from types import SimpleNamespace

import pytest

from src.desktop.platform import windows_read


def _command(monkeypatch, path, raw_mode: bool) -> str:
    """The command Odin's handler builds for ``path``."""
    import src.tools.output_delivery as delivery
    from src.tools.handlers.files_docs import FilesDocsTools

    monkeypatch.setattr(delivery, "get_delivery_budget", lambda config: 11_500)
    tool = FilesDocsTools.__new__(FilesDocsTools)
    tool._deps = SimpleNamespace(config=lambda: SimpleNamespace())
    sent = []

    async def run_on_host(_host, command):
        sent.append(command)
        return "", 0

    tool._run_on_host = run_on_host
    asyncio.run(tool._handle_read_file({"path": str(path), "host": "localhost",
                                        "raw": raw_mode}))
    return sent[0]


def _read(path, raw_mode):
    return windows_read.read_local(str(path), start=1, start_label="n1", count=200,
                                   budget=10_000, raw_mode=raw_mode)


@pytest.fixture
def folder(tmp_path):
    folder = tmp_path / "a folder's name"  # printed as given, never quoted
    folder.mkdir()
    (folder / "inside.txt").write_bytes(b"inside\n")
    return folder


def _refusing_folders(path, *args, **kwargs):
    """Opening as Windows does: a folder can't be opened, and says so as a permission error."""
    if os.path.isdir(path):
        raise PermissionError(errno.EACCES, "Permission denied", path)
    return builtins.open(path, *args, **kwargs)


@pytest.mark.parametrize("raw_mode", [False, True], ids=["numbered", "raw"])
@pytest.mark.parametrize("link", [False, True], ids=["directory", "link"])
@pytest.mark.parametrize("opening", ["posix", "windows"])
def test_the_port_prints_what_the_directory_guard_prints(tmp_path, monkeypatch, folder,
                                                         raw_mode, link, opening):
    path = folder
    if link:
        path = tmp_path / "linked"
        path.symlink_to(folder, target_is_directory=True)
    done = subprocess.run(["/bin/sh", "-c", _command(monkeypatch, path, raw_mode)],
                          capture_output=True, timeout=60)
    guard = (done.returncode, done.stdout.decode("utf-8"))
    assert guard == (1, f"Error: {path} is a directory, not a file.\n")
    if opening == "windows":
        monkeypatch.setattr(windows_read, "open", _refusing_folders, raising=False)

    assert _read(path, raw_mode) == guard


def test_files_and_real_permission_problems_keep_their_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(windows_read, "open", _refusing_folders, raising=False)
    readable = tmp_path / "notes.txt"
    readable.write_bytes(b"alpha\n")
    assert _read(readable, False) == (0, "1: alpha\n\n[returned 1-1]")

    def locked(path, *args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", path)

    monkeypatch.setattr(windows_read, "open", locked, raising=False)
    assert _read(readable, False) == (
        2, f"read_file: cannot open {readable}: Permission denied\n")


class _Lease:
    def __init__(self, address):
        self.target = SimpleNamespace(address=address, ssh_user="u")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


@pytest.mark.parametrize("raw_mode", [False, True], ids=["numbered", "raw"])
def test_the_model_sees_a_failed_command_naming_the_directory(monkeypatch, folder, raw_mode):
    """What the handler is given for a local directory: Odin's failed command, not a refusal
    to open that earns a permission hint."""
    monkeypatch.setattr(windows_read, "open", _refusing_folders, raising=False)
    executor = SimpleNamespace(_acquire_host=lambda alias: _Lease("127.0.0.1"))

    result = asyncio.run(windows_read.read_on_host(
        executor, "localhost", "unused", path=str(folder), start=1, start_label="n1", count=200,
        budget=10_000, raw_mode=raw_mode))

    assert result == (
        f"Command failed (exit 1):\nError: {folder} is a directory, not a file.\n", 1)
    assert "Permission denied" not in result[0]
