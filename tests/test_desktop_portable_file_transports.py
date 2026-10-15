"""Odin 4.15 (#655): read_file's raw transport and both apply_patch transports write
``chmod -- 600 FILES``, which GNU and BSD chmod read the same way.

Odin's own cases, run on Desktop: the two frozen 4.13 cases that asserted the old order (the
mixed original-cases group deselects exactly those two) in their 4.15 form, and Odin 4.15's
real-transport cases, whose chmod accepts only the portable order.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.schema import ToolHost, ToolsConfig
from src.tools.handlers.files_docs import FilesDocsTools
from tests.desktop_adapters.tools_cases import ToolExecutor, owner_fixture


@pytest.fixture(autouse=True)
def desktop_tool_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("desktop-owner")):
        yield


def _tools(run_ret="file contents", resolve=("1.2.3.4", "root", "linux")):
    from src.tools.hosts import HostRegistry

    t = FilesDocsTools.__new__(FilesDocsTools)
    t._run_on_host = AsyncMock(return_value=run_ret)
    t._govern_command = MagicMock(return_value=(True, "", None))
    t._resolve_host = lambda host: resolve
    t._acquire_host = lambda host: HostRegistry.unmanaged_lease(host, resolve)
    t._exec_command = AsyncMock(return_value=(0, ""))
    t._deps = SimpleNamespace(
        config=lambda: SimpleNamespace(ssh_key_path="/dev/null", ssh_known_hosts_path="/dev/null")
    )
    return t


class TestReadFile:
    async def test_defaults_and_requested_range_reach_source_bounded_command(self):
        t = _tools()
        assert await t._handle_read_file({"path": "/etc/x", "host": "h"}) == "file contents"
        command = t._run_on_host.call_args.args[1]
        assert "-v start=1" in command
        assert "-v start_label=n1" in command
        assert "-v count=200" in command
        assert "-v budget=10500" in command
        assert "returned %.0f-%.0f, continue at start_line=%.0f" in command
        assert "ODIN_READ_FILE_RAW_CONTENT_V1" not in command

        await t._handle_read_file(
            {"path": "/tmp/name with spaces", "host": "h", "start_line": 41, "lines": 17}
        )
        command = t._run_on_host.call_args.args[1]
        assert "-v start=41" in command
        assert "-v start_label=n41" in command
        assert "-v count=17" in command
        assert "< '/tmp/name with spaces'" in command

        await t._handle_read_file({"path": "/tmp/name with spaces", "host": "h", "raw": True})
        command = t._run_on_host.call_args.args[1]
        assert "LC_ALL=C awk" in command
        assert "ODIN_READ_FILE_RAW_META_V1" in command
        assert "base64 <" in command
        assert "tr -d" in command
        assert command.count("$(mktemp)") == 3
        assert 'chmod -- 600 "$metadata" "$body" "$encoded"' in command
        assert "$metadata.body" not in command
        assert "$metadata.encoded" not in command
        assert "-v count=200" in command
        assert "< '/tmp/name with spaces'" in command


class TestApplyPatchHandlerTransport:
    async def test_patch_payload_is_base64_transport_and_private(self):
        t = _tools(run_ret=(' {"ok":true,"changed":["a.txt"]} ', 0))
        secret_line = "payload-never-literal-in-shell"
        patch = f"*** Begin Patch\n*** Add File: a.txt\n+{secret_line}\n*** End Patch\n"
        result = await t._handle_apply_patch({"host": "h", "root": "/repo", "patch_text": patch})
        assert result[1] == 0
        command = t._run_on_host.call_args.args[1]
        assert secret_line not in command
        assert command.count("$(mktemp)") == 2
        assert 'chmod -- 600 "$runner" "$plan"' in command
        assert "base64 -d" in command
        assert 'python3 "$runner" /repo < "$plan"' in command


def _bsd_chmod(directory):
    """A chmod that accepts only the order BSD chmod reads, then runs the real one."""
    shim = directory / "chmod"
    shim.write_text(
        "#!/bin/sh\n"
        '[ "$1" = -- ] && [ "$2" = 600 ] || exit 64\n'
        'exec /bin/chmod "$@"\n'
    )
    shim.chmod(0o755)
    return directory


@pytest.mark.parametrize("large", [False, True])
async def test_transport_with_bsd_chmod_contract(tmp_path, monkeypatch, large):
    monkeypatch.setenv("PATH", f"{_bsd_chmod(tmp_path)}:{os.environ['PATH']}")
    root = tmp_path / "root"
    root.mkdir()
    content = "portable λ " * 3000 if large else "portable λ"
    executor = ToolExecutor(config=ToolsConfig(hosts={"local": ToolHost(
        address="127.0.0.1", ssh_user="root")}))
    patch = f"*** Begin Patch\n*** Add File: added.txt\n+{content}\n*** End Patch\n"
    result = await executor.execute(
        "apply_patch", dict(host="local", root=str(root), patch_text=patch))
    assert result.ok, result.output
    assert (root / "added.txt").read_text() == content + "\n"


async def test_raw_mode_bsd_chmod_ordering(tmp_path, monkeypatch):
    target = tmp_path / "raw.txt"
    target.write_bytes(b"portable raw bytes\r\n")
    monkeypatch.setenv("PATH", f"{_bsd_chmod(tmp_path)}:{os.environ['PATH']}")
    executor = ToolExecutor(config=ToolsConfig(hosts={"localhost": ToolHost(
        address="127.0.0.1")}))
    result = await executor.execute(
        "read_file", {"host": "localhost", "path": str(target), "raw": True})
    assert result.ok, result.output
    header, framed = result.output[len("<<<ODIN_READ_FILE_RAW_V1 "):].split(
        ">>>\n<<<ODIN_READ_FILE_RAW_CONTENT_V1>>>\n", 1)
    encoded = framed.encode("utf-8")
    size = json.loads(header)["content_bytes"]
    assert encoded[size:] == b"<<<ODIN_READ_FILE_RAW_END_V1>>>"
    assert encoded[:size] == target.read_bytes()
