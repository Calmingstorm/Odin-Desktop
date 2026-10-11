"""validate_action's probes on this Windows computer (phase 3 plan C8)."""
from __future__ import annotations

import functools
import http.server
import json
import socket
import subprocess
import sys
import threading
import uuid
from types import SimpleNamespace

import pytest

from src.desktop.platform.windows_tools import exec_command, handle_validate_action

PYTHON = getattr(sys, "_base_executable", "") or sys.executable


class Lease:
    def __init__(self, address):
        self.target = SimpleNamespace(address=address, ssh_user="u", alias="host")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


def validator(sent):
    addresses = {"localhost": "127.0.0.1", "server": "192.0.2.10"}
    fake = SimpleNamespace(
        bulkheads={}, ssh_pool=None, _ensure_local_workspace=lambda: None,
        _command_shell_mode=lambda: "auto",
        config=SimpleNamespace(command_timeout_seconds=60),
        _current_user_id="owner", command_governor=None,
        _resolve_default_host=lambda user: "localhost",
        _resolve_host=lambda alias: (addresses[alias], "u", "x") if alias in addresses else None,
        _acquire_host=lambda alias: Lease(addresses[alias]) if alias in addresses else None)
    local = functools.partial(exec_command, fake)

    async def route(address, command, ssh_user, **kwargs):
        if address == "127.0.0.1":
            return await local(address, command, ssh_user, **kwargs)
        sent.append(command)
        return 0, "200"

    fake._exec_command = route
    return fake


async def validate(*checks):
    sent = []
    text = await handle_validate_action(validator(sent), {"checks": list(checks), "format": "json"})
    results = {result["target"]: result for result in json.loads(text)["checks"]}
    return results, sent


@pytest.fixture
def web():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]  # released again: nothing listens there


async def test_http_and_port_probes(web):
    shut = closed_port()
    results, _ = await validate(
        {"type": "http", "target": f"http://127.0.0.1:{web}/"},
        {"type": "http", "target": f"http://127.0.0.1:{shut}/", "timeout_seconds": 5},
        {"type": "port", "target": f"127.0.0.1:{web}"},
        {"type": "port", "target": f"127.0.0.1:{shut}", "timeout_seconds": 2})
    assert results[f"http://127.0.0.1:{web}/"]["status"] == "pass"
    refused = results[f"http://127.0.0.1:{shut}/"]
    assert refused["status"] == "fail" and refused["error"].startswith("curl failed (exit 7)")
    assert results[f"127.0.0.1:{web}"]["status"] == "pass"
    assert results[f"127.0.0.1:{shut}"]["status"] == "fail"


# Longer than a service name may be: the service manager fails it (1783), not "no such service".
REFUSED = "x" * 300


async def test_service_states_read_as_systemctl_words():
    results, _ = await validate(
        {"type": "service", "target": "EventLog"},
        {"type": "service", "target": "Windows Event Log"},  # a display name
        {"type": "service", "target": "OdinNoSuchService"},
        {"type": "service", "target": REFUSED})
    assert results["EventLog"]["status"] == "pass", results["EventLog"]["error"]
    assert results["Windows Event Log"]["status"] == "pass"
    missing = results["OdinNoSuchService"]
    assert missing["status"] == "fail" and missing["error"] == (
        "expected state 'active', got 'inactive'")
    refused = results[REFUSED]
    assert refused["status"] == "fail" and "got 'service check failed: " in refused["error"]


async def test_process_probes_match_command_lines():
    marker = f"odin-marker-{uuid.uuid4().hex}"
    program = f"import time; time.sleep(60)  # {marker}"
    sleeper = subprocess.Popen([PYTHON, "-I", "-S", "-c", program],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        results, _ = await validate(
            {"type": "process", "target": marker},
            {"type": "process", "target": marker.upper()},  # pgrep matches case-sensitively
            {"type": "process", "target": f"absent-{marker}"},
            # services.exe hides its command line even from admins: matched by image name
            {"type": "process", "target": r"^services\.exe$"},
            {"type": "process", "target": "("})
    finally:
        sleeper.kill()
        sleeper.wait(10)
    assert results[marker]["status"] == "pass"
    assert results[marker.upper()]["status"] == "fail"
    assert results[f"absent-{marker}"]["status"] == "fail"
    assert results[r"^services\.exe$"]["status"] == "pass"
    assert results["("]["status"] == "error" and "PROCESS_CHECK_ERROR" in results["("]["error"]


async def test_log_probes_read_the_event_log():
    pattern = f"odin-never-logged-{uuid.uuid4().hex}"
    results, _ = await validate(
        {"type": "log_absent", "target": pattern, "window_seconds": 600},
        {"type": "log_present", "target": f"unit=OdinNoSuchProvider:{pattern}x"},
        {"type": "log_absent", "target": "(", "window_seconds": 60})
    assert results[pattern]["status"] == "pass"
    assert results[f"unit=OdinNoSuchProvider:{pattern}x"]["status"] == "fail"
    invalid = results["("]
    assert invalid["status"] == "error" and "invalid pattern" in invalid["error"]


async def test_commands_run_under_powershell_and_other_hosts_keep_posix_probes():
    results, sent = await validate(
        {"type": "command", "target": "Write-Output hi", "compare": "contains", "expected": "hi"},
        {"type": "http", "target": "http://192.0.2.10/", "host": "server"})
    assert results["Write-Output hi"]["status"] == "pass"
    assert results["http://192.0.2.10/"]["status"] == "pass"
    assert len(sent) == 1 and sent[0].startswith("curl -sS -o /dev/null ")


async def test_the_handlers_own_refusals_and_governor_answers():
    fake = validator([])
    assert (await handle_validate_action(fake, {"checks": []})).startswith(
        "Error: 'checks' must be a non-empty list")

    fake.command_governor = object()  # present: every command check asks it first
    fake._govern_command = lambda command, address: (False, "denied in this test", "")
    blocked, _ = await validate_with(fake, {"type": "command", "target": "Write-Output hi"})
    assert blocked["Write-Output hi"]["status"] == "error"
    assert "governor-blocked: denied in this test" in blocked["Write-Output hi"]["error"]

    def broken(command, address):
        raise ValueError("the governor itself failed")

    fake._govern_command = broken
    raised, _ = await validate_with(fake, {"type": "command", "target": "Write-Output hi"})
    assert "governor check raised ValueError" in raised["Write-Output hi"]["error"]

    fake._govern_command = lambda command, address: (True, "", "")
    allowed, _ = await validate_with(fake, {"type": "command", "target": "Write-Output hi",
                                            "compare": "contains", "expected": "hi"})
    assert allowed["Write-Output hi"]["status"] == "pass"


async def test_a_host_that_resolves_but_cant_be_leased_is_an_error_and_summaries_read():
    fake = validator([])
    fake._resolve_host = lambda alias: ("192.0.2.9", "u", "x")  # known, but its lease is gone
    fake._acquire_host = lambda alias: None
    results, _ = await validate_with(fake, {"type": "http", "target": "http://x/", "host": "gone"})
    assert "unknown host alias: gone" in results["http://x/"]["error"]
    summary = await handle_validate_action(validator([]), {
        "checks": [{"type": "command", "target": "Write-Output hi"}], "bundle_name": "summary"})
    assert "summary" in summary and "pass" in summary.lower()


async def validate_with(fake, *checks):
    text = await handle_validate_action(fake, {"checks": list(checks), "format": "json"})
    return {result["target"]: result for result in json.loads(text)["checks"]}, text
