"""SQLite through the held directory on macOS, without procfs."""
from __future__ import annotations

import fcntl
import os

import pytest

from src.desktop.platform.macos_storage import anchored_database_path


def test_the_path_comes_from_the_held_directory(tmp_path):
    (tmp_path / "journal.sqlite").write_bytes(b"")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert anchored_database_path(fd, "journal.sqlite") == os.path.join(
            os.path.realpath(tmp_path), "journal.sqlite")
    finally:
        os.close(fd)


def test_a_different_file_at_the_path_is_refused(tmp_path, monkeypatch):
    held, other = tmp_path / "held", tmp_path / "other"
    held.mkdir()
    other.mkdir()
    (held / "journal.sqlite").write_bytes(b"held")
    (other / "journal.sqlite").write_bytes(b"other")
    fd = os.open(held, os.O_RDONLY | os.O_DIRECTORY)
    real = fcntl.fcntl

    def elsewhere(descriptor, command, argument=0):
        if command == fcntl.F_GETPATH:
            return os.fsencode(os.path.realpath(other)) + b"\0"
        return real(descriptor, command, argument)

    monkeypatch.setattr(fcntl, "fcntl", elsewhere)
    try:
        with pytest.raises(OSError, match="changed"):
            anchored_database_path(fd, "journal.sqlite")
    finally:
        os.close(fd)


def test_the_command_journal_opens_and_reopens(tmp_path):
    from src.desktop.commands import JournalStore

    path = tmp_path / "data" / "commands.sqlite"
    store = JournalStore(path, "test")
    store.close()
    again = JournalStore(path, "test")
    again.close()
    assert path.exists()
