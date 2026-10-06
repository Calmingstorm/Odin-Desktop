"""Exercise the fixture launcher with fake Docker only; never start containers."""

import importlib.util
import os
import signal
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lab_fixture_runner", ROOT / "scripts/run-lab-fixture-tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    for relative in (*runner.FILES, f"{runner.CI}/Dockerfile"):
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(relative)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.os, "geteuid", lambda: 1000)
    calls = []

    def docker(*arguments, **kwargs):
        calls.append((arguments, kwargs))
        if arguments[0] == "build":
            context = Path(arguments[-1])
            assert [p.name for p in context.iterdir()] == ["Dockerfile"]
        if arguments[0] == "cp":
            with tarfile.open(fileobj=kwargs["stdin"]) as bundle:
                assert set(bundle.getnames()) == set(runner.FILES)
                assert all(item.isfile() for item in bundle.getmembers())
        return SimpleNamespace(stdout="0\n", returncode=0)

    monkeypatch.setattr(runner, "docker", docker)
    return calls, docker, tmp_path


def test_host_root_refused_before_any_docker(fake, monkeypatch):
    calls, _, _ = fake
    monkeypatch.setattr(runner.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit, match="root host"):
        runner.main([])
    assert not calls


@pytest.mark.parametrize("arguments", [["tests/test_other.py"], ["--privileged"], ["-k", "x"]])
def test_arbitrary_selection_and_options_refused(fake, arguments):
    with pytest.raises(SystemExit, match="selection is fixed"):
        runner.main(arguments)
    assert not fake[0]


@pytest.mark.parametrize("arguments", [[], ["--collect-only"]])
def test_minimal_build_copy_nonprivileged_container_and_exact_cleanup(fake, arguments):
    calls, _, _ = fake
    assert runner.main(arguments) == 0
    assert [call[0][0] for call in calls] == ["build", "create", "cp", "start",
                                             "inspect", "rm", "image"]
    create = calls[1][0]
    name = create[create.index("--name") + 1]
    image = create[-1 - len(arguments)]
    assert create == tuple([*runner.create_arguments(name, image), *arguments])
    assert create[create.index("--network") + 1] == "none"
    assert create[create.index("--cap-drop") + 1] == "ALL"
    assert create[create.index("--pids-limit") + 1] == "256"
    assert create[create.index("--memory") + 1] == "1g"
    assert create[create.index("--cpus") + 1] == "2"
    assert calls[2][0] == ("cp", "-", f"{name}:/fixture")
    assert calls[-2][0] == ("rm", "--force", name)
    assert calls[-1][0] == ("image", "rm", image)
    assert not any(option in create for option in (
        "--privileged", "--mount", "--volume", "-v", "--device", "--pid", "--ipc"))


@pytest.mark.parametrize("stage", ["build", "create", "cp", "start", "inspect"])
def test_failure_always_cleans_only_owned_artifacts(fake, monkeypatch, stage):
    calls, original, _ = fake

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == stage:
            raise subprocess.CalledProcessError(7, args)
        return result

    monkeypatch.setattr(runner, "docker", fail)
    assert runner.main([]) == 7
    assert calls[-2][0][0:2] == ("rm", "--force")
    assert calls[-1][0][0:2] == ("image", "rm")
    assert calls[-2][0][-1].startswith("odin-lab-fixture-")


def test_cancellation_start_cleans_and_restores_handler(fake, monkeypatch):
    calls, original, _ = fake
    old = signal.getsignal(signal.SIGTERM)

    def cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == "start":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return result

    monkeypatch.setattr(runner, "docker", cancel)
    with pytest.raises(SystemExit) as stopped:
        runner.main([])
    assert stopped.value.code == 143
    assert calls[-2][0][0] == "rm"
    assert signal.getsignal(signal.SIGTERM) == old


def test_container_failure_exit_is_not_hidden(fake, monkeypatch):
    _, original, _ = fake

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        return SimpleNamespace(stdout="1\n") if args[0] == "inspect" else result

    monkeypatch.setattr(runner, "docker", fail)
    assert runner.main([]) == 1


def test_no_credentials_or_display_environment():
    assert runner.clean_environment() == {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent",
        "DOCKER_CONFIG": "/nonexistent", "LANG": "C.UTF-8",
    }


@pytest.mark.parametrize("kind", ["leaf", "parent", "missing"])
def test_archive_rejects_symlink_or_missing_allowlisted_source(fake, tmp_path, kind):
    _, _, root = fake
    source = root / runner.TESTS[0]
    if kind == "parent":
        source.parent.rename(root / "moved")
        source.parent.symlink_to(root / "moved", target_is_directory=True)
    else:
        source.unlink()
        if kind == "leaf":
            source.symlink_to(root / runner.TESTS[1])
    with pytest.raises(ValueError, match="Unsafe or missing"):
        runner.archive_sources(root, tmp_path / "archive.tar")


def test_docker_subprocess_has_clean_env_and_streaming_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    runner.docker("start", "--attach", "own-container")
    assert calls[0][0] == (["docker", "start", "--attach", "own-container"],)
    options = calls[0][1]
    assert options["check"] is True
    assert set(options) == {"env", "check"}
    environment = options["env"]
    assert set(environment) == set(runner.clean_environment())
    assert environment["HOME"] == environment["DOCKER_CONFIG"]
    assert not Path(environment["HOME"]).exists()


def test_container_entrypoint_refuses_root_before_pytest(monkeypatch):
    spec = importlib.util.spec_from_file_location("fixture_entry", ROOT / runner.CI / "run.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(entry.os, "getuid", lambda: 0)
    monkeypatch.setattr(entry.os, "execv", lambda *a: pytest.fail("root pytest forbidden"))
    with pytest.raises(SystemExit, match="UID/GID 1000"):
        entry.main()


def test_start_timeout_cleans_owned_container(fake, monkeypatch):
    calls, original, _ = fake

    def timeout(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == "start":
            assert kwargs["timeout"] == 300
            raise subprocess.TimeoutExpired(args, 300)
        return result

    monkeypatch.setattr(runner, "docker", timeout)
    assert runner.main([]) == 124
    assert calls[-2][0][0] == "rm"


def test_nonregular_dockerfile_refused_before_read_or_docker(fake):
    calls, _, root = fake
    source = root / runner.CI / "Dockerfile"
    source.unlink()
    os.mkfifo(source)
    with pytest.raises(ValueError, match="regular file"):
        runner.main([])
    assert [call[0][0] for call in calls] == ["rm", "image"]


@pytest.mark.parametrize("operation", ["rm", "image"])
def test_cleanup_failure_cannot_report_success_and_attempts_both_removals(
    fake, monkeypatch, operation,
):
    calls, original, _ = fake

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == operation:
            raise subprocess.CalledProcessError(7, args)
        return result

    monkeypatch.setattr(runner, "docker", fail)
    assert runner.main([]) == 1
    assert calls[-2][0][0] == "rm"
    assert calls[-1][0][0] == "image"
