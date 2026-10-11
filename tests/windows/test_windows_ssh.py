"""SSH from this Windows computer to Linux hosts (phase 3 plan C6).

The ``live`` cases reach a real Linux host described by ``C:\\odt-runner\\ssh\\target.json``
(the Legion's test container); without it they are skipped, as in CI. The rest drive
the lifted SSH bodies with fakes and Windows' own OpenSSH programs.
"""
from __future__ import annotations

import asyncio
import functools
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.platform import win32
from src.desktop.platform import windows_remote as remote
from src.desktop.platform import windows_ssh as wssh
from src.desktop.platform.windows_tools import exec_command

TARGET = Path(r"C:\odt-runner\ssh\target.json")
live = pytest.mark.skipif(not TARGET.exists(), reason="no SSH test target on this machine")


def private_copy(source: str, folder: Path) -> str:
    """The test key with the ACL Odin Desktop gives its own key."""
    destination = folder / "id_ed25519"
    shutil.copyfile(source, destination)
    wssh.restrict_key(destination)
    return str(destination)


@pytest.fixture
def target(tmp_path):
    spec = json.loads(TARGET.read_text())
    return SimpleNamespace(
        address=spec["address"], ssh_user=spec["user"], port=spec["port"], host_key_alias="",
        key_path=private_copy(spec["key"], tmp_path), known_hosts_path=spec["known_hosts"],
        runtime_key="odt-ssh")


def executor():
    return SimpleNamespace(
        bulkheads={}, ssh_pool=object(), _ensure_local_workspace=lambda: None,
        _command_shell_mode=lambda: "auto",
        config=SimpleNamespace(command_timeout_seconds=60, ssh_key_path="", ssh_known_hosts_path="",
                               ssh_retry=SimpleNamespace(max_retries=1, base_delay=0, max_delay=0)))


def ssh_clients() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ssh.exe", "/NH"], capture_output=True,
                         text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return out.lower().count("ssh.exe")


@live
async def test_a_command_runs_on_the_linux_host(target):
    code, output = await exec_command(executor(), target.address, "uname -s; whoami",
                                      target.ssh_user, target=target)
    assert code == 0, output
    assert output.split() == ["Linux", target.ssh_user]


@live
async def test_a_remote_failure_is_the_commands_own(target):
    code, output = await exec_command(executor(), target.address, "echo err >&2; exit 7",
                                      target.ssh_user, target=target)
    assert (code, output.strip()) == (7, "err")


@live
async def test_a_timeout_ends_the_client(target):
    before = ssh_clients()
    started = time.monotonic()
    code, output = await exec_command(executor(), target.address, "sleep 30", target.ssh_user,
                                      timeout=3, target=target)
    assert (code, output) == (1, "Command timed out after 3 seconds")
    assert time.monotonic() - started < 15
    assert ssh_clients() <= before


@live
async def test_output_streams_line_by_line(target):
    lines = []

    async def collect(text):
        lines.append(text)

    code, output = await exec_command(
        executor(), target.address, "for i in 1 2 3; do echo line $i; sleep 0.2; done",
        target.ssh_user, on_output=collect, target=target)
    assert code == 0 and lines == ["line 1\n", "line 2\n", "line 3\n"]


@live
async def test_a_pinned_host_enrolls_end_to_end(target, tmp_path):
    from src.desktop.platform.windows import windows_profile_paths
    from src.tools.hosts import HostEnrollmentManager, HostRegistry
    from src.tools.hosts.trust import fingerprint_public_key

    paths = windows_profile_paths("default", environ={"LOCALAPPDATA": str(tmp_path)})
    paths.create_private()
    registry = HostRegistry({}, key_path=target.key_path, profile_paths=paths)
    manager = HostEnrollmentManager(registry)
    keys = await manager.scan(target.address, target.port)
    assert keys and all(key.startswith(("ssh-", "ecdsa-")) for key in keys)
    candidate = await manager.prepare("box", {
        "address": target.address, "port": target.port, "ssh_user": target.ssh_user,
        "trust_mode": "pinned", "expected_fingerprints": [fingerprint_public_key(keys[0])]},
        allow_tofu=False)
    tested = await manager.test(candidate.token)
    assert tested.test_result["detail"] == "authentication and platform verified"
    trust = list((paths.data_dir / "host_trust").glob("*.known_hosts"))
    assert len(trust) == 1 and trust[0].read_text().startswith(f"odin-{candidate.host_id} ")


# --- Without a host ----------------------------------------------------------------------------


def test_openssh_programs_are_named_by_their_full_path(monkeypatch, tmp_path):
    assert wssh.openssh("ssh").lower().endswith(r"\system32\openssh\ssh.exe")
    assert wssh.openssh_argv(["ssh-keyscan", "-p", "22", "h"])[1:] == ["-p", "22", "h"]
    assert wssh.openssh_argv(["other", "x"]) == ["other", "x"]
    with pytest.raises(ValueError):
        wssh.openssh("scp")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="OpenSSH Client"):
        wssh.openssh("ssh")


async def test_the_argv_runner_uses_windows_openssh_and_ends_a_late_client():
    code, output = await remote.run_argv(["ssh", "-V"], 15)
    assert code == 0 and b"OpenSSH" in output
    started = time.monotonic()
    with pytest.raises(TimeoutError):  # TEST-NET: never answers
        await remote.run_argv(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30",
                               "odt@192.0.2.1"], 1)
    assert time.monotonic() - started < 10


class FakeProcess:
    def __init__(self, code=0, output=b"", *, hang=False, lines=()):
        self.returncode = None
        self._code, self._output, self._hang = code, output, hang
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data(line)
        if not hang:
            self.stdout.feed_eof()
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(60)
        self.returncode = self._code
        return self._output, b""

    async def wait(self):
        if self._hang and not self.killed:
            await asyncio.sleep(60)
        self.returncode = self._code if not self.killed else 1
        return self.returncode

    def kill(self):
        self.killed = True
        self.stdout.feed_eof()


def spawning(monkeypatch, *processes):
    queue = list(processes)
    argvs = []

    async def spawn(*argv, **kwargs):
        argvs.append((argv, kwargs))
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return argvs


def ssh(**changes):
    values = dict(host="h", command="true", ssh_key_path="k", known_hosts_path="kh", timeout=2,
                  max_retries=2, retry_base_delay=0, retry_max_delay=0)
    values.update(changes)
    return remote.run_ssh_command(**values)


async def test_a_transient_failure_is_retried_once_more(monkeypatch):
    argvs = spawning(monkeypatch, FakeProcess(255, b"ssh: connect: Connection refused\n"),
                     FakeProcess(0, b"ok\n"))
    assert await ssh() == (0, "ok\n")
    argv, kwargs = argvs[0]
    assert argv[0].lower().endswith(r"\openssh\ssh.exe") and argv[-2:] == ("root@h", "true")
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    reset = b"Connection reset\n"
    spawning(monkeypatch, FakeProcess(255, reset), FakeProcess(255, reset))
    assert await ssh() == (255, "Connection reset\n")


async def test_timeouts_cancellation_and_errors_end_the_client(monkeypatch):
    hung = FakeProcess(hang=True)
    spawning(monkeypatch, hung, FakeProcess(hang=True))
    assert await ssh(timeout=0.2) == (1, "Command timed out after 0.2 seconds")
    assert hung.killed
    cancelled = FakeProcess(hang=True)
    spawning(monkeypatch, cancelled)
    task = asyncio.create_task(ssh(max_retries=1))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.killed
    spawning(monkeypatch, OSError("no such program"))
    code, output = await ssh(max_retries=1)
    assert code == 1 and output.startswith("SSH error: ")


async def test_a_pool_is_honoured_when_one_is_given(monkeypatch):
    calls = []
    pool = SimpleNamespace(
        is_connected=lambda *a: False,
        acquire=lambda *a, **k: _done(calls.append("acquire") or True),
        get_ssh_args=lambda *a, **k: ["ssh", "pooled"],
        ensure_master_registered=lambda *a: _done(calls.append("registered")),
        release=lambda *a, **k: None)
    spawning(monkeypatch, FakeProcess(0, b"pooled\n"))
    assert await ssh(pool=pool, max_retries=1) == (0, "pooled\n")
    assert calls == ["acquire", "registered"]


async def _done(value=None):
    return value


async def test_streamed_output_keeps_its_bounds(monkeypatch):
    lines = []

    async def collect(text):
        lines.append(text)

    spawning(monkeypatch, FakeProcess(0, lines=[b"a\nb", b"c\n", b"x" * 20000]))
    code, output = await ssh(on_output=collect, max_retries=1)
    assert code == 0 and lines == ["a\n", "bc\n", "x" * 20000]
    assert output.startswith("a\nbc\nxx")  # the usual bound on the returned text
    stuck = FakeProcess(hang=True, lines=[b"first\n"])
    spawning(monkeypatch, stuck)
    code, output = await ssh(on_output=collect, timeout=0.3, max_retries=1)
    assert code == 1 and stuck.killed

    async def failing(text):
        raise RuntimeError("consumer broke")

    broken = FakeProcess(0, lines=[b"a\n"])
    spawning(monkeypatch, broken)
    code, output = await ssh(on_output=failing, max_retries=1)
    assert code == 1 and broken.killed


def test_host_trust_is_written_through_the_private_store(tmp_path):
    import base64

    from src.desktop.platform.windows import windows_profile_paths
    from src.desktop.platform.windows_files import dacl_is_private
    from src.tools.hosts import HostRegistry

    paths = windows_profile_paths("default", environ={"LOCALAPPDATA": str(tmp_path)})
    paths.create_private()
    registry = HostRegistry({}, profile_paths=paths)
    key = "ssh-ed25519 " + base64.b64encode(b"public").decode()
    written = Path(registry.materialize_trust("id-1", "odin-id-1", "pinned", [key]))
    assert written.parent == paths.data_dir / "host_trust"
    assert written.read_text() == f"odin-id-1 {key}\n"
    assert registry.materialize_trust("id-1", "odin-id-1", "pinned", [key]) == str(written)
    handle = win32.create_file(written, win32.READ_CONTROL, 0x7, win32.OPEN_EXISTING,
                               win32.FILE_FLAG_OPEN_REPARSE_POINT)
    try:
        assert dacl_is_private(win32.object_security(handle))
    finally:
        win32.close(handle)

def test_a_known_hosts_path_with_spaces_stays_one_file():
    expected = 'UserKnownHostsFile="C:/Users/Jo Doe/kh"'
    assert wssh.known_hosts_option("C:\\Users\\Jo Doe\\kh") == expected


def test_a_key_is_left_to_this_user_system_and_administrators(tmp_path):
    from src.desktop.platform.windows_files import user_sid

    key = tmp_path / "key"
    key.write_bytes(b"x")
    wssh.restrict_key(key)
    handle = win32.create_file(key, win32.READ_CONTROL, 0x7, win32.OPEN_EXISTING, 0)
    try:
        security = win32.object_security(handle)
    finally:
        win32.close(handle)
    granted = {ace[3] for ace in security.aces if ace[0] == win32.ACCESS_ALLOWED_ACE_TYPE}
    assert security.protected and granted == {user_sid(), win32.SYSTEM_SID,
                                              win32.ADMINISTRATORS_SID}


def test_the_profile_key_is_one_windows_openssh_accepts(tmp_path):
    from src.desktop.platform.windows import windows_profile_paths
    from src.desktop.platform.windows_desktop import ensure_ssh_key
    from src.tools.hosts.control import public_key_info

    paths = windows_profile_paths("default", environ={"LOCALAPPDATA": str(tmp_path)})
    paths.create_private()
    key = str(paths.secrets_dir / "id_ed25519")
    config = SimpleNamespace(tools=SimpleNamespace(ssh_key_path=key))
    ensure_ssh_key(paths, SimpleNamespace(durability_degraded=False), config)
    info = asyncio.run(public_key_info(key))  # ssh-keygen -y has to read the key
    assert info["public_key"].startswith("ssh-ed25519 ")


RECORDED = (b"[192.0.2.9]:2222 ssh-ed25519 "
            b"AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")


async def test_the_scan_reads_what_ssh_recorded(monkeypatch):
    async def fake_ssh(argv, timeout, **kwargs):
        known = next(arg for arg in argv if arg.startswith("UserKnownHostsFile="))
        if "HostKeyAlgorithms=ssh-ed25519" in argv:
            Path(known.split('"')[1]).write_bytes(RECORDED)
        return 255, b"odin-scan@192.0.2.9: Permission denied (publickey).\r\n"

    monkeypatch.setattr(remote, "run_argv", fake_ssh)
    assert await wssh.scan_host_keys("192.0.2.9", 2222, 5) == (0, RECORDED)
    refused = b"ssh: connect to host 192.0.2.9 port 2222: Connection refused"

    async def nothing(argv, timeout, **kwargs):
        return 255, refused

    monkeypatch.setattr(remote, "run_argv", nothing)
    assert await wssh.scan_host_keys("192.0.2.9", 2222, 5) == (1, refused)


async def test_a_family_that_times_out_keeps_the_keys_already_recorded(monkeypatch):
    async def ed25519_then_timeouts(argv, timeout, **kwargs):
        if "HostKeyAlgorithms=ssh-ed25519" not in argv:
            raise TimeoutError
        known = next(arg for arg in argv if arg.startswith("UserKnownHostsFile="))
        Path(known.split('"')[1]).write_bytes(RECORDED)
        return 255, b"odin-scan@192.0.2.9: Permission denied (publickey).\r\n"

    monkeypatch.setattr(remote, "run_argv", ed25519_then_timeouts)
    assert await wssh.scan_host_keys("192.0.2.9", 2222, 5) == (0, RECORDED)

    async def always_late(argv, timeout, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(remote, "run_argv", always_late)
    code, output = await wssh.scan_host_keys("192.0.2.9", 2222, 5)
    assert code == 1 and output.startswith(b"ssh timed out after 5s")


async def test_cancelling_a_scan_still_ends_it(monkeypatch):
    async def cancelled(argv, timeout, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(remote, "run_argv", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await wssh.scan_host_keys("192.0.2.9", 2222, 5)


async def test_a_certificate_scan_says_when_windows_keyscan_is_at_fault(monkeypatch, tmp_path):
    from src.tools.hosts import HostEnrollmentManager, HostRegistry
    from src.tools.hosts.trust import HostTrustError

    async def broken(argv, timeout, **kwargs):
        return 1, b"choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com\n"

    monkeypatch.setattr(remote, "run_argv", broken)
    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path))
    with pytest.raises(HostTrustError, match="use pinned trust for this host"):
        await manager.scan_ca("192.0.2.9", 22)
    assert wssh.keyscan_hint(b"timeout") == ""


def binary_reader():
    from src.tools.binary_read import read_binary_file  # the PDF and image tools' route

    return read_binary_file


@live
async def test_a_remote_binary_read_uses_windows_openssh(target):
    read = functools.partial(binary_reader(), target.address, ssh_key_path=target.key_path,
                             known_hosts_path=target.known_hosts_path, ssh_user=target.ssh_user,
                             port=target.port)
    data, error = await read("/etc/os-release", max_bytes=1 << 20)
    assert error == "" and b"Debian" in data
    assert await read("/etc/os-release", max_bytes=10) == (
        None, "file is over the 10-byte limit")
    data, error = await read("/odin-test/missing", max_bytes=10)
    assert data is None and "No such file" in error


async def test_a_binary_read_that_never_answers_ends_its_client(tmp_path):
    silent = socket.socket()
    silent.bind(("127.0.0.2", 0))  # accepts, never sends an SSH banner
    silent.listen()
    try:
        before = ssh_clients()
        data, error = await binary_reader()(
            "127.0.0.2", "/x", max_bytes=10, ssh_key_path=str(tmp_path / "none"),
            known_hosts_path=str(tmp_path / "known_hosts"), port=silent.getsockname()[1],
            timeout=2)
        assert data is None and error == "timed out reading /x after 2s"
        assert ssh_clients() <= before
    finally:
        silent.close()


async def test_a_local_binary_read_stays_in_python(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\x00\xffodin")
    assert await binary_reader()("127.0.0.1", str(tmp_path / "blob.bin"), max_bytes=10) == (
        b"\x00\xffodin", "")



# --- Without a live host: the lifted paths CI also runs ----------------------------------------


class SlowExit(FakeProcess):
    """Its output ends, but the client itself doesn't exit until it is ended."""

    def __init__(self, lines=()):
        super().__init__(0, lines=lines)

    async def wait(self):
        if not self.killed:
            await asyncio.sleep(60)
        self.returncode = 1
        return self.returncode


async def test_the_line_reader_on_a_partial_line_a_late_exit_and_cancellation(monkeypatch):
    lines = []

    async def collect(text):
        lines.append(text)

    spawning(monkeypatch, FakeProcess(0, lines=[b"no newline at the end"]))
    assert await ssh(on_output=collect, max_retries=1) == (0, "no newline at the end")
    assert lines == ["no newline at the end"]
    late = SlowExit(lines=[b"done\n"])
    spawning(monkeypatch, late)
    code, output = await ssh(on_output=collect, timeout=0.3, max_retries=1)
    assert code == 1 and "done" in output and late.killed
    stuck = FakeProcess(hang=True, lines=[b"first\n"])
    spawning(monkeypatch, stuck)
    task = asyncio.create_task(ssh(on_output=collect, max_retries=1))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stuck.killed


async def test_a_pooled_timeout_keeps_the_masters_registration(monkeypatch):
    calls = []
    pool = SimpleNamespace(
        is_connected=lambda *a: False,
        acquire=lambda *a, **k: _done(calls.append("acquire") or True),
        get_ssh_args=lambda *a, **k: ["ssh", "pooled"],
        ensure_master_registered=lambda *a: _done(calls.append("registered")),
        release=lambda *a, **k: None)
    spawning(monkeypatch, FakeProcess(hang=True))
    assert await ssh(pool=pool, timeout=0.2, max_retries=1) == (
        1, "Command timed out after 0.2 seconds")
    assert "registered" in calls


async def test_binary_reads_without_a_host(tmp_path, monkeypatch):
    read = binary_reader()
    assert await read("127.0.0.1", str(tmp_path / "x"), max_bytes=-1) == (
        None, "max_bytes must be >= 0")
    data, error = await read("127.0.0.1", str(tmp_path / "missing"), max_bytes=10)
    assert data is None and error.startswith("cannot stat ")
    (tmp_path / "big.bin").write_bytes(b"x" * 11)
    assert await read("127.0.0.1", str(tmp_path / "big.bin"), max_bytes=10) == (
        None, "file is 11 bytes, over the 10-byte limit")
    data, error = await read("127.0.0.1", str(tmp_path), max_bytes=10)  # a folder: unreadable
    assert data is None and error.startswith("cannot read ")
    remote_read = functools.partial(read, "192.0.2.5", "/x", ssh_key_path="k",
                                    known_hosts_path="kh")
    argvs = spawning(monkeypatch, FakeProcess(0, b"\x00bytes"))
    assert await remote_read(max_bytes=10) == (b"\x00bytes", "")
    argv, kwargs = argvs[0]
    assert argv[0].lower().endswith(r"\openssh\ssh.exe") and argv[-1] == "head -c 11 -- /x"
    assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
    spawning(monkeypatch, FakeProcess(0, b"x" * 11))
    assert await remote_read(max_bytes=10) == (None, "file is over the 10-byte limit")
    spawning(monkeypatch, FakeProcess(1, b""))
    assert await remote_read(max_bytes=10) == (None, "remote read failed (exit 1)")
    hung = FakeProcess(hang=True)
    spawning(monkeypatch, hung)
    assert await remote_read(max_bytes=10, timeout=0.2) == (None, "timed out reading /x after 0.2s")
    assert hung.killed
    cancelled = FakeProcess(hang=True)
    spawning(monkeypatch, cancelled)
    task = asyncio.create_task(remote_read(max_bytes=10))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.killed
    spawning(monkeypatch, OSError("no such program"))
    assert await remote_read(max_bytes=10) == (None, "ssh failed: no such program")


async def test_a_host_key_scan_keeps_each_key_once(monkeypatch, tmp_path):
    from src.tools.hosts import HostEnrollmentManager, HostRegistry
    from src.tools.hosts.trust import HostTrustError

    answers = iter([(0, b"# 192.0.2.9:2222 SSH-2.0-OpenSSH\n\n" + RECORDED + RECORDED
                     + b"192.0.2.9 not-a-key AAAA\n"),
                    (1, b"Connection refused"), (0, b"# nothing\n")])

    async def scanned(address, port, timeout):
        return next(answers)

    monkeypatch.setattr(remote, "scan_host_keys", scanned)
    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path))
    assert await manager.scan("192.0.2.9", 2222) == (b" ".join(RECORDED.split()[1:3]).decode(),)
    with pytest.raises(HostTrustError, match="host-key scan failed"):
        await manager.scan("192.0.2.9", 2222)
    with pytest.raises(HostTrustError, match="no supported public keys"):
        await manager.scan("192.0.2.9", 2222)


async def test_a_certificate_scan_returns_its_signing_authority(monkeypatch, tmp_path):
    from src.tools.hosts import HostEnrollmentManager, HostRegistry
    from src.tools.hosts.trust import HostTrustError

    def keygen(*args):
        subprocess.run([wssh.openssh("ssh-keygen"), *args], check=True, capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)

    keygen("-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "ca"))
    keygen("-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "host"))
    keygen("-q", "-s", str(tmp_path / "ca"), "-I", "odin-test", "-h", "-n", "192.0.2.9",
           str(tmp_path / "host.pub"))
    certificate = (tmp_path / "host-cert.pub").read_text().split()
    line = f"192.0.2.9 {certificate[0]} {certificate[1]}\n".encode()
    answers = iter([(0, b"# 192.0.2.9:22 SSH-2.0-OpenSSH\n\n" + line + line), (0, b"# none\n")])

    async def scanned(argv, timeout, **kwargs):
        return next(answers)

    monkeypatch.setattr(remote, "run_argv", scanned)
    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path / "trust"))
    authority = " ".join((tmp_path / "ca.pub").read_text().split()[:2])
    assert await manager.scan_ca("192.0.2.9", 22) == (authority,)
    with pytest.raises(HostTrustError, match="no supported host certificates"):
        await manager.scan_ca("192.0.2.9", 22)
