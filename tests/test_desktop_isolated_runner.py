"""Probe and supervisor behaviour, without launching nested namespaces or sudo."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "desktop_isolated_runner", ROOT / "scripts/run-phase1-tests.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_runner(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "os", SimpleNamespace(
        getuid=lambda: 1234, geteuid=lambda: 1234,
        getgid=lambda: 5678, getegid=lambda: 5678,
        readlink=lambda path: "pid:[host]",
        environ=os.environ,
        fsencode=os.fsencode,
    ))
    monkeypatch.setattr(runner.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="testowner"))
    return runner


def probe_results(runner, monkeypatch, results, permission=0):
    captured = []
    outcomes = iter(results)

    def probe(command, **options):
        captured.append((command, options))
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    def permission_probe(command, **options):
        assert command == ["sudo", "-n", "-l", runner.ISOLATION_HELPER]
        assert options["timeout"] == 10
        assert options["stdin"] == subprocess.DEVNULL
        assert options["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        if isinstance(permission, Exception):
            raise permission
        return subprocess.CompletedProcess(command, permission, "", "")

    monkeypatch.setattr(runner.subprocess, "run", permission_probe)
    monkeypatch.setattr(runner, "_run_namespace", probe)
    return captured


def test_runner_namespaces_and_cleans_ambient_environment(tmp_path, monkeypatch):
    runner = configure_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.sys, "argv", ["runner", "tests/test_neutral.py"])
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("DISPLAY", ":active-display")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "active-session")
    monkeypatch.setenv("DISCORD_TOKEN", "fixture-only-not-a-credential")
    monkeypatch.setenv("RUNNER_TRACKING_ID", "cleanup-fixture")
    probes = probe_results(runner, monkeypatch, [0])
    captured = []
    monkeypatch.setattr(
        runner, "run_namespace", lambda cmd: captured.append(cmd) or 0
    )
    assert runner.main() == 0
    command = captured[0]
    assert command[:4] == ["sudo", "-n", runner.ISOLATION_HELPER, "env"]
    assert command[4:6] == [
        "-i",
        f"PATH={tmp_path / '.venv/bin'}:/usr/bin:/bin",
    ]
    assert not any(
        arg.startswith((
            "DISPLAY=", "DBUS_SESSION_BUS_ADDRESS=", "XDG_RUNTIME_DIR=", "DISCORD_TOKEN="
        ))
        for arg in command
    )
    home = Path(next(arg.removeprefix("HOME=") for arg in command if arg.startswith("HOME=")))
    assert home.parent.parent == tmp_path / ".test-state"
    assert home.parent.name.startswith("isolation-")
    assert f"XDG_DATA_HOME={home.parent / 'data'}" in command
    assert "RUNNER_TRACKING_ID=cleanup-fixture" in command
    assert not home.parent.exists()  # throwaway state is cleaned, even on persistent runners
    assert command[-1] == "tests/test_neutral.py"
    supervisor = command.index(runner.NAMESPACE_SUPERVISOR)
    assert command[supervisor + 1:supervisor + 4] == ["1234", "5678", "pid:[host]"]
    assert probes[0][0] == command[:supervisor + 4]
    assert probes[0][1]["timeout"] == 10
    assert probes[0][1]["quiet"] is True
    assert "--timeout=90" in command
    assert "--timeout-method=signal" in command


@pytest.mark.parametrize("failure", [
    1, FileNotFoundError("unshare"), subprocess.TimeoutExpired("unshare", 10),
])
def test_probe_failure_falls_back_to_sudo_as_numeric_invoking_user(
    tmp_path, monkeypatch, failure,
):
    runner = configure_runner(tmp_path, monkeypatch)
    probes = probe_results(runner, monkeypatch, [failure, 0])
    command = runner.namespace_command({"HOME": str(tmp_path)})
    assert len(probes) == 2
    assert command[:12] == [
        "sudo", "-n", "unshare", "--mount", "--pid", "--fork", "--mount-proc",
        "--kill-child", "sudo", "-n", "-u", "#1234",
    ]
    assert command[12:17] == ["-g", "#5678", "env", "-i", f"HOME={tmp_path}"]
    assert command[-3:] == ["1234", "5678", "pid:[host]"]
    assert not any(Path(arg).name == "pytest" for arg in probes[0][0])
    assert not any(Path(arg).name == "pytest" for arg in probes[1][0])


@pytest.mark.parametrize("permission", [
    1, FileNotFoundError("sudo"), subprocess.TimeoutExpired("sudo", 10),
])
def test_helper_without_permission_is_skipped_not_launched(tmp_path, monkeypatch, permission):
    runner = configure_runner(tmp_path, monkeypatch)
    probes = probe_results(runner, monkeypatch, [0], permission=permission)
    command = runner.namespace_command({"HOME": str(tmp_path)})
    assert len(probes) == 1
    assert command[:3] == ["sudo", "-n", "unshare"]
    assert runner.ISOLATION_HELPER not in command
    assert "--user" not in command


@pytest.mark.parametrize("failures", [[1, 1], [FileNotFoundError(), FileNotFoundError()]])
def test_both_namespace_methods_fail_closed_without_tests(tmp_path, monkeypatch, failures):
    runner = configure_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.sys, "argv", ["runner", "tests/test_neutral.py"])
    probes = probe_results(runner, monkeypatch, failures)
    monkeypatch.setattr(
        runner, "run_namespace", lambda *args: pytest.fail("must not execute tests"),
    )
    with pytest.raises(SystemExit, match="no tests were started") as error:
        runner.main()
    assert "UID 65534" in str(error.value)
    assert "sudo" in str(error.value)
    assert len(probes) == 2
    assert not list((tmp_path / ".test-state").iterdir())


@pytest.mark.parametrize("identity", [
    {"getuid": lambda: 0, "geteuid": lambda: 0},
    {"geteuid": lambda: 0},
    {"getegid": lambda: 0},
    {"getgid": lambda: 0, "getegid": lambda: 0},
])
def test_root_or_elevated_caller_is_rejected_before_any_probe(tmp_path, monkeypatch, identity):
    runner = configure_runner(tmp_path, monkeypatch)
    for name, value in identity.items():
        monkeypatch.setattr(runner.os, name, value)
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not probe as root"),
    )
    with pytest.raises(SystemExit, match="non-root, unprivileged user"):
        runner.namespace_command({})


def test_failed_suite_is_not_retried_through_sudo(tmp_path, monkeypatch):
    runner = configure_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.sys, "argv", ["runner", "tests/test_neutral.py"])
    probes = probe_results(runner, monkeypatch, [0])
    calls = []
    monkeypatch.setattr(runner, "run_namespace", lambda *a: calls.append(a) or 9)
    assert runner.main() == 9
    assert len(probes) == len(calls) == 1
    assert not list((tmp_path / ".test-state").iterdir())


def test_long_selection_keeps_proc_cmdline_small_without_dropping_arguments(tmp_path, monkeypatch):
    runner = configure_runner(tmp_path, monkeypatch)
    arguments = [f"tests/test_fixture_{index}.py" for index in range(700)]
    monkeypatch.setattr(runner.sys, "argv", ["runner", *arguments])
    probe_results(runner, monkeypatch, [0])
    captured = []

    def execute(command):
        response = Path(command[-1].removeprefix("@"))
        assert command[-1].startswith("@")
        assert response.read_text().splitlines() == arguments
        captured.append(response)
        assert sum(len(os.fsencode(arg)) + 1 for arg in command) < 16384
        return 0

    monkeypatch.setattr(runner, "run_namespace", execute)
    assert runner.main() == 0
    assert not captured[0].exists()


def test_long_selection_keeps_plugin_preloads_outside_response_file(tmp_path, monkeypatch):
    runner = configure_runner(tmp_path, monkeypatch)
    selections = [f"tests/test_fixture_{index}.py" for index in range(700)]
    arguments = [*selections, "-p", "scripts.qualification_once", "-pother.plugin",
                 "--collect-only", "--qualification-once-state=fixture.json"]
    probe_results(runner, monkeypatch, [0])

    def execute(command):
        assert command[-4:-1] == ["-p", "scripts.qualification_once", "-pother.plugin"]
        assert Path(command[-1].removeprefix("@")).read_text().splitlines() == [
            *selections, "--collect-only", "--qualification-once-state=fixture.json",
        ]
        return 0

    monkeypatch.setattr(runner, "run_namespace", execute)
    assert runner.main(arguments) == 0


@pytest.mark.parametrize("changed", [
    {}, {"getuid": 0}, {"getuid": 4321}, {"geteuid": 0},
    {"getgid": 8765}, {"getegid": 0}, {"getpid": 2},
    {"self_namespace": "pid:[host]"}, {"init_namespace": "pid:[different]"},
    {"requested_uid": "0", "getuid": 0, "geteuid": 0},
])
def test_supervisor_verifies_namespace_proc_and_non_root_identity(monkeypatch, changed):
    runner = load_runner()
    state = {"getuid": 1234, "geteuid": 1234, "getgid": 5678, "getegid": 5678,
             "getpid": 1, "self_namespace": "pid:[child]", "init_namespace": "pid:[child]",
             "requested_uid": "1234"}
    state.update(changed)
    fake_os = SimpleNamespace(**{
        name: lambda name=name: state[name]
        for name in ("getuid", "geteuid", "getgid", "getegid", "getpid")
    })
    fake_os.readlink = lambda path: state[
        "self_namespace" if path == "/proc/self/ns/pid" else "init_namespace"
    ]
    children = iter([(99, 0), (42, 7 << 8)])
    fake_os.wait = lambda: next(children)
    fake_os.waitstatus_to_exitcode = os.waitstatus_to_exitcode
    calls = []
    fake_subprocess = SimpleNamespace(
        Popen=lambda args: calls.append(args) or SimpleNamespace(pid=42),
    )
    fake_signal = SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *args: None)
    fake_sys = SimpleNamespace(argv=[
        "supervisor", state["requested_uid"], "5678", "pid:[host]", "pytest", "selection",
    ], executable="fixture-python")
    with monkeypatch.context() as context:
        context.setitem(sys.modules, "os", fake_os)
        context.setitem(sys.modules, "subprocess", fake_subprocess)
        context.setitem(sys.modules, "sys", fake_sys)
        context.setitem(sys.modules, "signal", fake_signal)
        with pytest.raises(SystemExit) as error:
            exec(runner.NAMESPACE_SUPERVISOR, {})
    if not changed:
        assert error.value.code == 7
        assert calls == [["fixture-python", "-c",
                          "import subprocess, sys; raise SystemExit(subprocess.call(sys.argv[1:]))",
                          "pytest", "selection"]]
    else:
        assert "not verified" in str(error.value)
        assert not calls


@pytest.mark.parametrize("cancelled", [False, True])
def test_namespace_process_ownership_and_cancellation(tmp_path, monkeypatch, cancelled):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    handlers = {}
    originals = {runner.signal.SIGINT: object(), runner.signal.SIGTERM: object()}
    handlers.update(originals)
    signals = []

    def install(sig, handler):
        previous = handlers[sig]
        handlers[sig] = handler
        return previous

    monkeypatch.setattr(runner.signal, "signal", install)
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    waits = []

    def wait(**kwargs):
        waits.append(kwargs)
        if cancelled and len(waits) == 1:
            handlers[runner.signal.SIGTERM](runner.signal.SIGTERM, None)
        return 9

    process = SimpleNamespace(pid=4321, wait=wait, poll=lambda: None if cancelled else 9)
    launched = []
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **kw: launched.append((a, kw)) or process,
    )
    if cancelled:
        with pytest.raises(SystemExit) as error:
            runner.run_namespace(["unshare", "fixture"])
        assert error.value.code == 143
        assert signals == [(4321, runner.signal.SIGKILL)]
        assert waits == [{}, {"timeout": 10}]
    else:
        assert runner.run_namespace(["unshare", "fixture"]) == 9
        assert not signals
        assert waits == [{}]
    assert handlers == originals
    assert launched == [((["unshare", "fixture"],), {
        "cwd": tmp_path, "env": {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        "start_new_session": True,
    })]


def test_timed_out_probe_kills_group_and_reaps_without_privileged_kill(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    handlers = {sig: object() for sig in (runner.signal.SIGINT, runner.signal.SIGTERM)}
    originals = handlers.copy()

    def install(sig, handler):
        previous = handlers[sig]
        handlers[sig] = handler
        return previous

    monkeypatch.setattr(runner.signal, "signal", install)
    signals = []
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    waits = []

    def wait(**kwargs):
        waits.append(kwargs)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired("fixture", 10)
        return -9

    process = SimpleNamespace(pid=4321, wait=wait, poll=lambda: None)
    launched = []
    monkeypatch.setattr(runner.subprocess, "Popen",
                        lambda *a, **kw: launched.append((a, kw)) or process)
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda *a, **kw: pytest.fail("cleanup must never sudo kill"))
    with pytest.raises(subprocess.TimeoutExpired):
        runner._run_namespace(["sudo", "-n", runner.ISOLATION_HELPER], timeout=10, quiet=True)
    assert signals == [(4321, runner.signal.SIGKILL)]
    assert waits == [{"timeout": 10}, {"timeout": 10}]
    assert handlers == originals
    assert launched[0][1]["start_new_session"] is True
    assert launched[0][1]["stdin"] == subprocess.DEVNULL


def test_runner_refuses_an_empty_unclassified_selection(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "maintenance/qualification-plan.json").write_text('{"groups": []}')
    monkeypatch.setattr(
        runner.subprocess, "call", lambda *args, **kwargs: pytest.fail("must not execute")
    )
    with pytest.raises(SystemExit, match="unclassified"):
        runner.main()


@pytest.mark.parametrize("versions,expected", [
    ({"3.12.3": "3.12.3", "3.12.12": "3.12.12", "3.12.99-rc.1": "3.12.99"}, "3.12.12"),
    ({"3.12.3-rc.1": "3.12.3"}, None),
    ({}, None),
    ({"3.12.3": "3.12.4"}, None),
])
def test_ci_uses_only_an_exact_stable_cached_python(tmp_path, versions, expected):
    workflow = yaml.safe_load((ROOT / ".github/workflows/phase1-engine.yml").read_text())
    for job_name, job in workflow["jobs"].items():
        guard = next(step for step in job["steps"] if step.get("id") == "cached-python")
        setup = next(step for step in job["steps"] if step.get("uses") == "actions/setup-python@v5")
        assert setup["with"]["python-version"] == "${{ steps.cached-python.outputs.version }}"
        cache = tmp_path / job_name
        cache.mkdir()
        for version, actual in versions.items():
            directory = cache / "Python" / version / "x64"
            (directory / "bin").mkdir(parents=True)
            (directory.parent / "x64.complete").touch()
            python = directory / "bin/python"
            python.write_text(f"#!/bin/sh\nprintf '%s\\n' '{actual}'\n")
            python.chmod(0o755)
        output = cache / "output"
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", guard["run"]],
            env={"PATH": "/usr/bin:/bin", "RUNNER_TOOL_CACHE": str(cache),
                 "GITHUB_OUTPUT": str(output)},
            capture_output=True, text=True, timeout=5,
        )
        if expected:
            assert result.returncode == 0, result.stderr
            assert output.read_text() == f"version={expected}\n"
        else:
            assert result.returncode != 0
            assert "::error::" in result.stdout
            assert not output.exists()


def test_ci_labels_keep_broad_suites_on_desktop_and_light_fixtures_bounded():
    workflow = yaml.safe_load((ROOT / ".github/workflows/phase1-engine.yml").read_text())
    light = workflow["jobs"]["short-gates"]
    full = workflow["jobs"]["full-suites"]
    assert light["runs-on"] == "${{ matrix.labels }}"
    assert light["strategy"]["matrix"]["include"] == [
        {"lane": "light", "labels": ["self-hosted", "odin-desktop-ci-light"]},
        {"lane": "desktop", "labels": ["self-hosted", "odin-desktop-short"]},
    ]
    assert light["strategy"]["fail-fast"] is False
    assert full["runs-on"] == ["self-hosted", "odin-desktop-ci"]
    light_commands = "\n".join(step.get("run", "") for step in light["steps"])
    full_commands = "\n".join(step.get("run", "") for step in full["steps"])
    # The offline capture fixtures are safe on either machine. Only this
    # explicit selection may use the namespace launcher in the light lane;
    # the broad engine/process suites still require desktop-only runners.
    light_namespace_commands = [
        step["run"] for step in light["steps"]
        if "run-phase1-tests.py" in step.get("run", "")
    ]
    assert light_namespace_commands == [
        ".venv/bin/python scripts/run-phase1-tests.py "
        "tests/test_lab_cinnamon.py tests/test_lab_gnome.py -rs"
    ]
    assert "run-qualified-tests.py" not in light_commands
    assert "scripts/maintenance/phase2_plan.py" in light_commands
    assert "scripts/run-phase1-tests.py tests/test_desktop_phase2_plan.py" not in full_commands
    assert "run-qualified-tests.py" not in full_commands
    # Whole classified groups run once across duration-balanced parallel shards.
    qualification = workflow["jobs"]["qualification"]
    assert qualification["runs-on"] == ["self-hosted", "odin-desktop-ci"]
    assert qualification["strategy"] == {"fail-fast": False, "matrix": {"shard": [1, 2, 3, 4, 5]}}
    shard_commands = [step["run"] for step in qualification["steps"]
                      if "run-qualified-tests.py" in step.get("run", "")]
    assert shard_commands == [
        ".venv/bin/python scripts/run-qualified-tests.py --shard ${{ matrix.shard }}/5"]
    namespace_commands = [line for step in full["steps"]
                          for line in step.get("run", "").splitlines()
                          if line.startswith(".venv/bin/python scripts/run-phase1-tests.py")]
    assert len(namespace_commands) == 2
    assert namespace_commands[0] == (
        ".venv/bin/python scripts/run-phase1-tests.py --additional-desktop-boundaries")
    lab_files = namespace_commands[1].split()[2:]
    assert lab_files and all(path.startswith("tests/") for path in lab_files)
    assert len(lab_files) == len(set(lab_files))
    assert not any(Path(path).name.startswith("test_desktop_") for path in lab_files)
    pass_now = next(step for step in full["steps"] if step.get("id") == "pass-now")
    assert "continue-on-error" not in pass_now
    for script in ("run-lab-fixture-tests.py",):
        step = next(step for step in full["steps"] if script in step.get("run", ""))
        assert step["if"] == "${{ !cancelled() && steps.pass-now.outcome != 'skipped' }}"
        assert "continue-on-error" not in step
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert "github.event.pull_request.number || github.ref" in workflow["concurrency"]["group"]
def test_default_selection_runs_full_adapter_instead_of_obsolete_original(tmp_path, monkeypatch):
    import json

    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "tests").mkdir()
    adapter = "tests/test_desktop_frozen_process.py"
    (tmp_path / adapter).write_text("def test_entire_corpus(): pass\n")
    (tmp_path / "tests/test_direct_helper.py").write_text("def test_helper(): pass\n")
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps({
        "groups": [{"name": "faithful-process", "reason": "Qualified complete frozen corpus",
                    "files": [adapter, "tests/test_direct_helper.py"]}],
    }))
    captured = []
    probe_results(runner, monkeypatch, [0])
    monkeypatch.setattr(runner, "run_namespace",
                        lambda command: captured.append(command) or 0)
    assert runner.main() == 0
    command = captured[0]
    assert "tests/test_original_process.py" not in command
    assert "tests/test_direct_helper.py" in command
    assert adapter in command
    assert command.count(adapter) == 1


def test_additional_flag_keeps_namespace_supervisor_and_receipt(tmp_path, monkeypatch):
    import json

    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_plan.py").touch()
    (tmp_path / "tests/test_desktop_extra.py").touch()
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps({
        "groups": [{"name": "plan", "reason": "reviewed", "files": ["tests/test_plan.py"]}],
    }))
    captured = []
    probe_results(runner, monkeypatch, [0])
    monkeypatch.setattr(runner, "run_namespace", lambda command: captured.append(command) or 0)
    assert runner.main(["--additional-desktop-boundaries"]) == 0
    assert len(captured) == 1
    assert runner.NAMESPACE_SUPERVISOR in captured[0]
    assert "tests/test_desktop_extra.py" in captured[0]
    assert "tests/test_plan.py" not in captured[0]
    assert "--junitxml=.test-state/additional-desktop-boundaries.xml" in captured[0]


@pytest.mark.parametrize("arguments", [
    ["tests/test_other.py"], ["-k", "other"], ["--maxfail=1"],
    ["--additional-desktop-boundaries"],
])
def test_additional_flag_refuses_selection_overrides_before_launch(
    tmp_path, monkeypatch, arguments,
):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "run_namespace", lambda command: pytest.fail("must not launch"))
    with pytest.raises(SystemExit, match="accepts only"):
        runner.main(["--additional-desktop-boundaries", *arguments])
