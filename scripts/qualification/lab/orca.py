#!/usr/bin/env python3
"""Source-build an Orca artifact and qualify one already-running owned lab VM.

The operator prepares a PRIVATE external staging tree containing app/ (source,
fixture-core, dependencies, test suite) and bin/node. No downloads, host session
access, VM lifecycle changes, arbitrary guest commands or automatic retries.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("odq_orca_lab", HERE / "lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
Error = lab.LabError
NAMES = ("odq-cinnamon", "odq-gnome", "odq-kde")
BOOTSTRAP = "scripts/qualification/lab/guest/orca_run.py"
SMOKE = "scripts/qualification/lab/guest/smoke.py"
REAL_CORE = "scripts/qualification/lab/guest/real_core.py"
OWNED = "scripts/qualification/lab/guest/owned_processes.py"
COLLECTOR = "scripts/qualification/lab/guest/native_dialog_events.py"
COLLECTOR_FILES = ("native-dialog-events.jsonl", "native-dialog-collector.log")
PROBE_SOURCES = tuple(
    "scripts/qualification/lab/guest/" + name
    for name in ("focused_probe.py", "focused_electron.cjs")
)
MANIFEST = "artifact-manifest.json"
FILES = (
    "guest-proof.json",
    "tasks.json",
    "orca-debug.log",
    "tasks.log",
    "orca-console.log",
    "speech-dispatcher.log",
    *COLLECTOR_FILES,
)
MAX_BYTES = 3 * 1024**3
MAX_FILES = 150000
TASK_NAMES = (
    "orca-bridge-named-message-and-native-button-role",
    "orca-chat-results-attach-cancel-save-copy-report",
    "orca-conversation-child-modal-search",
    "orca-busy-steer-consumed-queued-stop-resume-unknown-no-flood",
    "orca-all-eleven-settings-names-roles-states-errors-secret",
    "orca-delayed-history-search-retains-focused-current-message",
    "orca-real-core-services-when-explicitly-provisioned",
)
SUITE_SOURCES = tuple(
    "app/test/e2e/" + name
    for name in (
        "orca.spec.ts",
        "orca.config.ts",
        "orca-speech.ts",
        "orca-guest.py",
        "accessibility-core.py",
    )
)
SECRET_NAME = re.compile(
    r"(?:^|/)(?:\.env(?:\..*)?|\.npmrc|\.netrc|\.git|\.ssh|secrets?(?:\.(?:json|ya?ml|ini|conf|toml))?|credentials?(?:\.(?:json|ya?ml|ini|conf|toml))?|id_rsa|id_ed25519)(?:/|$)",
    re.I,
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or str(path) != name
        or any(ord(c) < 32 for c in name)
        or SECRET_NAME.search(name)
    ):
        raise Error(f"Unsafe artifact path: {name!r}")
    if name != MANIFEST and path.parts[0] not in ("app", "bin", "scripts", "engine"):
        raise Error(f"Unexpected artifact root: {name}")
    if (
        path.parts[0] == "engine"
        and len(path.parts) > 1
        and path.parts[1] not in ("src", "site-packages")
    ):
        raise Error("Engine artifacts permit only source and dependencies, never config/data")
    if (
        path.parts[0] == "app"
        and len(path.parts) > 1
        and path.parts[1] in ("profile", "profiles", "user-data", "cache", "data", "config")
    ):
        raise Error("User profiles/configuration must not be bundled")
    return path


def link_destination(name, target):
    if not target or target.startswith("/") or "\\" in target:
        raise Error("Absolute or invalid artifact symlink")
    parts = list(PurePosixPath(name).parent.parts)
    for part in PurePosixPath(target).parts:
        if part == "..":
            if not parts:
                raise Error("Artifact symlink escapes archive")
            parts.pop()
        elif part != ".":
            parts.append(part)
    resolved = "/".join(parts)
    safe_name(resolved)
    return resolved


def reject_credentials(data, name):
    if re.search(
        rb"(?m)^-----BEGIN ((?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY)-----\r?\n"
        rb"(?:[A-Za-z0-9+/=]{16,}\r?\n)+-----END \1-----\s*$",
        data,
    ):
        raise Error(f"Private key in artifact: {name}")
    # Source/tests may mention credential field names. Only deployable credential
    # configurations with actual string values are refused; never echo values.
    if name.endswith((".yaml", ".yml", ".ini", ".conf", ".toml")):
        if re.search(
            rb'(?im)^\s*(?:api[_-]?key|password|access[_-]?token|client[_-]?secret)\s*[:=]\s*["\']?[^\s"\'${}][^\r\n]{7,}',
            data,
        ):
            raise Error(f"Possible credential configuration in artifact: {name}")
    if name.endswith(".json") and len(data) <= 16 * 1024**2:
        try:
            document = json.loads(data)
        except (ValueError, UnicodeError):
            return

        def credential(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if (
                        re.fullmatch(
                            r"api[_-]?key|password|access[_-]?token|client[_-]?secret", key, re.I
                        )
                        and isinstance(item, str)
                        and len(item) >= 8
                        and not item.startswith(("${", "<", "[REDACTED]"))
                    ):
                        return True
                    if credential(item):
                        return True
            elif isinstance(value, list):
                return any(credential(item) for item in value)
            return False

        if credential(document):
            raise Error(f"Credential value in artifact configuration: {name}")


def inspect_archive(path):
    """Never extract on the host. Refuse hardlinks, devices and symlink pivots."""
    entries, members, total = {}, {}, 0
    manifest_bytes = None
    with tarfile.open(path, "r:*") as archive:
        for item in archive:
            name = item.name.rstrip("/") if item.isdir() else item.name
            safe_name(name)
            if item.mode & 0o6000:
                raise Error("Setuid/setgid archive permissions are forbidden")
            if name in members or len(members) >= MAX_FILES:
                raise Error("Duplicate member or excessive artifact file count")
            members[name] = item
            if item.isdir():
                continue
            if item.issym():
                link_destination(name, item.linkname)
                entries[name] = {"symlink": item.linkname}
                continue
            if not item.isfile() or item.size < 0:
                raise Error(f"Unsupported archive member: {name}")
            total += item.size
            if total > MAX_BYTES:
                raise Error("Artifact exceeds size budget")
            data = archive.extractfile(item).read()
            reject_credentials(data, name)
            if name == MANIFEST:
                if item.size > 32 * 1024**2:
                    raise Error("Oversized artifact manifest")
                manifest_bytes = data
            else:
                entries[name] = {"sha256": digest(data), "size": item.size}
        for name, item in members.items():
            for parent in PurePosixPath(name).parents:
                if str(parent) in members and not members[str(parent)].isdir():
                    raise Error("Archive writes beneath a file or symlink")
            if item.issym():
                destination = link_destination(name, item.linkname)
                if destination not in members or members[destination].issym():
                    raise Error("Dangling or chained artifact symlink")
        if manifest_bytes is None:
            raise Error("Missing artifact manifest")
        manifest = json.loads(manifest_bytes)
        if manifest.get("files") != entries:
            raise Error("Artifact file digests do not match manifest")
        if (
            manifest.get("schema") != 1
            or manifest.get("source_built") is not True
            or not re.fullmatch(r"[0-9a-f]{40,64}", manifest.get("source_sha", ""))
            or type(manifest.get("source_dirty")) is not bool
            or not re.fullmatch(r"v\d+\.\d+\.\d+", manifest.get("node_version", ""))
            or not manifest.get("source_files_sha256")
        ):
            raise Error("Invalid source/build provenance")
        for name, sha in manifest["source_files_sha256"].items():
            if entries.get(name, {}).get("sha256") != sha:
                raise Error("Source provenance differs from artifact bytes")
        if not all(
            path in manifest["source_files_sha256"]
            for path in (BOOTSTRAP, SMOKE, REAL_CORE, OWNED, COLLECTOR, *PROBE_SOURCES)
        ):
            raise Error("Guest bootstrap/session helpers must have working-source provenance")
        if not all(path in manifest["source_files_sha256"] for path in SUITE_SOURCES):
            raise Error("Complete suite source provenance is required")
        for required in (
            BOOTSTRAP,
            SMOKE,
            REAL_CORE,
            OWNED,
            COLLECTOR,
            "bin/node",
            "app/package-lock.json",
            "app/out/main/index.js",
            "app/test/e2e/orca.spec.ts",
            "app/node_modules/electron/path.txt",
            "app/node_modules/electron/dist/electron",
        ):
            if required not in entries or "sha256" not in entries[required]:
                raise Error(f"Missing artifact input: {required}")
    return manifest, digest(manifest_bytes)


def build_artifact(staging, output, *, root=ROOT):
    staging, output = Path(staging).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise Error("Artifact destination exists; never overwrite")
    if staging == root or root in staging.parents or output.is_relative_to(staging):
        raise Error("Use external staging and artifact output outside staging")
    for source in (
        root / BOOTSTRAP,
        root / SMOKE,
        root / REAL_CORE,
        root / OWNED,
        root / COLLECTOR,
        *(root / name for name in PROBE_SOURCES),
    ):
        target = staging / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_symlink() or target.read_bytes() != source.read_bytes():
                raise Error("Staged guest helper differs from working-tree source")
        else:
            shutil.copyfile(source, target)
    source_files = {}
    # Curated staging may omit repository docs and unrelated scripts. Every
    # staged source file is compared to working bytes, including untracked work.
    for path in staging.rglob("*"):
        name = str(path.relative_to(staging))
        safe_name(name)
        if path.is_symlink():
            link_destination(name, os.readlink(path))
            if not path.resolve().is_relative_to(staging):
                raise Error("Staging symlink escapes root")
        elif path.is_file():
            reject_credentials(path.read_bytes(), name)
            original = root / (
                name.removeprefix("engine/") if name.startswith("engine/src/") else name
            )
            if (
                name in (BOOTSTRAP, SMOKE, REAL_CORE, OWNED, COLLECTOR, *PROBE_SOURCES)
                or (
                    name.startswith("app/")
                    and not name.startswith(("app/out/", "app/node_modules/"))
                )
                or name.startswith("engine/src/")
            ):
                if not original.is_file() or original.read_bytes() != path.read_bytes():
                    raise Error(f"Staged source mismatch: {name}")
                source_files[name] = digest(path.read_bytes())
        elif not path.is_dir():
            raise Error("Unsupported staging file")
    node = staging / "bin/node"
    builder = staging / "app/node_modules/electron-vite/bin/electron-vite.js"
    if not node.is_file() or node.is_symlink() or not builder.is_file():
        raise Error("Prepared pinned bin/node and app electron-vite dependencies are required")
    env = {"PATH": f"{node.parent}:/usr/bin:/bin", "HOME": str(staging), "CI": "1"}
    version = subprocess.check_output(
        [str(node), "--version"], env=env, text=True, timeout=10
    ).strip()
    subprocess.run(
        [str(node), str(builder), "build"], cwd=staging / "app", env=env, check=True, timeout=300
    )
    entries = {}
    for path in sorted(staging.rglob("*")):
        name = str(path.relative_to(staging))
        if path.is_symlink():
            entries[name] = {"symlink": os.readlink(path)}
        elif path.is_file():
            entries[name] = {"sha256": digest(path.read_bytes()), "size": path.stat().st_size}
    if MANIFEST in entries:
        raise Error("Staging contains an old manifest")
    manifest = {
        "schema": 1,
        "source_built": True,
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=all"], cwd=root
            )
        ),
        "source_files_sha256": source_files,
        "node_version": version,
        "files": entries,
    }
    data = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path in sorted(staging.rglob("*")):
            archive.add(path, arcname=str(path.relative_to(staging)), recursive=False)
        item = tarfile.TarInfo(MANIFEST)
        item.mode, item.size = 0o600, len(data)
        archive.addfile(item, io.BytesIO(data))
    output.chmod(0o600)
    inspect_archive(output)
    return manifest


def parse_digests(output, expected):
    found = {}
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](/[^\r\n]+)", line)
        if not match or match[2] not in expected or match[2] in found:
            raise Error("Invalid guest digest output")
        found[match[2]] = match[1]
    if found != expected:
        raise Error("Guest uploaded-source digest mismatch")
    return found


def validate_tasks(report, *, real_core_required=False):
    """Require actual Playwright tests, not an empty or stale successful exit."""
    stats = report.get("stats", {})
    if (
        not isinstance(stats.get("expected"), int)
        or stats["expected"] < 1
        or any(stats.get(key) != 0 for key in ("unexpected", "flaky"))
        or report.get("errors")
    ):
        raise Error("Playwright Orca task results failed or are incomplete")
    tests, real_tests, named = [], [], {}

    def visit(suite):
        for spec in suite.get("specs", []):
            tests.extend(spec.get("tests", []))
            if spec.get("title") in TASK_NAMES:
                if spec["title"] in named:
                    raise Error("Duplicate Orca task names")
                named[spec["title"]] = spec.get("tests", [])
            if spec.get("title") == "orca-real-core-services-when-explicitly-provisioned":
                real_tests.extend(spec.get("tests", []))
        for child in suite.get("suites", []):
            visit(child)

    for suite in report.get("suites", []):
        visit(suite)
    if set(named) != set(TASK_NAMES):
        raise Error("Complete seven-task Orca report required, no filtered subset")
    for name in TASK_NAMES[:-1]:
        if not named[name] or any(
            t.get("status") != "expected" or not t.get("results") for t in named[name]
        ):
            raise Error("Required fixture Orca task was skipped or incomplete")
    if (
        not tests
        or not any(test.get("status") == "expected" for test in tests)
        or any(test.get("status") not in ("expected", "skipped") for test in tests)
        or any(
            result.get("status") != "passed"
            for test in tests
            if test.get("status") == "expected"
            for result in test.get("results", [])
        )
    ):
        raise Error("No verified passing Orca tests in report")
    if real_core_required and (
        not real_tests
        or any(test.get("status") != "expected" or not test.get("results") for test in real_tests)
    ):
        raise Error("Bundled real-core lane was skipped or failed")


def run(api, name, artifact, evidence, *, timeout=2100, probe=None):
    if probe not in (None, "electron", "gtk-electron", "native-attach"):
        raise Error("Unsupported focused probe")
    if name not in NAMES:
        raise Error("Orca accepts only Cinnamon, GNOME and KDE lab VMs")
    if not 30 <= timeout <= 2100:
        raise Error("Timeout must be 30..2100 seconds")
    # Freeze bytes before inspection/upload. Concurrent operator edits cannot
    # replace the validated archive between the validation and extraction.
    with tempfile.TemporaryDirectory(prefix="odq-orca-upload-") as temporary:
        frozen = Path(temporary) / "artifact.tar.gz"
        with Path(artifact).open("rb") as source, frozen.open("xb") as output:
            copied = 0
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_BYTES:
                    raise Error("Compressed artifact exceeds size budget")
                output.write(chunk)
        frozen.chmod(0o600)
        return _run(api, name, frozen, evidence, timeout=timeout, probe=probe)


def _run(api, name, artifact, evidence, *, timeout, probe=None):
    manifest, source_digest = inspect_archive(artifact)
    validate_source(manifest)
    if probe and not all(path in manifest["source_files_sha256"] for path in PROBE_SOURCES):
        raise Error("Focused probe requires working-source provenance")
    evidence = Path(evidence).absolute()
    if evidence.exists() or evidence.is_symlink():
        raise Error("Use a new private evidence directory")
    with lab.mutation_lock():
        check = lab.preflight(api, name=name)
        instance = lab.find(check["instances"], name)
        if not instance or lab.owned(instance)["status"] != "Running":
            raise Error("Orca requires the actual running marked/capped VM")
        image = lab.image_spec(name)
        if instance.get("config", {}).get("volatile.base_image") != image["fingerprint"]:
            raise Error("Running VM base image differs from pinned image")
        evidence.mkdir(parents=True, mode=0o700, exist_ok=False)
        evidence.chmod(0o700)
        run_id = uuid.uuid4().hex
        remote = f"/var/tmp/odq-orca-{run_id}"
        desktop = name[4:]
        proof = {
            "schema": 1,
            "kind": "focused-probes-not-qualification" if probe else "orca-qualification",
            "probe": probe,
            "passed": False,
            "instance": name,
            "run_id": run_id,
            "image": image,
            "source": manifest,
            "source_sha256": source_digest,
            "artifact_sha256": digest(Path(artifact).read_bytes()),
            "guest_files_sha256": {},
            "cleanup": "not-started",
        }
        created, launched, failure = False, False, None
        guest_result = None
        try:
            api.run(
                "exec", name, "--", "mkdir", "-m", "0700", "--", remote, capture=True, timeout=30
            )
            created = True
            api.run(
                "file",
                "push",
                str(artifact),
                f"{name}{remote}/artifact.tar.gz",
                "--mode",
                "0600",
                timeout=120,
            )
            parse_digests(
                api.run(
                    "exec",
                    name,
                    "--",
                    "sha256sum",
                    "--",
                    f"{remote}/artifact.tar.gz",
                    capture=True,
                    timeout=30,
                ),
                {f"{remote}/artifact.tar.gz": proof["artifact_sha256"]},
            )
            api.run(
                "exec",
                name,
                "--",
                "tar",
                "--extract",
                "--gzip",
                "--file",
                f"{remote}/artifact.tar.gz",
                "--directory",
                remote,
                "--no-same-owner",
                "--no-same-permissions",
                timeout=120,
            )
            expected = {
                f"{remote}/{path}": sha for path, sha in manifest["source_files_sha256"].items()
            }
            expected[f"{remote}/app/out/main/index.js"] = manifest["files"][
                "app/out/main/index.js"
            ]["sha256"]
            for path, item in manifest["files"].items():
                if "sha256" in item and path.startswith(
                    ("bin/", "app/node_modules/", "engine/site-packages/")
                ):
                    expected[f"{remote}/{path}"] = item["sha256"]
            expected[f"{remote}/{MANIFEST}"] = source_digest
            for start in range(0, len(expected), 200):
                chunk = dict(list(expected.items())[start : start + 200])
                proof["guest_files_sha256"].update(
                    parse_digests(
                        api.run(
                            "exec", name, "--", "sha256sum", "--", *chunk, capture=True, timeout=30
                        ),
                        chunk,
                    )
                )
            try:
                launched = True
                api.run(
                    "exec",
                    name,
                    "--",
                    "python3",
                    f"{remote}/{BOOTSTRAP}",
                    desktop,
                    remote,
                    *(["--probe", probe] if probe else []),
                    capture=True,
                    timeout=timeout,
                )
            except (Error, subprocess.TimeoutExpired) as exc:
                failure = exc  # Collect failure evidence, never replay tasks.
            files = tuple(name for name in FILES if not probe or name != "tasks.json")
            for filename in files:
                target = evidence / filename
                target.touch(mode=0o600, exist_ok=False)
                try:
                    api.run(
                        "file",
                        "pull",
                        f"{name}{remote}/evidence/{filename}",
                        str(target),
                        timeout=60,
                    )
                    target.chmod(0o600)
                except (Error, subprocess.TimeoutExpired) as exc:
                    if failure is None:
                        failure = exc
            guest_result = json.loads((evidence / "guest-proof.json").read_text())
            result = guest_result
            session = result.get("session", {})
            hashes = result.get("evidence_sha256", {})
            if not isinstance(hashes, dict) or len(hashes) > 2000:
                raise Error("Invalid guest evidence inventory")
            if any(filename not in hashes for filename in COLLECTOR_FILES):
                raise Error("Native dialog collector evidence digests are required")
            # Preserve Playwright attachments/traces/screenshots, not just a
            # report that points to files discarded with the guest workdir.
            for filename, sha in hashes.items():
                path = PurePosixPath(filename)
                if (
                    str(path) != filename
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in filename
                    or SECRET_NAME.search(filename)
                    or not re.fullmatch(r"[0-9a-f]{64}", sha)
                    or filename
                    in ("proof.json", "packages.tsv", "session.json", "guest-proof.json")
                    or not (
                        filename in files
                        or (probe and re.fullmatch(r"probe-[a-z0-9-]+\.(?:json|log|png)", filename))
                        or filename.startswith("tasks/")
                        or filename == "guest.png"
                        or re.fullmatch(r"guest-[a-z0-9-]+\.png", filename)
                    )
                ):
                    raise Error("Unsafe or unexpected guest evidence path")
                target = evidence / filename
                if filename not in files:
                    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    target.touch(mode=0o600, exist_ok=False)
                    api.run(
                        "file",
                        "pull",
                        f"{name}{remote}/evidence/{filename}",
                        str(target),
                        timeout=60,
                    )
                    target.chmod(0o600)
                if digest(target.read_bytes()) != sha:
                    raise Error("Pulled guest evidence digest mismatch")
            packages = api.run(
                "exec",
                name,
                "--",
                "dpkg-query",
                "-W",
                "-f=${Package}\t${Version}\n",
                "orca",
                "speech-dispatcher",
                "at-spi2-core",
                "python3-pyatspi",
                capture=True,
                timeout=30,
            )
            if not packages.strip():
                raise Error("Missing guest package versions")
            with (evidence / "packages.tsv").open("x") as output:
                output.write(packages)
            with (evidence / "session.json").open("x") as output:
                output.write(json.dumps(session, indent=2) + "\n")
            for filename in ("packages.tsv", "session.json"):
                (evidence / filename).chmod(0o600)
            if failure is not None:
                raise failure
            if probe:
                focused = json.loads((evidence / "probe-result.json").read_text())
                if (
                    focused.get("passed") is not True
                    or focused.get("kind") != "focused-probes-not-qualification"
                ):
                    raise Error("Focused probes failed; never label as seven-task qualification")
            else:
                validate_tasks(
                    json.loads((evidence / "tasks.json").read_text()),
                    real_core_required=any(
                        path.startswith("engine/src/") for path in manifest["files"]
                    ),
                )
            if (
                result.get("passed") is not True
                or result.get("source_sha256") != source_digest
                or session.get("Type") != ("x11" if desktop == "cinnamon" else "wayland")
                or not result.get("orca_version")
                or result.get("collector_running_during_tasks") is not True
                or result.get("native_dialog_collector", {}).get("type") != "ready"
                or result.get("cleanup", {}).get("uinput_restored") is not True
                or result.get("cleanup", {}).get("descendants_exited") is not True
                or not (evidence / "packages.tsv").stat().st_size
                or not (evidence / "orca-debug.log").stat().st_size
            ):
                raise Error("Guest source/task/session/Orca evidence failed validation")
            proof.update({"passed": True, "result": result, "session": session})
        except (Error, subprocess.TimeoutExpired, OSError, ValueError) as exc:
            failure = exc
            proof["passed"] = False
            proof["error"] = str(exc)
        finally:
            if created:
                try:
                    if launched and (
                        not isinstance(guest_result, dict)
                        or guest_result.get("cleanup", {}).get("owned_children_exited") is not True
                        or guest_result.get("cleanup", {}).get("uinput_restored") is not True
                    ):
                        raise Error(
                            "Guest cleanup unconfirmed; retain remote artifact, "
                            "no replay or process kill"
                        )
                    if (
                        launched
                        and guest_result.get("cleanup", {}).get("descendants_exited") is not True
                    ):
                        raise Error("Guest descendants unconfirmed; retain remote artifact")
                    api.run("exec", name, "--", "rm", "-rf", "--", remote, capture=True, timeout=30)
                    proof["cleanup"] = "confirmed"
                except (Error, subprocess.TimeoutExpired) as exc:
                    proof.update({"cleanup": "unknown", "passed": False, "cleanup_error": str(exc)})
                    if failure is None:
                        failure = exc
            proof["evidence_sha256"] = {
                str(p.relative_to(evidence)): digest(p.read_bytes())
                for p in evidence.rglob("*")
                if p.is_file()
            }
            with (evidence / "proof.json").open("x") as output:
                output.write(json.dumps(proof, indent=2) + "\n")
            (evidence / "proof.json").chmod(0o600)
        if failure is not None:
            raise Error(
                f"Orca qualification failed; evidence at {evidence}: {failure}"
            ) from failure
        return proof


def validate_source(manifest, *, root=ROOT):
    """A self-declared manifest is not authority to execute arbitrary helpers."""
    for name, sha in manifest["source_files_sha256"].items():
        if name.startswith("engine/src/"):
            source = root / name.removeprefix("engine/")
        elif name.startswith("app/") or name in (
            BOOTSTRAP,
            SMOKE,
            REAL_CORE,
            OWNED,
            COLLECTOR,
            *PROBE_SOURCES,
        ):
            source = root / name
        else:
            raise Error("Unexpected executable source provenance")
        if not source.is_file() or source.is_symlink() or digest(source.read_bytes()) != sha:
            raise Error(f"Current source differs from artifact: {name}; rebuild without replay")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--staging", required=True)
    pack.add_argument("--output", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("name", choices=NAMES)
    execute.add_argument("--artifact", required=True)
    execute.add_argument("--evidence", required=True)
    execute.add_argument("--timeout", type=int, default=2100)
    execute.add_argument("--probe", choices=("electron", "gtk-electron", "native-attach"))
    args = parser.parse_args(argv)
    try:
        if args.action == "pack":
            build_artifact(args.staging, args.output)
        else:
            print(
                json.dumps(
                    run(
                        lab.Incus(),
                        args.name,
                        args.artifact,
                        args.evidence,
                        timeout=args.timeout,
                        probe=args.probe,
                    ),
                    indent=2,
                )
            )
        return 0
    except (Error, subprocess.SubprocessError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
