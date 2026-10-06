"""Pinned Chromium input and extraction behaviour, without live services."""
import hashlib
import importlib.util
import json
import stat
import zipfile
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "app/packaging/python/chromium.py"
spec = importlib.util.spec_from_file_location("chromium_staging", MODULE)
chromium = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chromium)


def test_cached_hash_mismatch_fails_without_download(tmp_path, monkeypatch):
    (tmp_path / "browser.zip").write_bytes(b"corrupt")
    monkeypatch.setattr(
        chromium.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("download attempted")
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        chromium._cached({"sha256": "0" * 64}, tmp_path, "browser.zip")


def test_verified_cache_is_offline(tmp_path, monkeypatch):
    archive = tmp_path / "browser.zip"
    archive.write_bytes(b"verified")
    monkeypatch.setattr(
        chromium.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("download attempted")
    )
    digest = {"sha256": chromium._sha256(archive)}
    assert chromium._cached(digest, tmp_path, archive.name) == archive


@pytest.mark.parametrize("name,mode", [
    ("../escape", stat.S_IFREG | 0o644), ("/absolute", stat.S_IFREG | 0o644),
    ("chrome/../escape", stat.S_IFREG | 0o644), ("wrong/file", stat.S_IFREG | 0o644),
    ("chrome/link", stat.S_IFLNK | 0o777), ("chrome/socket", stat.S_IFSOCK | 0o777),
])
def test_extract_rejects_unsafe_members(tmp_path, name, mode):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        member = zipfile.ZipInfo(name)
        member.external_attr = mode << 16
        output.writestr(member, b"harmless")
    with pytest.raises(ValueError, match="Unsafe Chromium archive member"):
        chromium._extract(archive, tmp_path / "out", "chrome")


def test_extract_preserves_executable_but_not_setuid(tmp_path):
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive, "w") as output:
        member = zipfile.ZipInfo("chrome/executable")
        member.external_attr = (stat.S_IFREG | 0o4755) << 16
        output.writestr(member, b"test")
    chromium._extract(archive, tmp_path / "out", "chrome")
    assert (tmp_path / "out/chrome/executable").stat().st_mode & 0o7777 == 0o755


def test_playwright_lock_mismatch(tmp_path):
    uv = tmp_path / "uv.lock"
    uv.write_text('[[package]]\nname="playwright"\nversion="0.0.0"\nwheels=[]\n')
    lock = json.loads(chromium.LOCK_PATH.read_text())
    with pytest.raises(ValueError, match="does not match uv.lock"):
        chromium._validate_playwright(lock, uv, tmp_path / "unused.whl")


def test_complete_stage_offline_matches_lock_and_modes(tmp_path, monkeypatch):
    cache = tmp_path / "cache/chromium"
    cache.mkdir(parents=True)
    wheel = cache / "playwright-1.63.0.whl"
    with zipfile.ZipFile(wheel, "w") as output:
        output.writestr("playwright/driver/package/browsers.json", json.dumps({"browsers": [
            {"name": "chromium-headless-shell", "revision": "1243",
             "browserVersion": "153.0.8010.12"}
        ]}))
    archive = cache / "chrome-headless-shell-linux64-153.0.8010.12.zip"
    with zipfile.ZipFile(archive, "w") as output:
        member = zipfile.ZipInfo("chrome-headless-shell-linux64/chrome-headless-shell")
        member.external_attr = (stat.S_IFREG | 0o755) << 16
        output.writestr(member, b"not executed")
        output.writestr("chrome-headless-shell-linux64/LICENSE.headless_shell", b"license")
    lock = json.loads(chromium.LOCK_PATH.read_text())
    lock["playwright"]["sha256"] = chromium._sha256(wheel)
    lock["chromium"]["sha256"] = chromium._sha256(archive)
    lock["chromium"]["license_sha256"] = hashlib.sha256(b"license").hexdigest()
    pin = tmp_path / "chromium.lock.json"
    pin.write_text(json.dumps(lock))
    uv = tmp_path / "uv.lock"
    uv.write_text('[[package]]\nname="playwright"\nversion="1.63.0"\nwheels=[{url=' +
                  json.dumps(lock["playwright"]["url"]) + ',hash="sha256:' +
                  lock["playwright"]["sha256"] + '"}]\n')
    monkeypatch.setattr(chromium, "LOCK_PATH", pin)
    monkeypatch.setattr(chromium, "REPOSITORY", tmp_path)
    monkeypatch.setattr(
        chromium.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("download attempted")
    )
    root = tmp_path / "runtime with spaces"
    metadata = chromium.stage_chromium(root, tmp_path / "cache")
    assert (root / metadata["executable"]).read_bytes() == b"not executed"
    assert (root / "browser/chromium").stat().st_mode & 0o777 == 0o755
    assert metadata["sandbox_required"] is True
    assert metadata["files"] == 2
    assert chromium.stage_chromium(root, tmp_path / "cache") == metadata
    (root / metadata["executable"]).write_bytes(b"corrupt staged resource")
    with pytest.raises(ValueError, match="Existing Chromium resource mismatch"):
        chromium.stage_chromium(root, tmp_path / "cache")
