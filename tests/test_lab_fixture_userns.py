"""Mapping and failure classification with fake probes; no sudo or namespaces."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts.qualification.lab import fixture_userns as fixture


def payload(retry=False):
    return {
        "uid": 0, "euid": 0, "gid": 0, "egid": 0,
        "uid_map": [[1001, 1001, 1], [0, 100000, 1001]] if retry else [[0, 1001, 1]],
        "gid_map": [[1002, 1002, 1], [0, 200000, 1002]] if retry else [[0, 1002, 1]],
    }


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setattr(fixture.os, "getuid", lambda: 1001)
    monkeypatch.setattr(fixture.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(fixture.os, "getgid", lambda: 1002)
    monkeypatch.setattr(fixture.os, "getegid", lambda: 1002)


@pytest.mark.parametrize("retry", [False, True])
def test_mapping_verifies_exact_nonroot_host_owners(retry):
    fixture.verify_mapping(payload(retry), 1001, 1002, retry)


@pytest.mark.parametrize("key", ["uid", "euid", "gid", "egid"])
def test_worker_must_be_namespace_local_root(key):
    value = payload()
    value[key] = 1
    with pytest.raises(RuntimeError, match="namespace-local root"):
        fixture.verify_mapping(value, 1001, 1002, False)


@pytest.mark.parametrize("key", ["uid_map", "gid_map"])
@pytest.mark.parametrize("rows", [[], [[0, 0, 1]], [[0, -1, 1]], [[0, 1001, 0]],
                                 [[0, 1001]], [[0, 1001, 2]]])
def test_fresh_rejects_host_root_invalid_or_excess_mappings(key, rows):
    value = payload()
    value[key] = rows
    with pytest.raises(RuntimeError):
        fixture.verify_mapping(value, 1001, 1002, False)


@pytest.mark.parametrize("key", ["uid_map", "gid_map"])
@pytest.mark.parametrize("kind", ["single", "caller-missing", "overlap"])
def test_retry_requires_two_distinct_explicit_mappings(key, kind):
    value = payload(True)
    caller = 1001 if key == "uid_map" else 1002
    value[key] = {
        "single": [[0, caller, 1]],
        "caller-missing": [[0, 100000, 1]],
        "overlap": [[0, 100000, caller + 1], [caller, caller, 1]],
    }[kind]
    with pytest.raises(RuntimeError):
        fixture.verify_mapping(value, 1001, 1002, True)


@pytest.mark.parametrize("retry", [False, True])
def test_probe_verifies_mapping_with_clean_environment(identity, monkeypatch, retry):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload(retry)), stderr="")

    monkeypatch.setattr(fixture.subprocess, "run", run)
    assert fixture.probe_namespace(retry) == fixture.namespace_prefix(retry)
    command, options = calls[0]
    assert command == [*fixture.namespace_prefix(retry), fixture.sys.executable,
                       "-c", fixture.PROBE]
    assert "sudo" not in command
    assert "--kill-child=SIGKILL" in command
    assert options == {"env": {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                       "stdin": subprocess.DEVNULL, "capture_output": True,
                       "text": True, "timeout": 10}


@pytest.mark.parametrize("method", ["getuid", "getgid", "geteuid", "getegid"])
def test_root_or_elevated_parent_refused_before_probe(identity, monkeypatch, method):
    monkeypatch.setattr(fixture.os, method, lambda: 0)
    monkeypatch.setattr(fixture.subprocess, "run", lambda *a, **k: pytest.fail("probe forbidden"))
    with pytest.raises(RuntimeError, match="non-root"):
        fixture.probe_namespace(False)


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("error", [FileNotFoundError("unshare missing"),
                                  subprocess.TimeoutExpired("unshare", 10)])
def test_missing_or_denied_namespace_has_plain_capability_reason(
    identity, monkeypatch, retry, error,
):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(fixture.subprocess, "run", fail)
    with pytest.raises(fixture.NamespaceUnavailableError, match="KDE fixture needs"):
        fixture.probe_namespace(retry)


def test_mapper_denial_is_explicit_not_a_fresh_retry(identity, monkeypatch):
    monkeypatch.setattr(fixture.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="newuidmap: Operation not permitted"))
    with pytest.raises(fixture.NamespaceUnavailableError,
                       match="two distinct subordinate UID/GID.*newuidmap"):
        fixture.probe_namespace(True)


def test_malformed_successful_probe_is_failure_not_skip(identity, monkeypatch):
    monkeypatch.setattr(fixture.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="invalid json", stderr=""))
    with pytest.raises(json.JSONDecodeError):
        fixture.probe_namespace(False)


@pytest.mark.parametrize("retry", [False, True])
def test_emitter_executes_real_recipe_with_exact_namespace_owners(
    identity, monkeypatch, tmp_path, retry,
):
    prefix = fixture.namespace_prefix(retry)
    monkeypatch.setattr(fixture, "probe_namespace",
                        lambda value: prefix if value == retry else None)
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stderr="", stdout=(
            "retry initial namespace ownership: 0:0\n" if retry else ""))

    monkeypatch.setattr(fixture.subprocess, "run", run)
    recipe, home = tmp_path / "real recipe.sh", tmp_path / "home"
    fixture.emit_config(recipe, home, retry)
    assert len(calls) == 1  # Successful emission must never get ownership repair.
    command, options = calls[0]
    assert command == [*prefix, "bash", "-c", fixture.EMIT, "kde-fixture",
                       str(recipe), str(home), *( ["1001", "1002"] if retry else ["0", "0"]),
                       "yes" if retry else "no"]
    assert options["timeout"] == 15
    assert options["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert "sudo" not in command


@pytest.mark.parametrize("kind", ["returncode", "timeout", "missing-retry-evidence"])
def test_post_probe_execution_failures_never_become_skips(
    identity, monkeypatch, tmp_path, kind,
):
    monkeypatch.setattr(fixture, "probe_namespace", lambda retry: ["unshare"])
    calls = []

    def fail(command, **kwargs):
        calls.append((command, kwargs))
        if "chown" in command:
            return SimpleNamespace(returncode=0)
        if kind == "timeout":
            raise subprocess.TimeoutExpired("emitter", 15)
        return SimpleNamespace(returncode=1 if kind == "returncode" else 0,
                               stdout="", stderr="real emitter failure")

    monkeypatch.setattr(fixture.subprocess, "run", fail)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)) as failure:
        fixture.emit_config(tmp_path / "recipe", tmp_path / "home", True)
    assert not isinstance(failure.value, fixture.NamespaceUnavailableError)
    assert len(calls) == 2
    assert calls[1][0] == ["unshare", "chown", "-R", "1001:1002", "--", str(tmp_path / "home")]
    assert calls[1][1]["timeout"] == 10
    assert calls[1][1]["check"] is True


def test_cleanup_failure_preserves_original_timeout(identity, monkeypatch, tmp_path):
    monkeypatch.setattr(fixture, "probe_namespace", lambda retry: ["unshare"])

    def fail(command, **kwargs):
        if "chown" in command:
            raise subprocess.CalledProcessError(7, command)
        raise subprocess.TimeoutExpired(command, 15)

    monkeypatch.setattr(fixture.subprocess, "run", fail)
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        fixture.emit_config(tmp_path / "recipe", tmp_path / "home", True)
    assert "Failed retry ownership cleanup" in failure.value.__notes__[0]


def test_actual_shell_failure_runs_cleanup_without_masking_failure(tmp_path):
    # Harmless commands in the already-isolated pytest PID namespace. No real
    # namespace or chown here: exercise Bash's trap using a logging stub.
    recipe = tmp_path / "recipe.sh"
    log = tmp_path / "cleanup.log"
    home = tmp_path / "home"
    home.mkdir()
    recipe.write_text(
        "calls=0\n"
        'chown() { printf "%s\\n" "$*" >> "$6"; }\n'
        'kde_write_user_config() { calls=$((calls+1)); if (( calls == 2 )); '
        'then return 7; fi; mkdir -p "$1/.config"; : > "$1/.config/kaccessrc"; }\n'
        'stat() { printf "0:0\\n"; }\n'
    )
    # The stub needs its log argument independently of chown's own arguments.
    body = fixture.EMIT.replace('source "$1"', 'cleanup_log=$6; source "$1"')
    recipe.write_text(recipe.read_text().replace('>> "$6"', '>> "$cleanup_log"'))
    result = subprocess.run(
        ["bash", "-c", body, "fixture", str(recipe), str(home), "1001", "1002", "yes",
         str(log)], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 7
    assert log.read_text() == f"-R 1001:1002 -- {home}\n"
