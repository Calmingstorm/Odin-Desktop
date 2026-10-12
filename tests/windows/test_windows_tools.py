"""The lifted tool variants keep their Linux originals' checks and outcomes on Windows.

Each variant in ``windows_tools`` is the Linux body with its POSIX steps replaced.
These cases drive the rest of each body (input checks, error branches, remote
paths) through the Windows copy, so what Linux tests on the original holds here.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import json
from types import SimpleNamespace

import pytest

from src.desktop.platform import windows_tools as tools
from src.desktop.platform.windows_jobs import WindowsProcessRegistry
from src.tools.bulkhead import Bulkhead, BulkheadFullError


class Lease:
    def __init__(self, address="127.0.0.1"):
        self.target = SimpleNamespace(address=address, ssh_user="u", alias="host")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


class Full:
    @contextlib.asynccontextmanager
    async def acquire(self):
        raise BulkheadFullError("x", 1, 1)
        yield  # pragma: no cover


# --- read_file ---------------------------------------------------------------------------------


def reader(**fields):
    return SimpleNamespace(config=SimpleNamespace(), **fields)


@pytest.mark.parametrize("inp, refusal", [
    ({}, "Error: 'path' is required for read_file."),
    ({"path": "C:\\x.txt"}, "Error: 'host' is required for read_file."),
    ({"path": "C:\\x.txt", "host": "h", "lines": True}, "'lines' must be a positive integer"),
    ({"path": "C:\\x.txt", "host": "h", "lines": 1001}, "'lines' must not exceed 1000."),
    ({"path": "C:\\x.txt", "host": "h", "start_line": 0}, "'start_line' must be a positive"),
    ({"path": "C:\\x.txt", "host": "h", "start_line": 2**53}, "must not exceed 9007199254740991"),
    ({"path": "C:\\x.txt", "host": "h", "raw": "yes"}, "Error: 'raw' must be a boolean."),
])
async def test_read_file_checks_its_input(inp, refusal):
    assert refusal in await tools.handle_read_file(reader(), inp)


def transported(monkeypatch, text, code=0, budget=11_500):
    import src.tools.output_delivery as delivery

    async def fake(self, alias, command, **kwargs):
        return text, code

    monkeypatch.setattr(tools, "read_on_host", fake)
    monkeypatch.setattr(delivery, "get_delivery_budget", lambda config: budget)


def meta(*fields):
    return "ODIN_READ_FILE_RAW_META_V1\t" + "\t".join(str(field) for field in fields) + "\n"


@pytest.mark.parametrize("text, outcome", [
    ("\nERROR\tseven\n", ("Error: read_file raw transport returned an invalid envelope.", 1)),
    ("\nERROR\t12\n", ("Error: source line 12 exceeds the read_file output budget; "
                      "no lines returned.", 1)),
    ("garbage", ("Error: read_file raw transport returned an invalid envelope.", 1)),
    ("eA==\nODIN_READ_FILE_RAW_META_V1\tbad\n",
     ("Error: read_file raw transport returned an invalid envelope.", 1)),
    ("eA==\n" + meta(1, 200, 1, 1, "-", 5),
     ("Error: read_file raw transport returned an invalid envelope.", 1)),
    (base64.b64encode(b"\xff\xfe").decode() + "\n" + meta(1, 200, 1, 1, "-", 2),
     ("Error: read_file raw mode requires UTF-8 text content.", 1)),
])
async def test_read_file_refuses_a_damaged_raw_transport(monkeypatch, text, outcome):
    transported(monkeypatch, text)
    inp = {"path": "C:\\x.txt", "host": "h", "raw": True}
    assert await tools.handle_read_file(reader(), inp) == outcome


async def test_read_file_frames_an_empty_raw_range_and_bounds_its_envelope(monkeypatch):
    transported(monkeypatch, meta(5, 200, "-", "-", "-", 0))
    text, code = await tools.handle_read_file(reader(), {"path": "C:\\x.txt", "host": "h",
                                                         "raw": True, "start_line": 5})
    assert code == 0 and '"returned_start_line":null' in text and text.endswith(
        "<<<ODIN_READ_FILE_RAW_CONTENT_V1>>>\n<<<ODIN_READ_FILE_RAW_END_V1>>>")
    transported(monkeypatch, "x" * 900, budget=700)
    assert await tools.handle_read_file(reader(), {"path": "C:\\x.txt", "host": "h"}) == (
        "Error: read_file envelope exceeds the delivery budget; no lines returned.", 1)
    transported(monkeypatch, "Error: source line 3 exceeds the read_file output budget; "
                "no lines returned.")
    assert (await tools.handle_read_file(reader(), {"path": "C:\\x.txt", "host": "h"}))[1] == 1


# --- hosts -------------------------------------------------------------------------------------


def test_the_startup_inventory_check_reports_every_issue():
    assert tools.check_host_inventory_compat(SimpleNamespace(hosts={})).passed
    hosts = {
        "9bad": SimpleNamespace(address="192.0.2.1", os="linux", trust_mode="legacy", host_keys=[]),
        "pinned": SimpleNamespace(address="192.0.2.2", os="linux", trust_mode="pinned",
                                  host_keys=[]),
    }
    tools_config = SimpleNamespace(hosts=hosts, default_host="nowhere",
                                   governor=SimpleNamespace(host_overrides={"ghost": {}}))
    result = tools.check_host_inventory_compat(tools_config)
    assert not result.passed and result.metadata == {"issue_count": 4}
    for issue in ("alias '9bad' is not editable",
                  "tools.hosts.pinned has no usable pinned host key",
                  "host_overrides names unknown hosts: ghost",
                  "default_host names unknown host 'nowhere'"):
        assert issue in result.detail


@pytest.mark.parametrize("alias, body, refusal", [
    ("9x", {"address": "192.0.2.1"}, "alias must start with a letter"),
    ("box", {"address": "a/b"}, "not a plain hostname"),
    ("box", {"address": "bad_host!"}, "not a valid hostname"),
    ("box", {"address": "192.0.2.1", "ssh_user": "-u"}, "ssh_user is invalid"),
    ("box", {"address": "192.0.2.1", "port": 0}, "port must be an integer"),
    ("box", {"address": "192.0.2.1", "trust_mode": "magic"}, "trust_mode must be"),
])
def test_host_details_keep_odins_checks(alias, body, refusal):
    from src.tools.hosts.trust import HostTrustError

    with pytest.raises(HostTrustError, match=refusal):
        tools.validate_host_details(alias, body)


@pytest.mark.parametrize("reply, ok, detail", [
    ((0, b"odin-host-test linux\n"), True, "authentication and platform verified"),
    ((255, b""), False, "ssh exit 255"),
    (TimeoutError(), False, "connection test timed out"),
])
async def test_a_remote_host_is_checked_over_ssh(monkeypatch, tmp_path, reply, ok, detail):
    import src.tools.hosts.control as control
    from src.config.schema import ToolHost
    from src.tools.hosts import HostEnrollmentManager, HostRegistry

    host = ToolHost(address="example.invalid", ssh_user="deploy", os="linux",
                    host_id="06eebf65-8f6e-4c36-9acc-ce393fb34642", trust_mode="legacy")
    registry = HostRegistry({"build": host}, trust_dir=tmp_path)
    manager = HostEnrollmentManager(registry)
    candidate = await manager.prepare("build", {**host.model_dump()}, allow_tofu=False,
                                      existing=host)
    sent = []

    async def run_argv(argv, timeout, **kwargs):
        sent.append(argv)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(control, "_run_argv", run_argv)
    tested = await tools.host_test(manager, candidate.token)
    assert (tested.tested, tested.test_result["detail"]) == (ok, detail)
    assert sent[0][0] == "ssh" and sent[0][-2] == "deploy@example.invalid"


# --- run_script --------------------------------------------------------------------------------


def scripter(tmp_path, *, default=None, resolved=("127.0.0.1", "u", "windows"), streamer=None,
             freshness=False):
    fake = SimpleNamespace(
        _current_user_id="owner", output_streamer=streamer, _branch_freshness_enabled=freshness,
        _resolve_default_host=lambda user: default,
        _resolve_host=lambda alias: resolved,
        _govern_command=lambda script, host: (True, "", ""),
        bulkheads={}, config=SimpleNamespace(command_timeout_seconds=60),
        _ensure_local_workspace=lambda: str(tmp_path), _command_shell_mode=lambda: "auto")
    fake._exec_command = functools.partial(tools.exec_command, fake)
    return fake


async def test_run_script_checks_its_input(tmp_path):
    assert await tools.handle_run_script(scripter(tmp_path), {"script": "x"}) == (
        "Error: 'host' is required for run_script.")
    assert await tools.handle_run_script(scripter(tmp_path), {"host": "h"}) == (
        "Error: 'script' is required for run_script.")
    assert await tools.handle_run_script(scripter(tmp_path, resolved=None),
                                         {"host": "h", "script": "x", "interpreter": "python"}) \
        == "Unknown or disallowed host: h"


async def test_run_script_streams_and_notes_a_failing_test_run(tmp_path):
    lines, finished = [], []

    async def on_output(text):
        lines.append(text)

    async def finish():
        finished.append(True)
        raise RuntimeError("the stream's own failure is not the script's")

    streamer = SimpleNamespace(is_enabled=lambda name: True,
                               create_callback=lambda name, channel_id: (None, on_output, finish))
    fake = scripter(tmp_path, streamer=streamer, freshness=True)

    async def annotate(result, host, tool, command):
        return result + "\n[freshness noted]"

    fake._annotate_with_freshness = annotate
    text, code = await tools.handle_run_script(fake, {
        "host": "h", "script": "# pytest\nWrite-Output '1 failed in 0.1s'; exit 1"})
    assert code == 1 and text.startswith("Script failed (exit 1):")
    assert text.endswith("[freshness noted]") and finished == [True]
    assert any("1 failed" in line for line in lines)


# --- background jobs ---------------------------------------------------------------------------


async def test_a_local_start_refuses_what_linux_refuses(tmp_path, monkeypatch):
    from src.tools.workspace import WorkspaceError

    jobs = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="auto")
    assert await jobs.start("192.0.2.1", "Write-Output x") == (
        "Error: remote process start requires a generation-bound host lease.")
    jobs._revoking_aliases["127.0.0.1"] = 1
    assert await jobs.start("127.0.0.1", "Write-Output x") == (
        "Error: host force-revoked; process not started.")
    jobs._revoking_aliases.clear()

    def broken():
        raise WorkspaceError("the workspace is gone")

    unusable = WindowsProcessRegistry(workspace=broken, command_shell="auto")
    assert await unusable.start("127.0.0.1", "Write-Output x") == (
        "Error: cannot start background process — the workspace is gone")

    async def failing(*args, **kwargs):
        raise OSError("spawn refused")

    monkeypatch.setattr(tools, "create_job_shell", failing)
    assert await jobs.start("127.0.0.1", "Write-Output x") == (
        "Failed to start process: spawn refused")

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(tools, "create_job_shell", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await jobs.start("127.0.0.1", "Write-Output x")
    assert jobs._processes == {}


async def test_a_start_that_crosses_a_revoke_is_ended(tmp_path, monkeypatch):
    real = tools.create_job_shell
    jobs = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="auto")

    async def revoked_meanwhile(*args, **kwargs):
        shell = await real(*args, **kwargs)
        jobs._local_revoke_epochs["127.0.0.1"] = 1
        return shell

    monkeypatch.setattr(tools, "create_job_shell", revoked_meanwhile)
    assert await jobs.start("127.0.0.1", "Start-Sleep 60") == (
        "Error: host force-revoked; process terminated.")

    async def unproven(info):
        return False

    jobs._local_revoke_epochs.clear()
    real_terminate = jobs._terminate_bound_host_job
    monkeypatch.setattr(jobs, "_terminate_bound_host_job", unproven)
    reply = await jobs.start("127.0.0.1", "Start-Sleep 60")
    assert reply == "Error: host force-revoked; process outcome unknown outcome_unknown=true."
    unknown = next(info for info in jobs._processes.values() if info.status == "unknown")
    assert unknown.capture_error == "process cleanup could not be confirmed"
    monkeypatch.setattr(jobs, "_terminate_bound_host_job", real_terminate)
    assert await real_terminate(unknown)
    await jobs.shutdown()


async def test_a_lifecycle_that_cannot_start_ends_its_job(tmp_path, monkeypatch):
    import src.async_utils as async_utils

    def broken(coroutine, *args, **kwargs):
        coroutine.close()  # never started, so never awaited
        raise RuntimeError("no lifecycle")

    monkeypatch.setattr(async_utils, "fire_and_forget", broken)
    jobs = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="auto")
    with pytest.raises(RuntimeError, match="no lifecycle"):
        await jobs.start("127.0.0.1", "Start-Sleep 60")
    (info,) = jobs._processes.values()
    assert info.status == "killed" and info.session_confirmed_empty
    await jobs.shutdown()


# --- apply_patch -------------------------------------------------------------------------------


def patcher(monkeypatch, reply):
    async def apply(self, alias, command, **kwargs):
        return reply

    monkeypatch.setattr(tools, "apply_on_host", apply)
    return SimpleNamespace(_resolve_host=lambda alias: ("127.0.0.1", "u", "windows"),
                           _govern_command=lambda command, host: (True, "", ""))


PATCH = "*** Begin Patch\n*** Add File: x.txt\n+x\n*** End Patch\n"


async def test_apply_patch_checks_its_input(monkeypatch):
    fake = patcher(monkeypatch, ("", 0))
    assert await tools.handle_apply_patch(fake, {"root": "C:\\p", "patch_text": PATCH}) == (
        "Error: 'host' is required for apply_patch.", 1)
    assert await tools.handle_apply_patch(fake, {"host": "h", "root": "C:\\p"}) == (
        "Error: 'patch_text' is required for apply_patch.", 1)
    text, code = await tools.handle_apply_patch(fake, {"host": "h", "root": "C:\\p",
                                                       "patch_text": "nonsense"})
    assert code == 1 and text.startswith("Error: invalid apply_patch envelope:")
    fake._resolve_host = lambda alias: None
    assert await tools.handle_apply_patch(fake, {"host": "h", "root": "C:\\p",
                                                 "patch_text": PATCH}) == (
        "Unknown or disallowed host: h", 1)


@pytest.mark.parametrize("reply, outcome", [
    ("Unknown or disallowed host: h", ("Unknown or disallowed host: h", 1)),
    (("not json", 0), ("Error: apply_patch host returned an invalid result envelope.", 1)),
    ((json.dumps({"ok": False, "error": "boom", "rollback_failed": True,
                  "recovery_artifacts": ["C:\\p\\.odin-patch-recovery-1"]}), 0),
     ("Error: apply_patch rollback failed; manual recovery required: boom. Retained private "
      "recovery artifacts: C:\\p\\.odin-patch-recovery-1", 1)),
    (('{"ok":true,"changed":[1]}', 0),
     ("Error: apply_patch host returned an invalid result envelope.", 1)),
])
async def test_apply_patch_reads_the_envelope_as_linux_does(monkeypatch, reply, outcome):
    fake = patcher(monkeypatch, reply)
    assert await tools.handle_apply_patch(fake, {"host": "h", "root": "C:\\p",
                                                 "patch_text": PATCH}) == outcome


async def test_a_large_patch_travels_compressed(monkeypatch):
    commands = []

    async def apply(self, alias, command, **kwargs):
        commands.append(command)
        return '{"ok":true,"changed":["big.txt"]}', 0

    monkeypatch.setattr(tools, "apply_on_host", apply)
    fake = SimpleNamespace(_resolve_host=lambda alias: ("127.0.0.1", "u", "windows"),
                           _govern_command=lambda command, host: (True, "", ""))
    body = "\n".join(f"+line {n:05d} of a long added file" for n in range(1400))
    big = f"*** Begin Patch\n*** Add File: big.txt\n{body}\n*** End Patch\n"
    assert await tools.handle_apply_patch(fake, {"host": "h", "root": "C:\\p",
                                                 "patch_text": big}) == (
        "Applied patch successfully:\n- big.txt", 0)
    assert "zlib.decompress" in commands[0]


# --- exec_command ------------------------------------------------------------------------------


def executor(**fields):
    defaults = dict(
        bulkheads={}, _ensure_local_workspace=lambda: None, _command_shell_mode=lambda: "auto",
        ssh_pool=None,
        config=SimpleNamespace(command_timeout_seconds=60, ssh_key_path="k",
                               ssh_known_hosts_path="kh",
                               ssh_retry=SimpleNamespace(max_retries=0, base_delay=0, max_delay=0)))
    defaults.update(fields)
    return SimpleNamespace(**defaults)


async def test_local_commands_respect_the_subprocess_bulkhead():
    fake = executor(bulkheads={"subprocess": Bulkhead("subprocess", 1)})
    code, output = await tools.exec_command(fake, "127.0.0.1", "Write-Output in-bulkhead",
                                            use_command_shell=True)
    assert code == 0 and output.strip() == "in-bulkhead"
    full = executor(bulkheads={"subprocess": Full()})
    assert await tools.exec_command(full, "127.0.0.1", "Write-Output x") == (
        1, "Error: subprocess bulkhead full — too many concurrent local commands")


async def test_remote_commands_go_over_ssh_with_the_active_lease(monkeypatch):
    import src.tools.executor as executor_module

    calls = []

    async def ssh(**kwargs):
        calls.append(kwargs)
        return 0, "remote ok"

    monkeypatch.setattr(tools, "remote_ssh", ssh)  # Windows' OpenSSH route (phase 3b)
    lease = SimpleNamespace(target=SimpleNamespace(
        address="192.0.2.10", ssh_user="deploy", key_path="lease-key",
        known_hosts_path="lease-kh", port=2222, host_key_alias="odin-x", runtime_key="rk"))
    token = executor_module._host_lease_ctx.set(lease)
    try:
        assert await tools.exec_command(executor(), "192.0.2.10", "uptime", "deploy") == (
            0, "remote ok")
    finally:
        executor_module._host_lease_ctx.reset(token)
    assert calls[0]["port"] == 2222 and calls[0]["ssh_key_path"] == "lease-key"
    assert await tools.exec_command(executor(bulkheads={"ssh": Bulkhead("ssh", 1)}),
                                    "192.0.2.11", "uptime") == (0, "remote ok")
    assert calls[1]["ssh_key_path"] == "k" and calls[1]["port"] == 22
    assert await tools.exec_command(executor(bulkheads={"ssh": Full()}), "192.0.2.11",
                                    "uptime") == (
        1, "Error: SSH bulkhead full — too many concurrent SSH commands")
