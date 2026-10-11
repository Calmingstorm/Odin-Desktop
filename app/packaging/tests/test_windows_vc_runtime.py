"""Offline MSVC staging safety; live pin validation is an explicit separate check."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import windows_vc_runtime as vc
import windows_runtime as runtime
from windows_archive import ArchiveSafetyError
from windows_closure import StageError
from windows_dll import DLLAuditError
from test_windows_dll import pe_bytes


def fixture(tmp_path, monkeypatch, *, machine=0x8664, extra=None, missing=False,
            wrong_manifest=False, altered=False):
    pin = vc._load_pin()
    files = {}
    for item in pin["files"]:
        data = pe_bytes(imports=["kernel32.dll"], machine=machine)
        item.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        files[pin["release_root"] + "/" + item["filename"]] = data
    manifest = {"id": "wrong" if wrong_manifest else pin["name"], "version": pin["version"],
                "files": [{"fileName": "/" + path, "sha256": hashlib.sha256(data).hexdigest()}
                          for path, data in files.items()]}
    if missing:
        files.pop(next(iter(files)))
    if altered:
        path = next(iter(files))
        files[path] = files[path][:-1] + b"X"
    files["manifest.json"] = json.dumps(manifest).encode()
    if extra:
        files[extra] = b"forbidden"
    archive = tmp_path / "fixture.vsix"
    with zipfile.ZipFile(archive, "w") as opened:
        for name, data in files.items():
            opened.writestr(name, data)
    pin.update(size=archive.stat().st_size, sha256=runtime.digest(archive))
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(pin))
    monkeypatch.setattr(vc, "LOCK", lock)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / pin["sha256"]).write_bytes(archive.read_bytes())
    root = tmp_path / "python"
    root.mkdir()
    (root / "python.exe").write_bytes(pe_bytes())
    (root / "vcruntime140.dll").write_bytes(b"CPython owned")
    return root, cache, pin


def test_exact_stage_no_installer_no_host_dlls(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch,
                               extra="Contents/VC/Redist/debug_nonredist/msvcp140d.dll")
    monkeypatch.setenv("PATH", str(tmp_path / "do-not-use"))
    def no_network(*args, **kwargs):
        pytest.fail("offline verified cache must not access network")
    monkeypatch.setattr(runtime.urllib.request, "urlopen", no_network)
    evidence = vc.stage_vc_runtime(root, cache)
    assert {p.name for p in root.iterdir()} == vc.REQUIRED | {"python.exe", "vcruntime140.dll"}
    assert (root / "vcruntime140.dll").read_bytes() == b"CPython owned"
    assert {f["destination"] for f in evidence["files"]} == vc.REQUIRED
    assert all(f["machine"] == "AMD64" for f in evidence["files"])
    assert evidence["license_prerequisite_verified"] is False
    assert evidence["license_blockers"]
    assert evidence["installer_executed"] is False and evidence["host_dll_copies"] is False
    assert evidence["native_qualification"].startswith("pending")
    assert not list(tmp_path.glob(".vc-runtime-*"))


@pytest.mark.parametrize("kwargs,code", [
    ({"extra": "../escape"}, "path_traversal"),
    ({"extra": "Contents/CON.dll"}, "reserved_device"),
    ({"extra": "Contents/file:stream"}, "alternate_data_stream"),
    ({"missing": True}, "vc_runtime_path"),
    ({"wrong_manifest": True}, "vc_runtime_manifest"),
    ({"altered": True}, "artifact_hash"),
    ({"machine": 0x14C}, "wrong_machine"),
])
def test_bad_payload_never_adds_dlls(tmp_path, monkeypatch, kwargs, code):
    root, cache, pin = fixture(tmp_path, monkeypatch, **kwargs)
    with pytest.raises((StageError, ArchiveSafetyError, DLLAuditError)) as caught:
        vc.stage_vc_runtime(root, cache)
    assert caught.value.code == code
    assert not any((root / name).exists() for name in vc.REQUIRED)
    assert (root / "vcruntime140.dll").read_bytes() == b"CPython owned"


@pytest.mark.parametrize("name", ["MSVCP140.DLL", "msvcp140_1.dll"])
def test_existing_case_alias_no_merge(tmp_path, monkeypatch, name):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    (root / name).write_bytes(b"old stage")
    with pytest.raises(StageError, match="install_collision"):
        vc.stage_vc_runtime(root, cache)
    assert (root / name).read_bytes() == b"old stage"


def test_symlink_destination_refused(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    alias = tmp_path / "linked"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("fixture host cannot create links")
    with pytest.raises(StageError, match="vc_runtime_path"):
        vc.stage_vc_runtime(alias, cache)
    assert not (root / "msvcp140.dll").exists()


def test_copy_failure_rolls_back_only_own_files(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    original = vc.shutil.copyfileobj
    calls = 0
    def failing_copy(source, dest, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            dest.write(b"partial")
            raise OSError("disk full")
        return original(source, dest, *args, **kwargs)
    # Extractor shares shutil: fail only output files that belong to the stage.
    def scoped_copy(source, dest, *args, **kwargs):
        if Path(dest.name).parent == root:
            return failing_copy(source, dest, *args, **kwargs)
        return original(source, dest, *args, **kwargs)
    monkeypatch.setattr(vc.shutil, "copyfileobj", scoped_copy)
    with pytest.raises(OSError, match="disk full"):
        vc.stage_vc_runtime(root, cache)
    assert not any((root / name).exists() for name in vc.REQUIRED)
    assert (root / "vcruntime140.dll").read_bytes() == b"CPython owned"


@pytest.mark.parametrize("field", ["license", "provenance", "license_documents",
                                   "redistribution_conditions", "license_blockers"])
def test_provenance_and_license_required(tmp_path, monkeypatch, field):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    pin.pop(field)
    vc.LOCK.write_text(json.dumps(pin))
    with pytest.raises(StageError):
        vc.stage_vc_runtime(root, cache)
    assert not (root / "msvcp140.dll").exists()


def test_cache_hash_is_reverified(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    artifact = cache / pin["sha256"]
    artifact.write_bytes(b"X" + artifact.read_bytes()[1:])
    with pytest.raises(StageError, match="artifact_hash"):
        vc.stage_vc_runtime(root, cache)
    assert not (root / "msvcp140.dll").exists()


def test_cache_symlink_refused(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    linked = tmp_path / "linked-cache"
    try:
        linked.symlink_to(cache, target_is_directory=True)
    except OSError:
        pytest.skip("fixture host cannot create links")
    with pytest.raises(StageError, match="vc_runtime_path"):
        vc.stage_vc_runtime(root, linked)
    assert not (root / "msvcp140.dll").exists()


def test_inner_size_refused(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    pin["files"][0]["size"] += 1
    vc.LOCK.write_text(json.dumps(pin))
    with pytest.raises(StageError, match="artifact_size"):
        vc.stage_vc_runtime(root, cache)
    assert not (root / "msvcp140.dll").exists()


def test_file_set_refused(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    pin["files"].append({"filename": "msvcp140d.dll", "sha256": "0" * 64, "size": 1})
    vc.LOCK.write_text(json.dumps(pin))
    with pytest.raises(StageError, match="vc_runtime_files"):
        vc.stage_vc_runtime(root, cache)
    assert not (root / "msvcp140.dll").exists()


def test_snapshot_lock_override(tmp_path, monkeypatch):
    root, cache, pin = fixture(tmp_path, monkeypatch)
    snapshot_lock = vc.LOCK
    monkeypatch.setattr(vc, "LOCK", tmp_path / "missing-default.json")
    report = vc.stage_vc_runtime(root, cache, lock_path=snapshot_lock)
    assert report["sha256"] == pin["sha256"]
