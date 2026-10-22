"""Odin 4.21.0 (PR #672) on macOS: the darwin route of ``_exec_command`` hands a remote command
to the Linux original with the channel flag and every other parameter unchanged.

Remote commands from the Mac go through the byte-pinned ``ssh.py`` (the coordinator, the open
stdin, one dispatch); only this route sits in between.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.desktop.platform import macos_jobs
from src.tools.executor import ToolExecutor


async def test_macos_exec_command_forwards_the_channel_flag_with_every_other_parameter(
        monkeypatch):
    seen = []

    async def linux_original(self, address, command, ssh_user, timeout, on_output,
                             use_workspace, target, use_command_shell, **kwargs):
        seen.append(dict(address=address, command=command, ssh_user=ssh_user, timeout=timeout,
                         on_output=on_output, use_workspace=use_workspace, target=target,
                         use_command_shell=use_command_shell, **kwargs))
        return 0, "ok"

    monkeypatch.setattr(ToolExecutor, "_exec_command",
                        SimpleNamespace(linux_original=linux_original), raising=False)
    target = SimpleNamespace(alias="server")

    async def stream(_line):
        return None

    assert await macos_jobs.exec_command(
        object(), "192.0.2.7", "uptime", "odin", 45, stream, True, target, True,
        max_ssh_attempts=2, ssh_multiplex=False, end_with_channel=True) == (0, "ok")
    assert seen == [{
        "address": "192.0.2.7", "command": "uptime", "ssh_user": "odin", "timeout": 45,
        "on_output": stream, "use_workspace": True, "target": target, "use_command_shell": True,
        "max_ssh_attempts": 2, "ssh_multiplex": False, "end_with_channel": True,
    }]
