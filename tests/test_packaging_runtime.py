"""Runtime staging safety behaviour without real services or desktop state."""
import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "packaging_runtime", Path(__file__).parents[1] / "app/packaging/python/runtime.py"
)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def archive_at(tmp_path, entries):
    archive = tmp_path / "input.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, kind, value in entries:
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = value
                tar.addfile(info)
            elif kind == "device":
                info.type = tarfile.CHRTYPE
                tar.addfile(info)
            else:
                data = value.encode()
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return archive


@pytest.mark.parametrize("entries", [
    [("python/good", "file", "ok"), ("../escaped", "file", "bad")],
    [("/python/absolute", "file", "bad")],
    [("python/good", "file", "1"), ("python/good", "file", "2")],
    [("python/link", "link", "/etc/passwd")],
    [("python/link", "link", "../../escaped")],
    [("python/link", "link", "inside"), ("python/link/child", "file", "bad")],
    [("python/device", "device", "")],
    [("wrong-prefix/file", "file", "bad")],
])
def test_tar_rejected_before_first_write(tmp_path, entries):
    archive = archive_at(tmp_path, entries)
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError):
        runtime._extract_tar(archive, output, "python")
    assert list(output.iterdir()) == []


def test_internal_symlink_and_spaces_relocate(tmp_path):
    archive = archive_at(tmp_path, [("python/bin/python3.12", "file", "binary"),
                                    ("python/bin/python3", "link", "python3.12")])
    output = tmp_path / "path with spaces"
    output.mkdir()
    runtime._extract_tar(archive, output, "python")
    moved = tmp_path / "another relocated directory"
    output.rename(moved)
    assert (moved / "python/bin/python3").read_text() == "binary"


def test_corrupt_download_cache_fails_closed(tmp_path):
    digest = hashlib.sha256(b"correct").hexdigest()
    (tmp_path / digest).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Corrupt cached"):
        runtime._download({"sha256": digest, "url": "https://invalid.example"}, tmp_path)


def test_hashed_download_cache_needs_no_network(tmp_path, monkeypatch):
    digest = hashlib.sha256(b"correct").hexdigest()
    (tmp_path / digest).write_bytes(b"correct")
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    assert runtime._download({"sha256": digest}, tmp_path).read_bytes() == b"correct"


def test_wheel_inventory_hash_and_license(tmp_path):
    wheel = tmp_path / "example-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example-1.dist-info/METADATA",
                         "Name: example\nVersion: 1\nLicense-Expression: MIT\n")
        archive.writestr("example-1.dist-info/licenses/LICENSE", "license bytes")
    digest = runtime.sha256(wheel)
    lock = {"package": [{"name": "example", "version": "1", "wheels": [
        {"hash": f"sha256:{digest}", "url": "https://example.invalid/example.whl"}]}]}
    inventory = runtime._wheel_inventory(tmp_path, lock)
    assert inventory[0]["license_expression"] == "MIT"
    expected = hashlib.sha256(b"license bytes").hexdigest()
    assert inventory[0]["license_files"][0]["sha256"] == expected
    wheel.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="absent from uv.lock"):
        runtime._wheel_inventory(tmp_path, lock)


def test_stage_rejects_existing_wrong_lock(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "python").mkdir(parents=True)
    (bundle / "python/runtime-metadata.json").write_text(json.dumps({"uv_lock_sha256": "wrong"}))
    monkeypatch.setattr(runtime, "refresh_engine", lambda *a: pytest.fail("refresh"))
    with pytest.raises(ValueError, match="lock changed"):
        runtime.stage_runtime(bundle, tmp_path / "cache")
