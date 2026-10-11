"""Pure host tests for the sealed Windows consumer paths and trust policy."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.desktop import browser_runtime
from src.desktop.platform import windows_payloads

ROOT = Path(__file__).resolve().parents[1]


def load_windows(monkeypatch, name):
    # Do not import native win32 on Linux. Only these consumers' process seams stub.
    fake = ModuleType("src.desktop.platform.windows_exec")
    fake.ps_quote = lambda text: "'" + str(text).replace("'", "''") + "'"
    fake.release = lambda running: None
    fake.spawn = AsyncMock()
    fake.terminate = AsyncMock()
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    fullname = f"src.desktop.platform.{name}"
    path = ROOT / "src/desktop/platform" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(fullname, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def resources(tmp_path, monkeypatch):
    root = tmp_path / "resources with spaces"
    for relative in ("tools/curl/curl.exe", "tools/curl/curl-ca-bundle.crt",
                     "tools/openssh/ssh.exe"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    (root / "runtime").mkdir()
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(root / "runtime"))
    return root


def test_payload_is_install_relative_and_missing_never_falls_back(resources):
    expected = resources / "tools/openssh/ssh.exe"
    assert windows_payloads.packaged_file("tools/openssh/ssh.exe") == expected
    with pytest.raises(FileNotFoundError, match="ssh-keygen.exe"):
        windows_payloads.packaged_file("tools/openssh/ssh-keygen.exe")


def test_payload_source_and_bad_roots(monkeypatch):
    monkeypatch.delenv("ODIN_DESKTOP_BUNDLE_ROOT", raising=False)
    assert windows_payloads.packaged_file("tools/curl/curl.exe") is None
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", "relative")
    with pytest.raises(ValueError, match="absolute"):
        windows_payloads.packaged_root()


def test_payload_reparse_alias_refused(resources, tmp_path):
    path = resources / "tools/curl/curl.exe"
    path.unlink()
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"fixture")
    path.symlink_to(outside)
    with pytest.raises(FileNotFoundError, match="reparse alias"):
        windows_payloads.packaged_file("tools/curl/curl.exe")


def test_pinned_ca_policy_and_environment(resources, monkeypatch):
    monkeypatch.setenv("CURL_CA_BUNDLE", "/untrusted")
    monkeypatch.setenv("SSL_CERT_FILE", "/untrusted")
    monkeypatch.setenv("ssl_cert_dir", "/untrusted")
    ca = resources / "tools/curl/curl-ca-bundle.crt"
    assert windows_payloads.curl_policy_args() == ["--disable", "--no-ca-native", "--cacert",
                                                 str(ca)]
    assert not any(key.upper() in {"CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR"}
                   for key in windows_payloads.curl_environment())
    (resources / "tools/curl/curl-ca-bundle.crt").unlink()
    with pytest.raises(FileNotFoundError, match="curl-ca-bundle.crt"):
        windows_payloads.curl_policy_args()


@pytest.mark.asyncio
async def test_http_probe_uses_pinned_binary_and_ca(resources, monkeypatch):
    helper = load_windows(monkeypatch, "windows_helpers")
    helper.run_argv = AsyncMock(return_value=(0, "fixture"))
    executor = SimpleNamespace(config=SimpleNamespace(command_timeout_seconds=10), bulkheads={})
    result = await helper.probe(executor, "127.0.0.1", "curl -sS https://example.com", "test")
    assert result == (0, "fixture")
    argv, timeout = helper.run_argv.call_args.args
    assert argv[:5] == [str(resources / "tools/curl/curl.exe"), "--disable",
                        "--no-ca-native", "--cacert",
                        str(resources / "tools/curl/curl-ca-bundle.crt")]
    assert "--insecure" not in argv
    assert timeout == 10


def test_validation_uses_same_install_relative_tls_policy(resources, monkeypatch):
    helper = load_windows(monkeypatch, "windows_helpers")
    monkeypatch.setitem(sys.modules, "src.desktop.platform.windows_helpers", helper)
    validation = load_windows(monkeypatch, "windows_validate")
    check = SimpleNamespace(type="http", target="https://example.com", timeout_seconds=10)
    result = validation.windows_probe(check)
    assert str(resources / "tools/curl/curl.exe") in result
    assert "'--disable' '--no-ca-native' '--cacert'" in result
    assert "System32" not in result
    assert "Env:CURL_CA_BUNDLE" in result
    assert "--insecure" not in result


def test_windows_browser_only_pinned_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_runtime.sys, "platform", "win32")
    root = tmp_path / "resources"
    path = root / "runtime/browser/chromium/chrome-headless-shell-win64/chrome-headless-shell.exe"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture")
    assert browser_runtime.resolve_bundled_chromium(root) == path
    path.unlink()
    (path.parent / "chrome.exe").write_bytes(b"not pinned")
    with pytest.raises(RuntimeError, match="Chromium .exe is missing"):
        browser_runtime.resolve_bundled_chromium(root)


def test_bundled_interpreter_proves_root_without_env(resources, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(resources / "runtime/python"))
    monkeypatch.delenv("ODIN_DESKTOP_BUNDLE_ROOT")
    assert windows_payloads.packaged_root() == resources
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(resources / "wrong"))
    with pytest.raises(ValueError, match="does not match interpreter"):
        windows_payloads.packaged_root()


@pytest.mark.asyncio
async def test_probe_missing_ca_fails_no_dispatch(resources, monkeypatch):
    helper = load_windows(monkeypatch, "windows_helpers")
    helper.run_argv = AsyncMock()
    (resources / "tools/curl/curl-ca-bundle.crt").unlink()
    executor = SimpleNamespace(config=SimpleNamespace(command_timeout_seconds=10), bulkheads={})
    code, text = await helper.probe(executor, "127.0.0.1", "curl https://example.com", "test")
    assert code == 1 and "curl-ca-bundle.crt" in text
    helper.run_argv.assert_not_called()


@pytest.mark.parametrize("variable", ["PLAYWRIGHT_NODEJS_PATH", "NODE_OPTIONS", "NODE_PATH"])
def test_windows_driver_override_refused(tmp_path, monkeypatch, variable):
    monkeypatch.setenv(variable, "external")
    with pytest.raises(RuntimeError, match="overrides are refused"):
        browser_runtime.validate_windows_driver(tmp_path)


def test_windows_driver_install_relative_only(tmp_path, monkeypatch):
    import importlib.util

    package = tmp_path / "python/Lib/site-packages/playwright"
    (package / "driver").mkdir(parents=True)
    origin = package / "__init__.py"
    origin.write_bytes(b"")
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name: SimpleNamespace(origin=str(origin)))
    (package / "driver/node.exe").write_bytes(b"fixture")
    browser_runtime.validate_windows_driver(tmp_path)
    with pytest.raises(RuntimeError, match="node.exe is missing"):
        browser_runtime.validate_windows_driver(tmp_path / "elsewhere")


def test_openssh_packaged_path_and_no_machine_fallback(resources, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    win32 = ModuleType("src.desktop.platform.win32")
    files = ModuleType("src.desktop.platform.windows_files")
    files.user_sid = lambda: "fixture"
    monkeypatch.setitem(sys.modules, win32.__name__, win32)
    monkeypatch.setitem(sys.modules, files.__name__, files)
    ssh = load_windows(monkeypatch, "windows_ssh")
    assert ssh.openssh("ssh") == str(resources / "tools/openssh/ssh.exe")
    with pytest.raises(FileNotFoundError, match="ssh-keygen.exe"):
        ssh.openssh("ssh-keygen")
    with pytest.raises(ValueError, match="not an OpenSSH"):
        ssh.openssh("sshd")
