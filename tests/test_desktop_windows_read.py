"""The Windows local read_file prints what the awk programs print (phase 3 plan C3).

A differential on Linux: the command the unchanged handler builds runs under
/bin/sh with the system awk, and the Python port runs on the same file with the
same budgets. Their outputs and exit codes must be identical.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.platform import windows_read

pytestmark = pytest.mark.skipif(shutil.which("gawk") is None, reason="the reference is gawk")

CORPUS = {
    "empty": b"",
    "one": b"a",
    "one-lf": b"a\n",
    "two": b"a\nb",
    "two-lf": b"a\nb\n",
    "blank-lines": b"\n\n\nx\n\n",
    "crlf": b"first\r\nsecond\r\nthird\r\n",
    "unicode": "h\u00e9llo \u2713\n\U0001f600 smile\nplain\n".encode(),
    "invalid": b"ok\n\xff\xfe broken\n\xe2\x82 cut\nend",
    "nul": b"a\x00b\nc\n",
    "long": b"x" * 5000 + b"\nshort\n" + b"y" * 900 + b"\n",
    "many": b"".join(f"line {n} {'z' * (n % 37)}\n".encode() for n in range(1, 400)),
    "many-unterminated": b"".join(f"row {n}\n".encode() for n in range(1, 60)) + b"tail",
    # Raw mode's one undecidable case at the 700-byte delivery budget (100 raw bytes): a
    # line that fits only without its newline, decided by what follows it.
    "edge-first": b"x" * 100 + b"\nnext\n",
    "edge-first-eof": b"x" * 100,
    "edge-first-lf-eof": b"x" * 100 + b"\n",
    "edge-second": b"a\n" + b"y" * 98 + b"\nz\n",
    "edge-second-lf-eof": b"a\n" + b"y" * 98 + b"\n",
}


def handler(monkeypatch, delivery_budget):
    import src.tools.output_delivery as delivery
    from src.tools.handlers.files_docs import FilesDocsTools

    monkeypatch.setattr(delivery, "get_delivery_budget", lambda config: delivery_budget)
    tool = FilesDocsTools.__new__(FilesDocsTools)
    tool._deps = SimpleNamespace(config=lambda: SimpleNamespace())
    captured = {}

    async def run_on_host(host, command):
        captured["command"] = command
        return "", 0

    tool._run_on_host = run_on_host
    return tool, captured


def awk_output(command: str) -> tuple[int, str]:
    """The handler's command with gawk as its awk (a host's awk may be mawk, which counts bytes)."""
    command = command.replace("LC_ALL=C awk ", "LC_ALL=C gawk ", 1)
    if command.startswith("awk "):
        command = "g" + command
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    done = subprocess.run(["/bin/sh", "-c", command], capture_output=True, env=env, timeout=60)
    return done.returncode, done.stdout.decode("utf-8", errors="replace")


def budgets(delivery_budget):
    numbered = min(10_500, delivery_budget - 256)
    raw = min(8_000, delivery_budget - 600)
    return numbered, raw


@pytest.mark.parametrize("name", sorted(CORPUS))
@pytest.mark.parametrize("delivery_budget", [700, 1_000, 3_000, 11_500])
@pytest.mark.parametrize("raw_mode", [False, True])
def test_the_port_prints_what_awk_prints(tmp_path, monkeypatch, name, delivery_budget, raw_mode):
    path = tmp_path / name
    path.write_bytes(CORPUS[name])
    numbered_budget, raw_budget = budgets(delivery_budget)
    budget = raw_budget if raw_mode else numbered_budget
    for start in (1, 2, 3, 5, 40, 399, 400, 401):
        for count in (1, 2, 7, 200, 1000):
            tool, captured = handler(monkeypatch, delivery_budget)
            asyncio.run(tool._handle_read_file({
                "path": str(path), "host": "localhost", "lines": count, "start_line": start,
                "raw": raw_mode}))
            expected = awk_output(captured["command"])
            actual = windows_read.read_local(
                str(path), start=start, start_label=f"n{start}", count=count, budget=budget,
                raw_mode=raw_mode)
            assert actual == expected, (name, start, count, budget, raw_mode)


def test_a_missing_file_is_an_error_like_a_failed_redirect(tmp_path):
    code, output = windows_read.read_local(
        str(tmp_path / "missing"), start=1, start_label="n1", count=10, budget=100,
        raw_mode=False)
    assert code == 2 and "cannot open" in output


@pytest.mark.parametrize("path, absolute", [
    ("/etc/hosts", True), ("C:\\Users\\x", True), ("c:/x", True), ("\\\\server\\share\\f", True),
    ("relative\\x", False), ("C:relative", False), ("", False),
])
def test_absolute_paths_for_either_host(path, absolute):
    assert windows_read.is_absolute(path) is absolute


def test_the_final_newline_probe(tmp_path):
    for data, expected in ((b"", 0), (b"x", 0), (b"x\n", 1), (b"\n", 1), (b"x\r\n", 1)):
        path = tmp_path / f"f{len(data)}{expected}"
        path.write_bytes(data)
        with open(path, "rb") as stream:
            assert windows_read._final_newline(stream) == expected
            assert stream.tell() == 0  # rewound for the reading that follows
        if data:
            command = f"tail -c 1 < {path} | wc -l"
            assert int(subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                                      text=True).stdout) == expected
    assert os.path.exists(tmp_path)


class _Lease:
    def __init__(self, address):
        self.target = SimpleNamespace(address=address, ssh_user="u")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


def test_read_on_host_reads_this_computer_and_sends_the_command_elsewhere(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"alpha\n")
    sent = []

    async def exec_command(address, command, ssh_user, target=None):
        sent.append(command)
        return 0, "remote text"

    def executor(address, allowed=True):
        return SimpleNamespace(_acquire_host=lambda alias: _Lease(address) if allowed else None,
                               _exec_command=exec_command)

    async def read(fake, target):
        return await windows_read.read_on_host(
            fake, "host", "awk ...", path=str(target), start=1, start_label="n1", count=10,
            budget=1000, raw_mode=False)

    assert asyncio.run(read(executor("127.0.0.1"), path)) == ("1: alpha\n\n[returned 1-1]", 0)
    text, code = asyncio.run(read(executor("localhost"), tmp_path / "missing"))
    assert code == 2 and text.startswith("Command failed (exit 2):\nread_file: cannot open ")
    assert asyncio.run(read(executor("192.0.2.10"), path)) == ("remote text", 0)
    assert sent == ["awk ..."]
    assert asyncio.run(read(executor("127.0.0.1", allowed=False), path)) == (
        "Unknown or disallowed host: host")


VECTORS = Path(__file__).parent / "fixtures" / "read-file-vectors.json"


def test_the_shared_vectors_are_gawks_own(tmp_path, monkeypatch):
    """The Windows tests check the port against these; here each is gawk's output."""
    vectors = json.loads(VECTORS.read_text())
    assert {name: base64.b64decode(data) for name, data in vectors["corpus"].items()} == CORPUS
    for name, data in CORPUS.items():
        (tmp_path / name).write_bytes(data)
    for name, delivery_budget, raw_mode, start, count, code, digest in vectors["cases"]:
        tool, captured = handler(monkeypatch, delivery_budget)
        asyncio.run(tool._handle_read_file({
            "path": str(tmp_path / name), "host": "localhost", "lines": count,
            "start_line": start, "raw": raw_mode}))
        returned, output = awk_output(captured["command"])
        assert (returned, hashlib.sha256(output.encode()).hexdigest()) == (code, digest), name
