"""Core selection and entry composition without live state or subprocess input."""

import json
import os
from pathlib import Path

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths


def test_app_roots_follow_explicit_paths_and_xdg_cache(tmp_path):
    token = tmp_path / "config" / "ipc.token"
    data = tmp_path / "data"
    paths = ProfilePaths.from_app("work", token_file=token, data_dir=data,
                                  environ={}, home=tmp_path)
    assert paths.config_dir == token.parent
    assert paths.data_dir == data
    assert paths.cache_dir == tmp_path / ".cache/odin-desktop/work"
    assert paths.secrets_dir == data / "secrets"
    assert not data.exists()


@pytest.mark.parametrize("token,data", [
    ("relative/ipc.token", "/tmp/profile-data"),
    ("/tmp/config/ipc.token", "relative-data"),
    ("/tmp/config/ipc.token", "/tmp/config/data"),
    ("/tmp/config/ipc.token", "/tmp/config/../data"),
])
def test_app_invalid_roots_never_provision(tmp_path, token, data):
    with pytest.raises(ValueError):
        ProfilePaths.from_app("work", token_file=Path(token), data_dir=Path(data),
                              environ={}, home=tmp_path)


def test_runtime_paths_match_selected_app_profile(tmp_path, monkeypatch):
    from src.runtime_paths import runtime_profile_paths

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", "work")
    monkeypatch.setenv("ODIN_DESKTOP_TOKEN_FILE", str(tmp_path / "config/ipc.token"))
    monkeypatch.setenv("ODIN_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    assert runtime_profile_paths().data_dir == tmp_path / "data"
    assert runtime_profile_paths().config_dir == tmp_path / "config"
    monkeypatch.delenv("ODIN_DESKTOP_TOKEN_FILE")
    with pytest.raises(ValueError, match="together"):
        runtime_profile_paths()


def scaffold(paths):
    paths.create_private()
    token = paths.config_dir / "ipc.token"
    token.write_text("1" * 64)
    token.chmod(0o600)
    (paths.config_dir / "app-state.json").write_text(json.dumps({"noTrayNoticeShown": True}))
    (paths.data_dir / "drafts.json").write_text("{}")
    logs = paths.data_dir / "logs"
    logs.mkdir(mode=0o700)
    (logs / "core.log").write_text("app supervisor starting\n")


def test_app_bootstrap_retains_app_files_without_importing_authority(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    before = (paths.config_dir / "ipc.token").read_bytes()
    authority = OwnerAuthority(paths, app_bootstrap=True)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    assert authority.accepts(context)
    assert (paths.config_dir / "ipc.token").read_bytes() == before
    assert not paths.config_file.exists()
    authority.release_runtime()
    assert not authority.accepts(context)


@pytest.mark.parametrize("area,name", [("data", "drafts.json.tmp"),
                                      ("config", "app-state.json.tmp")])
def test_app_bootstrap_retains_interrupted_app_save_without_reading_it(tmp_path, area, name):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    root = paths.data_dir if area == "data" else paths.config_dir
    leftover = root / name
    leftover.write_bytes(b"incomplete opaque app save")
    authority = OwnerAuthority(paths, app_bootstrap=True)
    try:
        context = authority.authenticate_local(peer_uid=os.geteuid())
        assert authority.accepts(context)
        assert leftover.read_bytes() == b"incomplete opaque app save"
    finally:
        authority.release_runtime()


@pytest.mark.parametrize("name", ["engine.sqlite.tmp", "config.yml.tmp", "unknown.tmp"])
def test_app_bootstrap_does_not_ignore_arbitrary_temporary_engine_state(tmp_path, name):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    (paths.data_dir / name).write_text("not app scaffolding")
    with pytest.raises(ValueError, match="existing state"):
        OwnerAuthority(paths, app_bootstrap=True)


def test_app_bootstrap_refuses_linked_drafts_temporary_file(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    (paths.data_dir / "drafts.json.tmp").symlink_to(paths.data_dir / "drafts.json")
    with pytest.raises(PermissionError, match="unsafe app bootstrap"):
        OwnerAuthority(paths, app_bootstrap=True)


def test_non_app_authority_still_refuses_existing_state(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    with pytest.raises(ValueError, match="existing state"):
        OwnerAuthority(paths)
    assert not paths.identity_file.exists()


@pytest.mark.parametrize("area,name", [("config", "config.yml"), ("data", "engine.sqlite"),
                                      ("logs", "odin.log"), ("secrets", "environment")])
def test_bootstrap_cannot_import_engine_state(tmp_path, area, name):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    roots = {"config": paths.config_dir, "data": paths.data_dir,
             "logs": paths.data_dir / "logs", "secrets": paths.secrets_dir}
    (roots[area] / name).write_text("fixture")
    with pytest.raises(ValueError):
        OwnerAuthority(paths, app_bootstrap=True)
    assert not paths.identity_file.exists()


def test_bootstrap_does_not_repair_unsafe_token(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    scaffold(paths)
    token = paths.config_dir / "ipc.token"
    token.chmod(0o644)
    with pytest.raises(PermissionError):
        OwnerAuthority(paths, app_bootstrap=True)
    assert token.stat().st_mode & 0o777 == 0o644
    assert not paths.identity_file.exists()


def test_profile_lock_follows_identity_not_socket_or_data_override(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    first = OwnerAuthority(paths)
    first.acquire_runtime()
    alternative = ProfilePaths.from_app(
        paths.profile_id, token_file=paths.config_dir / "ipc.token",
        data_dir=tmp_path / "other-data", environ={}, home=tmp_path,
    )
    second = OwnerAuthority(alternative)
    try:
        with pytest.raises(BlockingIOError):
            second.acquire_runtime()
        first.release_runtime()
        second.acquire_runtime()
    finally:
        first.release_runtime()
        second.release_runtime()


def test_replaced_lock_revokes_context_and_held_descriptor(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    first = OwnerAuthority(paths)
    context = first.authenticate_local(peer_uid=os.geteuid())
    lock = paths.config_dir / ".core.lock"
    lock.rename(paths.config_dir / ".retired-core.lock")
    replacement = OwnerAuthority(paths)
    try:
        replacement.acquire_runtime()
        assert not first.accepts(context)
        with pytest.raises(PermissionError, match="lock changed"):
            first.acquire_runtime()
    finally:
        replacement.release_runtime()
        first.release_runtime()


def test_fifo_identity_refuses_promptly_and_revokes_existing_context(tmp_path):
    import subprocess
    import sys

    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    authority = OwnerAuthority(paths)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    paths.identity_file.rename(paths.config_dir / "saved-profile.json")
    os.mkfifo(paths.identity_file, 0o600)
    program = """
import sys
from pathlib import Path
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
paths = ProfilePaths.from_xdg(environ={}, home=Path(sys.argv[1]))
try:
    OwnerAuthority(paths)
except PermissionError:
    raise SystemExit(0)
raise SystemExit(1)
"""
    try:
        result = subprocess.run([sys.executable, "-c", program, str(tmp_path)],
                                capture_output=True, timeout=2)
        assert result.returncode == 0
        assert not authority.accepts(context)
    finally:
        authority.release_runtime()


def test_core_parser_explicit_inputs_only(tmp_path, monkeypatch):
    from src.cli import parse_core_args

    monkeypatch.setenv("HOME", str(tmp_path))
    options = parse_core_args(["--socket", str(tmp_path / "run/core.sock"),
                               "--token-file", str(tmp_path / "config/ipc.token"),
                               "--profile", "work", "--data-dir", str(tmp_path / "data")])
    assert options.paths.profile_id == "work"
    assert options.paths.config_dir == tmp_path / "config"
    assert options.paths.data_dir == tmp_path / "data"
    with pytest.raises(SystemExit) as missing:
        parse_core_args([])
    assert missing.value.code == 2


def test_entry_uses_containment_and_finalize_barrier(tmp_path, monkeypatch):
    from src import __main__ as entry
    from src.desktop import core

    stages = []
    monkeypatch.setattr(entry.sys, "argv", ["desktop", "--socket", str(tmp_path / "run.sock"),
                         "--token-file", str(tmp_path / "config/ipc.token"), "--profile", "work",
                         "--data-dir", str(tmp_path / "data")])
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("ODIN_DESKTOP_PROFILE", "ODIN_DESKTOP_TOKEN_FILE", "ODIN_DESKTOP_DATA_DIR"):
        monkeypatch.setenv(key, "unselected-fixture")
    monkeypatch.setattr(entry, "_enable_process_containment", lambda log: stages.append("contain")
                        or True)

    class Reaper:
        def start(self):
            stages.append("reaper-start")

        async def stop(self):
            stages.append("reaper-stop")

    class Service:
        def __init__(self, paths, socket, token_file, *, release_runtime_on_close):
            assert paths.profile_id == "work"
            assert socket == tmp_path / "run.sock"
            assert token_file == tmp_path / "config/ipc.token"
            assert release_runtime_on_close is False
            from src.runtime_paths import runtime_profile_paths

            assert runtime_profile_paths() == paths

        async def run(self):
            stages.append("run")
            return 0

        def release_runtime(self):
            stages.append("release")

    def finalize(loop, reaper, log, code):
        assert code == 0
        stages.append("finalize")
        loop.close()

    monkeypatch.setattr(entry, "AdoptedZombieReaper", Reaper)
    monkeypatch.setattr(core, "CoreService", Service)
    monkeypatch.setattr(entry, "_finalize_and_exit", finalize)
    entry.main()
    assert stages == ["contain", "reaper-start", "run", "reaper-stop", "finalize", "release"]


def test_entry_failure_enters_finalization_before_any_error_logging(tmp_path, monkeypatch):
    import logging

    from src import __main__ as entry
    from src.desktop import core

    stages = []
    monkeypatch.setattr(entry.sys, "argv", ["desktop", "--socket", str(tmp_path / "run.sock"),
                         "--token-file", str(tmp_path / "config/ipc.token"), "--profile", "work",
                         "--data-dir", str(tmp_path / "data")])
    for key in ("ODIN_DESKTOP_PROFILE", "ODIN_DESKTOP_TOKEN_FILE", "ODIN_DESKTOP_DATA_DIR"):
        monkeypatch.setenv(key, "unselected-fixture")
    monkeypatch.setattr(entry, "_enable_process_containment", lambda log: True)

    class Reaper:
        def start(self):
            pass

        async def stop(self):
            pass

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            raise RuntimeError("harmless isolated service failure")

        def release_runtime(self):
            stages.append("release")

    def finalize(loop, reaper, log, code):
        assert code == 1
        stages.append("finalize")
        loop.close()

    monkeypatch.setattr(entry, "AdoptedZombieReaper", Reaper)
    monkeypatch.setattr(core, "CoreService", Service)
    monkeypatch.setattr(logging.Logger, "error", lambda *args: stages.append("sync-error-log"))
    monkeypatch.setattr(entry, "_finalize_and_exit", finalize)
    with pytest.raises(SystemExit) as failed:
        entry.main()
    assert failed.value.code == 1
    assert stages == ["finalize", "release"]


@pytest.mark.parametrize("failure_kind", ["permission", "secret", "hostile"])
def test_entry_reports_scrubbed_failure_only_under_armed_watchdog(
    tmp_path, monkeypatch, capsys, failure_kind,
):
    import logging

    from src import __main__ as entry
    from src.desktop import core

    logger = logging.getLogger("odin.desktop")
    monkeypatch.setattr(logger, "handlers", list(logger.handlers))

    stages = []
    secret = "credential-fixture-never-print"
    path = tmp_path / "cache/odin-desktop"

    class HostileMeta(type):
        def __hash__(cls):
            raise AssertionError("must not hash an exception's type")

    class HostileError(Exception, metaclass=HostileMeta):
        def __str__(self):
            raise AssertionError("must not stringify arbitrary exceptions")

        def __repr__(self):
            raise AssertionError("must not repr arbitrary exceptions")

    failures = {
        "permission": PermissionError(13, "foreign profile ancestor", str(path)),
        "secret": RuntimeError(secret),
        "hostile": HostileError(secret),
    }
    monkeypatch.setattr(entry.sys, "argv", ["desktop", "--socket", str(tmp_path / "run.sock"),
                         "--token-file", str(tmp_path / "config/ipc.token"), "--profile", "work",
                         "--data-dir", str(tmp_path / "data")])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for key in ("ODIN_DESKTOP_PROFILE", "ODIN_DESKTOP_TOKEN_FILE", "ODIN_DESKTOP_DATA_DIR"):
        monkeypatch.setenv(key, "unselected-fixture")
    monkeypatch.setattr(entry, "_enable_process_containment", lambda log: True)

    class Reaper:
        def start(self):
            pass

        async def stop(self):
            pass

        def drain_at_teardown(self):
            assert stages == ["armed"]
            return 0, True

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            raise failures[failure_kind]

        def release_runtime(self):
            stages.append("released")

    def arm(code):
        assert code == 1
        assert "Odin stopped" not in capsys.readouterr().err
        stages.append("armed")
        return object()

    def disarm(watchdog, code):
        assert code == 1
        output = capsys.readouterr().err
        assert secret not in output
        assert len(output.splitlines()) == 1
        if failure_kind == "permission":
            assert "PermissionError" in output
            assert "foreign profile ancestor" in output
            assert str(path) in output
        elif failure_kind == "secret":
            assert "RuntimeError" in output
            assert str(tmp_path / "data") in output
        else:
            assert "startup_failure" in output
        stages.append("disarmed")

    monkeypatch.setattr(entry, "AdoptedZombieReaper", Reaper)
    monkeypatch.setattr(core, "CoreService", Service)
    monkeypatch.setattr(entry, "_arm_finalize_watchdog", arm)
    monkeypatch.setattr(entry, "_disarm_finalize_watchdog", disarm)
    with pytest.raises(SystemExit) as failed:
        entry.main()
    assert failed.value.code == 1
    assert stages == ["armed", "disarmed", "released"]


@pytest.mark.asyncio
async def test_real_core_accepts_node_style_socketpair_stdin_and_exits_on_parent_eof():
    import asyncio
    import socket
    import sys
    import tempfile

    from tests.test_desktop_core_lifecycle import profile, request, wait_connected

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths, socket_path, token_file = profile(root)
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        process = None
        writer = None
        try:
            environment = {
                "PATH": os.environ["PATH"], "HOME": str(root), "LANG": "C.UTF-8",
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"), "XDG_CACHE_HOME": str(root / "cache"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "src", "--socket", str(socket_path),
                "--token-file", str(token_file), "--profile", paths.profile_id,
                "--data-dir", str(paths.data_dir), stdin=child,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=environment, cwd=Path(__file__).resolve().parents[1],
            )
            child.close()
            reader, writer, welcome = await wait_connected(process, socket_path)
            assert welcome["t"] == "welcome"
            parent.sendall(b"supervisor alive\n")
            status = await request(reader, writer, "status.get")
            assert status["result"]["phase"] == "ready"
            parent.close()
            _, stderr = await asyncio.wait_for(process.communicate(), 10)
            assert process.returncode == 0, stderr
            assert not socket_path.exists()
        finally:
            parent.close()
            child.close()
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            if process is not None and process.returncode is None:
                await asyncio.wait_for(process.communicate(), 15)


@pytest.mark.asyncio
async def test_parent_link_refuses_regular_files_and_datagram_sockets(tmp_path):
    import socket

    from src.desktop.lifecycle import CoreLifetime

    lifetime = CoreLifetime()
    with (tmp_path / "not-a-parent").open("w+") as regular:
        with pytest.raises(ValueError, match="supervised"):
            lifetime.watch_parent(regular.fileno())
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as datagram:
        with pytest.raises(ValueError, match="supervised"):
            lifetime.watch_parent(datagram.fileno())
    assert lifetime.admitting
    lifetime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", [False, True])
async def test_real_core_start_failure_names_credential_path_without_credential(unsafe):
    import asyncio
    import tempfile

    from tests.test_desktop_core_lifecycle import launch, profile

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths, socket_path, token_file = profile(root)
        token = token_file.read_bytes()
        if unsafe:
            token_file.chmod(0o644)
        else:
            token_file.unlink()
        process = await launch(paths, socket_path, token_file, root)
        _, stderr = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 1
        assert len(stderr.splitlines()) == 1
        assert b"Odin stopped:" in stderr
        assert (b"PermissionError" if unsafe else b"FileNotFoundError") in stderr
        assert str(token_file).encode() in stderr
        assert token not in stderr
