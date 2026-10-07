"""Rootless host orchestration tests. Fake Incus only, no VM/display/bus use."""

import importlib.util
import io
import json
import subprocess
import tarfile
from contextlib import nullcontext
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/orca.py"
spec = importlib.util.spec_from_file_location("orca_host_tests", SCRIPT)
orca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orca)


def archive(tmp_path, *, extra=None, dirty=True, corrupt=False):
    files = {
        orca.BOOTSTRAP: b"# fixed guest helper",
        orca.SMOKE: b"# fixed session helper",
        orca.REAL_CORE: b"# fixed real-core helper",
        orca.OWNED: b"# fixed containment helper",
        orca.COLLECTOR: b"# fixed native collector",
        "bin/node": b"pinned node",
        "app/package-lock.json": b"{}",
        "app/out/main/index.js": b"compiled source",
        "app/test/e2e/orca.spec.ts": b"task source",
        "app/node_modules/electron/path.txt": b"electron",
        "app/node_modules/electron/dist/electron": b"pinned electron",
    }
    files.update({name: b"source suite" for name in orca.SUITE_SOURCES})
    files.update({name: b"focused helper source" for name in orca.PROBE_SOURCES})
    manifest = {
        "schema": 1,
        "source_built": True,
        "source_sha": "a" * 40,
        "source_dirty": dirty,
        "node_version": "v24.9.0",
        "source_files_sha256": {
            p: orca.digest(data) for p, data in files.items() if p != "bin/node"
        },
        "files": {p: {"sha256": orca.digest(data), "size": len(data)} for p, data in files.items()},
    }
    if corrupt:
        manifest["files"]["bin/node"]["sha256"] = "0" * 64
    path = tmp_path / "artifact.tgz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in {**files, orca.MANIFEST: json.dumps(manifest).encode()}.items():
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(data), 0o600
            tar.addfile(item, io.BytesIO(data))
        for item, data in extra or []:
            tar.addfile(item, io.BytesIO(data) if data is not None else None)
    return path


def task_report():
    return {
        "stats": {"expected": 7, "unexpected": 0, "flaky": 0},
        "suites": [
            {
                "specs": [
                    {
                        "title": name,
                        "tests": [{"status": "expected", "results": [{"status": "passed"}]}],
                    }
                    for name in orca.TASK_NAMES
                ]
            }
        ],
    }


class API:
    def __init__(
        self,
        artifact,
        *,
        fail_task=False,
        wrong_hash=False,
        timeout=False,
        cleanup_failure=False,
        evidence_path=None,
    ):
        self.calls = []
        self.artifact = artifact
        self.manifest, self.sha = orca.inspect_archive(artifact)
        self.fail_task, self.wrong_hash = fail_task, wrong_hash
        self.timeout, self.cleanup_failure = timeout, cleanup_failure
        self.evidence_path = evidence_path

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if "sha256sum" in args:
            paths = args[args.index("sha256sum") + 2 :]
            result = []
            for path in paths:
                name = path.split("/", 4)[-1]
                if name == "artifact.tar.gz":
                    sha = orca.digest(self.artifact.read_bytes())
                elif name == orca.MANIFEST:
                    sha = self.sha
                else:
                    sha = self.manifest["files"][name]["sha256"]
                result.append(f"{'0' * 64 if self.wrong_hash else sha}  {path}")
            return "\n".join(result) + "\n"
        if args[:2] == ("file", "pull"):
            target = Path(args[3])
            data = {
                "guest-proof.json": json.dumps(
                    {
                        "passed": not self.fail_task,
                        "source_sha256": self.sha,
                        "session": {"Type": "x11"},
                        "orca_version": "48.2",
                        "collector_running_during_tasks": True,
                        "native_dialog_collector": {"type": "ready"},
                        "cleanup": {
                            "owned_children_exited": not (self.timeout or self.cleanup_failure),
                            "uinput_restored": True,
                            "descendants_exited": True,
                        },
                        "evidence_sha256": {
                            **{name: orca.digest(b"attachment") for name in orca.COLLECTOR_FILES},
                            **(
                                {self.evidence_path: orca.digest(b"attachment")}
                                if self.evidence_path
                                else {}
                            ),
                        },
                    }
                ),
                "tasks.json": json.dumps(task_report()),
                "orca-debug.log": "SPEECH OUTPUT role name",
                "tasks.log": "tasks",
                "orca-console.log": "orca",
                "speech-dispatcher.log": "speechd",
            }.get(target.name, "attachment")
            target.write_text(data)
        if "dpkg-query" in args:
            return "orca\t48.2\n"
        if "python3" in args:
            if "--cleanup" in args:
                if self.cleanup_failure:
                    raise orca.Error("cleanup acknowledgement lost")
            elif self.timeout:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            elif self.fail_task:
                raise orca.Error("guest suite failed")
        return ""


@pytest.fixture
def running(monkeypatch):
    instance = {
        "name": "odq-cinnamon",
        "status": "Running",
        "config": {"volatile.base_image": "b" * 64},
    }
    monkeypatch.setattr(orca.lab, "mutation_lock", nullcontext)
    monkeypatch.setattr(orca.lab, "owned", lambda item: item)
    monkeypatch.setattr(orca.lab, "preflight", lambda api, **kw: {"instances": [instance]})
    monkeypatch.setattr(orca.lab, "image_spec", lambda name: {"fingerprint": "b" * 64})
    monkeypatch.setattr(orca, "validate_source", lambda manifest: None)
    return instance


def test_inspect_dirty_explicit_digest_bound(tmp_path):
    manifest, sha = orca.inspect_archive(archive(tmp_path))
    assert manifest["source_dirty"] is True
    assert len(sha) == 64


def test_missing_collector_source_provenance_is_rejected(tmp_path, monkeypatch):
    # Freeze an otherwise valid archive but remove the collector's provenance.
    path = archive(tmp_path)
    replacement = tmp_path / "without-collector-provenance.tgz"
    with tarfile.open(path) as source, tarfile.open(replacement, "w:gz") as output:
        for item in source:
            data = source.extractfile(item).read()
            if item.name == orca.MANIFEST:
                manifest = json.loads(data)
                del manifest["source_files_sha256"][orca.COLLECTOR]
                data = json.dumps(manifest).encode()
                item.size = len(data)
            output.addfile(item, io.BytesIO(data))
    with pytest.raises(orca.Error, match="working-source provenance"):
        orca.inspect_archive(replacement)


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "../escape",
        "app/../../escape",
        "app/.env",
        "app/.npmrc",
        "app/secrets/key",
        "app/credentials.json",
        "app\\escape",
        "app/./x",
    ],
)
def test_unsafe_archive_names_rejected(tmp_path, name):
    item = tarfile.TarInfo(name)
    item.size = 1
    with pytest.raises(orca.Error):
        orca.inspect_archive(archive(tmp_path, extra=[(item, b"x")]))


@pytest.mark.parametrize(
    "kind,target",
    [
        (tarfile.SYMTYPE, "../../../etc"),
        (tarfile.SYMTYPE, "/etc"),
        (tarfile.LNKTYPE, "bin/node"),
        (tarfile.FIFOTYPE, ""),
        (tarfile.CHRTYPE, ""),
    ],
)
def test_unsafe_archive_links_and_special_files(tmp_path, kind, target):
    item = tarfile.TarInfo("app/unsafe")
    item.type, item.linkname = kind, target
    with pytest.raises(orca.Error):
        orca.inspect_archive(archive(tmp_path, extra=[(item, None)]))


def test_private_key_rejected_without_echo(tmp_path):
    data = b"-----BEGIN RSA PRIVATE KEY-----\nU0VDUkVUX1ZBTFVF\n-----END RSA PRIVATE KEY-----\n"
    item = tarfile.TarInfo("app/key.pem")
    item.size = len(data)
    with pytest.raises(orca.Error, match="Private key") as error:
        orca.inspect_archive(archive(tmp_path, extra=[(item, data)]))
    assert "SECRET_VALUE" not in str(error.value)


def test_dependency_source_key_envelope_literals_are_not_credentials():
    source = (
        b'BEGIN = b"-----BEGIN OPENSSH PRIVATE KEY-----"\n'
        b'END = b"-----END OPENSSH PRIVATE KEY-----"\n'
    )
    orca.reject_credentials(source, "engine/site-packages/cryptography/serialization/ssh.py")


def test_private_key_material_inside_unrelated_source_file_is_rejected():
    source = (
        b"# fixture\n-----BEGIN PRIVATE KEY-----\n"
        b"QUJDREVGR0hJSktMTU5PUA==\n-----END PRIVATE KEY-----\n"
    )
    with pytest.raises(orca.Error, match="Private key"):
        orca.reject_credentials(source, "app/source.py")


def test_archive_digest_tamper(tmp_path):
    with pytest.raises(orca.Error, match="digests"):
        orca.inspect_archive(archive(tmp_path, corrupt=True))


@pytest.mark.parametrize(
    "output", ["", "bad", f"{'a' * 64}  /wrong", f"{'a' * 64}  /ok\n{'a' * 64}  /ok"]
)
def test_guest_digests_fail_closed(output):
    with pytest.raises(orca.Error):
        orca.parse_digests(output, {"/ok": "a" * 64})


@pytest.mark.parametrize(
    "name", ["odq-hyprland", "production", "odq-cinnamon;reboot", "../odq-gnome"]
)
def test_unsafe_target_before_any_io(tmp_path, name):
    api = type("NoCalls", (), {"run": lambda *a, **kw: pytest.fail("guest call")})()
    with pytest.raises(orca.Error, match="only"):
        orca.run(api, name, tmp_path / "missing", tmp_path / "evidence")


def test_preflight_failure_no_guest_calls(tmp_path, running, monkeypatch):
    api = API(archive(tmp_path))

    def blocked(*args, **kwargs):
        raise orca.Error("2 other VMs are not stopped")

    monkeypatch.setattr(orca.lab, "preflight", blocked)
    with pytest.raises(orca.Error, match="other VMs are not stopped"):
        orca.run(api, "odq-cinnamon", api.artifact, tmp_path / "evidence")
    assert api.calls == []
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("state", ["Stopped", "Starting", "Error", "Frozen"])
def test_nonrunning_target_rejected(tmp_path, running, state):
    running["status"] = state
    api = API(archive(tmp_path))
    with pytest.raises(orca.Error, match="actual running"):
        orca.run(api, "odq-cinnamon", api.artifact, tmp_path / "evidence")
    assert api.calls == []


def test_wrong_actual_base_image_rejected(tmp_path, running):
    running["config"]["volatile.base_image"] = "c" * 64
    api = API(archive(tmp_path))
    with pytest.raises(orca.Error, match="base image"):
        orca.run(api, "odq-cinnamon", api.artifact, tmp_path / "evidence")
    assert api.calls == []


def test_success_fixed_commands_provenance_private_files(tmp_path, running):
    api = API(archive(tmp_path))
    destination = tmp_path / "evidence"
    proof = orca.run(api, "odq-cinnamon", api.artifact, destination)
    assert proof["passed"] is True and proof["cleanup"] == "confirmed"
    assert proof["source"]["source_dirty"] is True
    assert proof["guest_files_sha256"]
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in destination.iterdir())
    assert not any(call[0][0] in ("start", "stop", "restart", "delete") for call in api.calls)
    for args, kwargs in api.calls:
        assert 0 < kwargs["timeout"] <= 2100
        assert not any(command in args for command in ("bash", "sh", "-c", "eval"))


def test_evidence_never_overwrites(tmp_path, running):
    api = API(archive(tmp_path))
    destination = tmp_path / "evidence"
    destination.mkdir()
    (destination / "proof.json").write_text("prior proof")
    with pytest.raises(orca.Error, match="new private"):
        orca.run(api, "odq-cinnamon", api.artifact, destination)
    assert api.calls == []
    assert (destination / "proof.json").read_text() == "prior proof"


@pytest.mark.parametrize("tamper", [False, True])
def test_collector_evidence_is_pulled_private_and_digest_checked(tmp_path, running, tamper):
    class CollectorAPI(API):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            if (
                tamper
                and args[:2] == ("file", "pull")
                and Path(args[3]).name == orca.COLLECTOR_FILES[0]
            ):
                Path(args[3]).write_text("tampered event source")
            return result

    api = CollectorAPI(archive(tmp_path))
    destination = tmp_path / "evidence"
    if tamper:
        with pytest.raises(orca.Error, match="digest mismatch"):
            orca.run(api, "odq-cinnamon", api.artifact, destination)
    else:
        proof = orca.run(api, "odq-cinnamon", api.artifact, destination)
        for name in orca.COLLECTOR_FILES:
            assert (destination / name).read_bytes() == b"attachment"
            assert (destination / name).stat().st_mode & 0o777 == 0o600
            assert proof["evidence_sha256"][name] == orca.digest(b"attachment")
            assert any(
                call[0][:2] == ("file", "pull") and call[0][3] == str(destination / name)
                for call in api.calls
            )


@pytest.mark.parametrize("missing", orca.COLLECTOR_FILES)
def test_missing_collector_digest_cannot_pass(tmp_path, running, missing):
    class MissingAPI(API):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            if args[:2] == ("file", "pull") and Path(args[3]).name == "guest-proof.json":
                path = Path(args[3])
                proof = json.loads(path.read_text())
                del proof["evidence_sha256"][missing]
                path.write_text(json.dumps(proof))
            return result

    api = MissingAPI(archive(tmp_path))
    with pytest.raises(orca.Error, match="collector evidence digests"):
        orca.run(api, "odq-cinnamon", api.artifact, tmp_path / "evidence")


@pytest.mark.parametrize(
    "options",
    [{"fail_task": True}, {"timeout": True}, {"wrong_hash": True}, {"cleanup_failure": True}],
)
def test_failure_retained_cleanup_no_task_replay(tmp_path, running, options):
    api = API(archive(tmp_path), **options)
    destination = tmp_path / "evidence"
    with pytest.raises(orca.Error):
        orca.run(api, "odq-cinnamon", api.artifact, destination)
    proof = json.loads((destination / "proof.json").read_text())
    assert proof["passed"] is False
    tasks = [args for args, _ in api.calls if "python3" in args and "--cleanup" not in args]
    assert len(tasks) <= 1
    assert proof["cleanup"] == (
        "unknown" if options.get("cleanup_failure") or options.get("timeout") else "confirmed"
    )


@pytest.fixture
def stage(tmp_path, monkeypatch):
    root, staging = tmp_path / "source", tmp_path / "stage"
    files = {
        orca.BOOTSTRAP: b"# helper",
        orca.SMOKE: b"# session helper",
        orca.REAL_CORE: b"# real-core helper",
        orca.OWNED: b"# containment helper",
        orca.COLLECTOR: b"# native collector",
        "app/package-lock.json": b"{}",
        "app/test/e2e/orca.spec.ts": b"source suite",
        "app/src/main.ts": b"source app",
    }
    files.update({name: b"source suite" for name in orca.SUITE_SOURCES})
    files.update({name: b"focused probe source" for name in orca.PROBE_SOURCES})
    for name, data in files.items():
        for destination in (root, staging):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    for name, data in {
        "bin/node": b"pinned node",
        "app/node_modules/electron-vite/bin/electron-vite.js": b"builder",
        "app/node_modules/electron/path.txt": b"electron",
        "app/node_modules/electron/dist/electron": b"electron",
    }.items():
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def output(command, **kwargs):
        if command[-1] == "--version":
            return "v24.9.0\n"
        if command[:2] == ["git", "rev-parse"]:
            return "a" * 40 + "\n"
        return b" M app/src/main.ts\n"

    def build(command, **kwargs):
        assert command[-1] == "build"
        assert kwargs["cwd"] == staging / "app"
        assert "DISPLAY" not in kwargs["env"] and "DBUS_SESSION_BUS_ADDRESS" not in kwargs["env"]
        target = staging / "app/out/main/index.js"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"source build")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(orca.subprocess, "check_output", output)
    monkeypatch.setattr(orca.subprocess, "run", build)
    return root, staging


def test_pack_builds_source_and_runtime_private_artifact(tmp_path, stage):
    root, staging = stage
    target = tmp_path / "new.tgz"
    manifest = orca.build_artifact(staging, target, root=root)
    assert manifest["source_built"] is True
    assert manifest["source_dirty"] is True
    assert target.stat().st_mode & 0o777 == 0o600
    assert manifest == orca.inspect_archive(target)[0]
    assert "app/src/main.ts" in manifest["source_files_sha256"]
    assert all(name in manifest["source_files_sha256"] for name in orca.PROBE_SOURCES)


def test_pack_mismatched_source_rejected_before_build(tmp_path, stage):
    root, staging = stage
    (staging / "app/src/main.ts").write_text("not actual source")
    with pytest.raises(orca.Error, match="source mismatch"):
        orca.build_artifact(staging, tmp_path / "new.tgz", root=root)
    assert not (tmp_path / "new.tgz").exists()


def test_pack_refuses_overwrite(tmp_path, stage):
    root, staging = stage
    target = tmp_path / "prior.tgz"
    target.write_text("prior evidence")
    with pytest.raises(orca.Error, match="never overwrite"):
        orca.build_artifact(staging, target, root=root)
    assert target.read_text() == "prior evidence"


def test_pack_refuses_escaping_staged_symlink(tmp_path, stage):
    root, staging = stage
    (staging / "app/outside").symlink_to("/etc/passwd")
    with pytest.raises(orca.Error, match="symlink"):
        orca.build_artifact(staging, tmp_path / "new.tgz", root=root)


@pytest.mark.parametrize(
    "name",
    ["engine/config/secrets.json", "engine/data/database.sqlite", "app/profile/session.json"],
)
def test_real_core_archive_never_includes_host_config_or_data(name):
    with pytest.raises(orca.Error):
        orca.safe_name(name)


def test_runner_source_manifest_is_not_helper_execution_authority(tmp_path):
    path = archive(tmp_path)
    manifest, _ = orca.inspect_archive(path)
    with pytest.raises(orca.Error, match="Current source differs"):
        orca.validate_source(manifest, root=tmp_path)


def test_runner_source_matches_built_working_bytes(tmp_path, stage):
    root, staging = stage
    manifest = orca.build_artifact(staging, tmp_path / "new.tgz", root=root)
    orca.validate_source(manifest, root=root)
    (root / orca.BOOTSTRAP).write_text("arbitrary helper replaced")
    with pytest.raises(orca.Error, match="Current source differs"):
        orca.validate_source(manifest, root=root)


def test_setuid_archive_members_forbidden(tmp_path):
    item = tarfile.TarInfo("app/setuid")
    item.mode, item.size = 0o4755, 1
    with pytest.raises(orca.Error, match="Setuid"):
        orca.inspect_archive(archive(tmp_path, extra=[(item, b"x")]))


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"stats": {"expected": 0, "unexpected": 0, "flaky": 0}},
        {"stats": {"expected": 1, "unexpected": 1, "flaky": 0}},
        {"stats": {"expected": 1, "unexpected": 0, "flaky": 0}, "suites": []},
    ],
)
def test_empty_or_failed_task_report_cannot_pass(report):
    with pytest.raises(orca.Error):
        orca.validate_tasks(report)


@pytest.mark.parametrize("name", ["tasks/chat/attachment.json", "guest-orca-task.png"])
def test_playwright_attachment_pulled_verified_before_guest_cleanup(tmp_path, running, name):
    api = API(archive(tmp_path), evidence_path=name)
    proof = orca.run(api, "odq-cinnamon", api.artifact, tmp_path / "evidence")
    assert (tmp_path / "evidence" / name).read_text() == "attachment"
    assert proof["evidence_sha256"][name] == orca.digest(b"attachment")


@pytest.mark.parametrize(
    "name", ["../outside", "/etc/passwd", "proof.json", "tasks/../outside", "tasks/.env"]
)
def test_unsafe_guest_evidence_inventory_cannot_write_host(tmp_path, running, name):
    api = API(archive(tmp_path), evidence_path=name)
    with pytest.raises(orca.Error, match="Unsafe or unexpected guest evidence"):
        orca.run(api, "odq-cinnamon", api.artifact, tmp_path / "evidence")
    assert not (tmp_path / "outside").exists()


def test_generic_json_credential_rejected_no_value_echo():
    with pytest.raises(orca.Error, match="Credential value") as error:
        orca.reject_credentials(
            b'{"nested":{"api_key":"LIVE_SECRET_EXAMPLE"}}', "app/resources/settings.json"
        )
    assert "LIVE_SECRET_EXAMPLE" not in str(error.value)


def test_bundled_real_core_cannot_skip():
    report = task_report()
    report["suites"][0]["specs"][-1]["tests"] = [{"status": "skipped"}]
    orca.validate_tasks(report)
    with pytest.raises(orca.Error, match="real-core lane"):
        orca.validate_tasks(report, real_core_required=True)
    report["suites"][0]["specs"][-1]["tests"] = [
        {"status": "expected", "results": [{"status": "passed"}]}
    ]
    orca.validate_tasks(report, real_core_required=True)


def test_dead_launcher_proof_without_descendant_drain_never_deletes_guest(tmp_path, running):
    api = API(archive(tmp_path))
    original = api.run

    def incomplete(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[:2] == ("file", "pull") and Path(args[3]).name == "guest-proof.json":
            path = Path(args[3])
            proof = json.loads(path.read_text())
            proof["cleanup"].pop("descendants_exited")
            path.write_text(json.dumps(proof))
        return result

    api.run = incomplete
    destination = tmp_path / "evidence"
    with pytest.raises(orca.Error):
        orca.run(api, "odq-cinnamon", api.artifact, destination)
    proof = json.loads((destination / "proof.json").read_text())
    assert proof["cleanup"] == "unknown"
    assert proof["passed"] is False
    assert not any("rm" in args for args, kwargs in api.calls)


def test_filtered_single_pass_cannot_qualify_desktop():
    report = task_report()
    report["suites"][0]["specs"] = report["suites"][0]["specs"][:1]
    with pytest.raises(orca.Error, match="seven-task"):
        orca.validate_tasks(report)
