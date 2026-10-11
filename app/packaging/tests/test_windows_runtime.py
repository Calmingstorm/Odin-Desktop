"""Wheel validation, offline spread, pins and transaction boundaries."""
import base64
import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import windows_runtime as runtime
from windows_closure import StageError


def wheel(tmp_path, *, metadata=None, tag="py3-none-any", license=True, data=None):
    files = {
        "a/__init__.py": b"VALUE=1\n",
        "a-1.0.dist-info/METADATA": (metadata or "Name: a\nVersion: 1.0\n").encode(),
        "a-1.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: " + tag + "\n").encode(),
    }
    if license:
        files["a-1.0.dist-info/licenses/LICENSE"] = b"MIT\n"
    if data:
        files[data] = b"payload"
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for name, value in files.items():
        hashed = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()
        writer.writerow([name, "sha256=" + hashed, str(len(value))])
    writer.writerow(["a-1.0.dist-info/RECORD", "", ""])
    files["a-1.0.dist-info/RECORD"] = output.getvalue().encode()
    artifact = tmp_path / "a-1.0-py3-none-any.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    pin = {"name": "a", "version": "1.0", "filename": artifact.name,
           "sha256": runtime.digest(artifact), "size": artifact.stat().st_size,
           "license": "MIT", "provenance": "https://example.org/a", "url": "https://example.org/a.whl"}
    return artifact, pin


def test_verified_wheel_spread(tmp_path):
    artifact, pin = wheel(tmp_path)
    evidence = runtime.inspect_wheel(artifact, pin, [pin])
    assert evidence["license_files"]
    site, scratch = tmp_path / "site", tmp_path / "scratch"
    site.mkdir()
    scratch.mkdir()
    runtime.install_wheel(artifact, pin, site, scratch)
    assert (site / "a/__init__.py").read_bytes() == b"VALUE=1\n"
    with pytest.raises(StageError, match="install_collision"):
        runtime.install_wheel(artifact, pin, site, tmp_path / "scratch2")


@pytest.mark.parametrize("kwargs,code", [
    ({"metadata": "Name: other\nVersion: 1.0\n"}, "wheel_metadata"),
    ({"metadata": "Name: a\nVersion: 2.0\n"}, "wheel_metadata"),
    ({"tag": "cp312-cp312-win32"}, "wheel_tag_mismatch"),
    ({"license": False}, "license_missing"),
    ({"metadata": "Name: a\nVersion: 1.0\nRequires-Dist: missing>=1\n"},
     "metadata_dependency_mismatch"),
    ({"metadata": "Name: a\nVersion: 1.0\nRequires-Dist: a @ https://example.org/a.whl\n"},
     "metadata_dependency_mismatch"),
])
def test_wheel_metadata_refusals(tmp_path, kwargs, code):
    artifact, pin = wheel(tmp_path, **kwargs)
    with pytest.raises(StageError) as error:
        runtime.inspect_wheel(artifact, pin, [pin])
    assert error.value.code == code
    assert error.value.package == "a"


def test_ignored_platform_requires_dist(tmp_path):
    artifact, pin = wheel(
        tmp_path, metadata="Name: a\nVersion: 1.0\n"
        "Requires-Dist: absent; sys_platform == 'linux'\n")
    runtime.inspect_wheel(artifact, pin, [pin])


def test_record_tampering(tmp_path):
    artifact, pin = wheel(tmp_path)
    with zipfile.ZipFile(artifact) as source:
        files = {n: source.read(n) for n in source.namelist()}
    files["a/__init__.py"] = b"altered"
    with zipfile.ZipFile(artifact, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    pin.update(sha256=runtime.digest(artifact), size=artifact.stat().st_size)
    with pytest.raises(StageError, match="wheel_record"):
        runtime.inspect_wheel(artifact, pin, [pin])


@pytest.mark.parametrize("scheme", ["scripts", "data"])
def test_unexpected_install_scheme(tmp_path, scheme):
    artifact, pin = wheel(tmp_path, data=f"a-1.0.data/{scheme}/payload")
    site = tmp_path / "site"
    site.mkdir()
    with pytest.raises(StageError, match="wheel_layout"):
        runtime.install_wheel(artifact, pin, site, tmp_path / "scratch")
    assert not list(site.iterdir())


def test_header_scheme_explicitly_omitted_and_recorded(tmp_path):
    artifact, pin = wheel(tmp_path, data="a-1.0.data/headers/a.h")
    site = tmp_path / "site"
    site.mkdir()
    omitted = runtime.install_wheel(artifact, pin, site, tmp_path / "scratch")
    assert omitted == ["a-1.0.data/headers/a.h"]
    assert not list(site.rglob("*.h"))


@pytest.mark.parametrize("change,code", [("hash", "artifact_hash"), ("size", "artifact_size"),
                                       ("license", "pin_missing"), ("provenance", "pin_missing")])
def test_cache_is_reverified(tmp_path, change, code):
    artifact, pin = wheel(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / pin["sha256"]).write_bytes(artifact.read_bytes())
    if change == "hash":
        value = bytearray(artifact.read_bytes())
        value[0] ^= 1
        (cache / pin["sha256"]).write_bytes(value)
    elif change == "size":
        pin["size"] += 1
    else:
        del pin[change]
    with pytest.raises(StageError, match=code):
        runtime.verified_download(pin, cache, "a")


def test_wrong_host_no_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    with pytest.raises(StageError, match="wrong_os"):
        runtime.stage_windows_runtime(tmp_path, tmp_path / "out", tmp_path / "cache")
    assert not (tmp_path / "out").exists()


def test_previous_stage_no_refresh_or_mix(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "AMD64")
    previous = tmp_path / "out/python"
    previous.mkdir(parents=True)
    (previous / "sentinel").write_text("unchanged")
    with pytest.raises(StageError, match="previous_stage"):
        runtime.stage_windows_runtime(tmp_path, previous.parent, tmp_path / "cache")
    assert (previous / "sentinel").read_text() == "unchanged"


def test_native_environment_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/bad")
    monkeypatch.setenv("PYTHONHOME", "/bad")
    monkeypatch.setenv("PATH", "/bad")
    env = runtime.native_environment(tmp_path)
    assert not {"PYTHONPATH", "PYTHONHOME"} & env.keys()
    assert env["PATH"].endswith("System32")


def test_actual_runtime_lock_and_pip():
    import tomllib
    repo = Path(__file__).resolve().parents[3]
    spec = json.loads((repo / "app/packaging/runtime-lock.win_amd64.json").read_text())
    lock = tomllib.loads((repo / "uv.lock").read_text())
    project = tomllib.loads((repo / "pyproject.toml").read_text())["project"]
    closure = runtime.production_closure(lock, project)
    runtime.validate_lock(spec, closure)
    del spec["pip"]
    with pytest.raises(StageError, match="pin_missing"):
        runtime.validate_lock(spec, closure)


def test_partial_native_failure_has_no_published_python(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(runtime, "verified_download", lambda *args: tmp_path / "artifact")

    def extract(artifact, target, **kwargs):
        (target / "python/Lib").mkdir(parents=True)
        (target / "python/python.exe").write_bytes(b"fixture")

    monkeypatch.setattr(runtime, "extract_archive", extract)
    monkeypatch.setattr(runtime, "native_run", lambda *args: "0.0.0")
    dest = tmp_path / "out"
    with pytest.raises(StageError, match="python_abi"):
        runtime.stage_windows_runtime(repo, dest, tmp_path / "cache")
    assert not (dest / "python").exists()
    assert list(dest.iterdir()) == []


def test_wrong_architecture_no_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "ARM64")
    with pytest.raises(StageError, match="wrong_arch"):
        runtime.stage_windows_runtime(tmp_path, tmp_path / "out", tmp_path / "cache")
    assert not (tmp_path / "out").exists()


def test_development_backend_absent_refuses_structurally(tmp_path):
    with pytest.raises(StageError, match="backend_pin"):
        runtime.build_engine(tmp_path, tmp_path / "python.exe", tmp_path,
                             {"package": []}, {"name": "engine"}, tmp_path, [])


def test_lock_metadata_missing_edge_refused(tmp_path):
    artifact, pin = wheel(tmp_path)
    pin["selected_dependencies"] = ["b"]
    with pytest.raises(StageError, match="metadata_dependency_mismatch"):
        runtime.inspect_wheel(artifact, pin, [pin])


def test_wrong_requires_python_refused(tmp_path):
    artifact, pin = wheel(tmp_path, metadata="Name: a\nVersion: 1.0\nRequires-Python: >=3.13\n")
    with pytest.raises(StageError, match="python_abi"):
        runtime.inspect_wheel(artifact, pin, [pin])


@pytest.mark.parametrize("path", ["a.pth", "sitecustomize.py", "usercustomize.py",
                                  "a-1.0.dist-info/direct_url.json"])
def test_python_path_injection_refused(tmp_path, path):
    artifact, pin = wheel(tmp_path, data=path)
    with pytest.raises(StageError, match="python_path_injection"):
        runtime.inspect_wheel(artifact, pin, [pin])


def test_malformed_wheel_filename_refuses_structurally(tmp_path):
    artifact, pin = wheel(tmp_path)
    pin["filename"] = "not-a-wheel.zip"
    with pytest.raises(StageError, match="wheel_name_invalid"):
        runtime.inspect_wheel(artifact, pin, [pin])


def test_actual_locked_playwright_supplier_tag_discrepancy_refused(tmp_path):
    """Inspect real pinned supplier bytes, not a synthetic mismatched fixture."""
    import tomllib
    repo = Path(__file__).resolve().parents[3]
    lock = tomllib.loads((repo / "uv.lock").read_text())
    project = tomllib.loads((repo / "pyproject.toml").read_text())["project"]
    closure = runtime.production_closure(lock, project)
    pin = next(p for p in closure if p["name"] == "playwright")
    local = repo / ".packaging-cache/windows-python/artifacts" / pin["sha256"]
    artifact = (runtime.verified_download(pin, local.parent, "playwright") if local.exists()
                else runtime.verified_download(pin, tmp_path / "artifacts", "playwright"))
    assert pin["filename"] == "playwright-1.63.0-py3-none-win_amd64.whl"
    with zipfile.ZipFile(artifact) as archive:
        metadata_path = next(n for n in archive.namelist() if n.endswith(".dist-info/WHEEL"))
        assert b"Tag: py3-none-any" in archive.read(metadata_path)
    with pytest.raises(StageError) as caught:
        runtime.inspect_wheel(artifact, pin, closure)
    assert caught.value.code == "wheel_tag_mismatch"
    assert caught.value.package == "playwright"
    assert caught.value.path == pin["filename"]


def test_foreign_supplier_payloads_named_pruning(tmp_path):
    launchers = tmp_path / "pip/_vendor/distlib"
    launchers.mkdir(parents=True)
    for name in ("w32.exe", "t32.exe", "w64-arm.exe", "t64-arm.exe", "w64.exe", "t64.exe"):
        (launchers / name).write_bytes(b"fixture")
    scripts = tmp_path / "playwright/driver/package/bin"
    scripts.mkdir(parents=True)
    (scripts / "install_linux.sh").write_text("fixture")
    (scripts / "install_win.ps1").write_text("fixture")
    records = runtime.prune_foreign_payloads(tmp_path)
    assert len(records) == 5
    assert (launchers / "w64.exe").exists() and (launchers / "t64.exe").exists()
    assert (scripts / "install_win.ps1").exists()
    assert all(len(record["sha256"]) == 64 for record in records)
