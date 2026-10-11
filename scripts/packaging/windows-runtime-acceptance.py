#!/usr/bin/env python3
"""Private phase-4a staged-runtime qualification, not installer/Legion acceptance.

The controller copies this script outside the checkout and invokes each consumer
with the staged interpreter's -I flag and cold, private paths. No desktop input,
services, root certificates, or existing profiles are changed.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import http.server
import importlib.util
import json
import math
import ntpath
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace


def cold_environment(work: Path, resources: Path, ambient: dict[str, str]) -> dict[str, str]:
    system = ambient.get("SystemRoot", r"C:\Windows")
    # Windows' own machine-wide settings stay; every real session defines them and the app's core
    # inherits them. Without PATHEXT PowerShell takes curl.exe for a document and won't run it in
    # a pipeline; without ProgramData the bundled OpenSSH exits 255 before doing anything.
    env = {key: ambient[key] for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT",
                                         "ProgramData", "ALLUSERSPROFILE", "SystemDrive")
           if key in ambient}
    env.update({
        "PATH": str(Path(system) / "System32"),
        "USERPROFILE": str(work / "home"), "HOME": str(work / "home"),
        "LOCALAPPDATA": str(work / "local"), "APPDATA": str(work / "roaming"),
        "TEMP": str(work / "temp"), "TMP": str(work / "temp"),
        "HF_HOME": str(work / "hf"), "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1", "PLAYWRIGHT_BROWSERS_PATH": str(work / "no-browser-cache"),
        "ODIN_DESKTOP_BUNDLE_ROOT": str(resources / "runtime"),
        "ODIN_DESKTOP_PROFILE": "runtime-acceptance",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def profile_environment(work: Path, resources: Path, ambient: dict[str, str]) -> dict[str, str]:
    """The cold environment with one difference: the account's real profile folders, as the app's
    core runs with them. Comparing the two isolates what a fabricated empty profile costs."""
    env = cold_environment(work, resources, ambient)
    profile = ("USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA")
    env.update({key: ambient[key] for key in profile if key in ambient})
    return env


# The product's default validation timeout: a first call must finish inside it.
FIRST_CALL_DEADLINE = 20
# curl exits for a failed connection itself (resolve, connect, TLS handshake, timeout, reset).
CONNECTION_FAILURES = frozenset({6, 7, 28, 35, 52, 56})


def digest_tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def installed(module):
    path = Path(module.__file__).resolve()
    if not path.is_relative_to(Path(sys.prefix).resolve()):
        raise AssertionError(f"module escaped staged interpreter: {module.__name__}: {path}")


# Native evidence a static DLL audit can't give: the modules each process actually loaded, and
# Chromium's process tokens. A developer machine's own redistributable (the VC++ runtime,
# OpenSSL) would mask a missing bundled copy, so one loaded from outside the bundle fails.
REDISTRIBUTABLE = re.compile(r"^((msvcp|vcruntime|concrt|vccorlib|vcomp|vcamp|mfc|atl|msvcr)"
                             r"\d+[a-z0-9_]*|libcrypto.*|libssl.*)\.dll$", re.IGNORECASE)
SANDBOXED_LEVELS = {"S-1-16-0": "untrusted", "S-1-16-4096": "low"}


def native():
    """Process, module, token and command-line queries (ctypes; Windows only)."""
    import ctypes
    from ctypes import wintypes

    from src.desktop.platform import win32

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    class ProcessEntry(ctypes.Structure):  # PROCESSENTRY32W
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD),
                    ("threads", wintypes.DWORD), ("parent", wintypes.DWORD),
                    ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", ctypes.c_wchar * 260)]

    class ModuleEntry(ctypes.Structure):  # MODULEENTRY32W
        _fields_ = [("size", wintypes.DWORD), ("module", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("global_usage", wintypes.DWORD), ("process_usage", wintypes.DWORD),
                    ("base", ctypes.c_void_p), ("base_size", wintypes.DWORD),
                    ("handle", ctypes.c_void_p), ("name", ctypes.c_wchar * 256),
                    ("path", ctypes.c_wchar * 260)]

    class UnicodeString(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("maximum", ctypes.c_ushort),
                    ("buffer", ctypes.c_void_p)]

    snapshot = kernel32.CreateToolhelp32Snapshot
    snapshot.argtypes, snapshot.restype = [wintypes.DWORD, wintypes.DWORD], ctypes.c_void_p
    for name, entry in (("Process32FirstW", ProcessEntry), ("Process32NextW", ProcessEntry),
                        ("Module32FirstW", ModuleEntry), ("Module32NextW", ModuleEntry)):
        function = getattr(kernel32, name)
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(entry)]
        function.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.IsTokenRestricted.argtypes = [ctypes.c_void_p]
    ntdll.NtQueryInformationProcess.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG)]
    invalid = {None, 0, ctypes.c_void_p(-1).value}
    limited = win32.PROCESS_QUERY_LIMITED_INFORMATION

    def walk(flags, pid, first, step, entry_type, field):
        def open_snapshot():
            for _ in range(5):  # ERROR_BAD_LENGTH: the process was loading a module; ask again
                handle = snapshot(flags, pid)
                if handle not in invalid or ctypes.get_last_error() != 24:
                    break
            return None if handle in invalid else handle

        entry = entry_type()
        entry.size = ctypes.sizeof(entry)
        return observe(open_snapshot, lambda handle: first(handle, ctypes.byref(entry)),
                       lambda handle: step(handle, ctypes.byref(entry)),
                       lambda: getattr(entry, field), ctypes.get_last_error,
                       kernel32.CloseHandle)

    def opened(pid, action):
        handle = kernel32.OpenProcess(limited, False, pid)
        if handle in invalid:
            return None
        try:
            return action(handle)
        finally:
            kernel32.CloseHandle(handle)

    def image(handle):
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return buffer.value if ok else None

    def command_line(handle):
        needed = wintypes.ULONG()
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        if ntdll.NtQueryInformationProcess(handle, 60, buffer, needed, ctypes.byref(needed)):
            return None
        text = UnicodeString.from_buffer(buffer)
        return ctypes.wstring_at(text.buffer, text.length // 2) if text.buffer else ""

    def token(handle):
        facts = {}
        try:
            facts["integrity"] = win32._token_sid(win32.TOKEN_INTEGRITY_LEVEL_CLASS, process=handle)
        except OSError as exc:
            facts["integrity"] = f"unreadable ({exc})"
        held = ctypes.c_void_p()
        if advapi32.OpenProcessToken(handle, win32.TOKEN_QUERY, ctypes.byref(held)):
            try:
                facts["restricted"] = bool(advapi32.IsTokenRestricted(held))
                value, needed = wintypes.DWORD(), wintypes.DWORD()
                if advapi32.GetTokenInformation(held, 29, ctypes.byref(value),  # IsAppContainer
                                                ctypes.sizeof(value), ctypes.byref(needed)):
                    facts["appcontainer"] = bool(value.value)
            finally:
                kernel32.CloseHandle(held)
        return facts

    return SimpleNamespace(
        processes=lambda: walk(0x2, 0, kernel32.Process32FirstW, kernel32.Process32NextW,
                               ProcessEntry, "pid"),
        modules=lambda pid: walk(0x18, pid, kernel32.Module32FirstW, kernel32.Module32NextW,
                                 ModuleEntry, "path"),
        image=lambda pid: opened(pid, image),
        command_line=lambda pid: opened(pid, command_line),
        token=lambda pid: opened(pid, token))


ERROR_NO_MORE_FILES = 18


def observe(open_snapshot, first, step, read, last_error, close) -> dict:
    """A Toolhelp walk and how it ended. Complete only when the API reports no more entries; an
    unopenable snapshot is unreadable, and any other ending (even after some entries) failed."""
    handle = open_snapshot()
    if handle is None:
        return {"status": "unreadable", "items": []}
    items = []
    try:
        ok = first(handle)
        while ok:
            items.append(read())
            ok = step(handle)
        error = last_error()
    finally:
        close(handle)
    if error != ERROR_NO_MORE_FILES:
        return {"status": "failed", "error": error, "items": items}
    return {"status": "complete", "items": items}


def under(path: str, root: Path | str) -> bool:
    """Whether a Windows path lies under root, by Windows' rules on any OS (testable on Linux).
    Both sides are canonical: a hosted runner's TEMP is an 8.3 short name (RUNNER~1), while a
    loaded module's path is long. (On Linux ntpath.realpath is abspath.)"""
    return ntpath.normcase(ntpath.realpath(path)).startswith(
        ntpath.normcase(ntpath.realpath(str(root))).rstrip("\\") + "\\")


def classify_modules(paths: list[str], bundle: Path) -> dict:
    """Loaded modules by origin. A redistributable from outside the bundle is a failure. The PDF
    engine's first use extracts it from the bundle into the profile's data; a module from
    neither (a security product's scanner, an overlay) is listed."""
    windows = os.environ.get("SystemRoot") or r"C:\Windows"
    profile = ntpath.join(os.environ.get("LOCALAPPDATA") or str(bundle), "odin-desktop")
    found = {"bundle": [], "windows": [], "extracted_into_the_profile": [],
             "redistributable_from_outside_the_bundle": [], "other": []}
    for path in paths:
        if under(path, bundle):
            found["bundle"].append(path)
        elif REDISTRIBUTABLE.match(ntpath.basename(path)):
            found["redistributable_from_outside_the_bundle"].append(path)
        elif under(path, windows):
            found["windows"].append(path)
        elif under(path, profile) and re.search(r"[\\/]resources[\\/]pdf[\\/][0-9a-f]{64}[\\/]",
                                                path):
            found["extracted_into_the_profile"].append(path)
        else:
            found["other"].append(path)
    return found


def qualified_modules(observation: dict, image: str, bundle: Path) -> dict:
    """A process's modules as dependency evidence: the walk complete, nonempty and holding the
    process's own image, and no redistributable from outside the bundle. Raises otherwise."""
    assert observation["status"] == "complete", f"modules of {image}: {observation}"
    paths = observation["items"]
    canonical = ntpath.normcase(ntpath.realpath(image))
    assert any(ntpath.normcase(ntpath.realpath(path)) == canonical for path in paths), (
        f"modules of {image} don't include its own image: {paths}")
    found = classify_modules(paths, bundle)
    assert not found["redistributable_from_outside_the_bundle"], (image, found)
    return found


def own_modules() -> dict:
    """This process's modules after its case, qualified (see qualified_modules)."""
    bundle = Path(sys.prefix).resolve().parent.parent
    return qualified_modules(native().modules(os.getpid()), sys.executable, bundle)


def bundle_processes(bundle: Path, query=None) -> dict:
    """Every other process running from the bundle, as observed: its image, command line (None
    when unreadable, and then its type and flags unknown), token and module walk."""
    query = query or native()
    listing = query.processes()
    rows = []
    for pid in listing["items"]:
        if pid == os.getpid():
            continue
        image = query.image(pid)
        if not image or not under(image, bundle):
            continue
        command = query.command_line(pid)
        kind = re.search(r"--type=([\w-]+)", command or "")
        rows.append({"image": image, "pid": pid, "command_line": command,
                     "type": None if command is None else kind.group(1) if kind else "main",
                     "no_sandbox_flag": None if command is None else "--no-sandbox" in command,
                     "token": query.token(pid) or {}, "modules": query.modules(pid)})
    return {"listing": {key: value for key, value in listing.items() if key != "items"},
            "processes": rows}


def judge_browser(evidence: dict, bundle: Path) -> list[dict]:
    """The browser case's verdict over bundle_processes. Every Chromium and Node process must be
    fully observed: a read command line (so its type and flags are known) and a qualified module
    walk. Every renderer runs at untrusted or low integrity with a restricted or AppContainer
    token, and no Chromium process carries --no-sandbox. Raises on anything else."""
    assert evidence["listing"]["status"] == "complete", f"process listing: {evidence['listing']}"
    relevant = [row for row in evidence["processes"] if ntpath.basename(row["image"]).lower()
                in {"chrome-headless-shell.exe", "node.exe"}]
    judged = []
    for row in relevant:
        assert row["command_line"] is not None, f"unclassified process (command line unread): {row}"
        judged.append({**row, "image": ntpath.relpath(row["image"], str(bundle)),
                       "modules": qualified_modules(row["modules"], row["image"], bundle)})
    chromium = [row for row in judged if row["image"].lower().endswith("chrome-headless-shell.exe")]
    renderers = [row for row in chromium if row["type"] == "renderer"]
    assert renderers, f"no Chromium renderer observed: {judged}"
    for row in renderers:  # Chromium's sandbox: a lowered label and a restricted token
        facts = row["token"]
        assert facts.get("integrity") in SANDBOXED_LEVELS, row
        assert facts.get("restricted") or facts.get("appcontainer"), row
    assert not any(row["no_sandbox_flag"] for row in chromium), chromium
    return judged


def loads() -> dict:
    import sqlite3

    import cryptography
    import onnxruntime
    import pip
    import sqlite_vec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    import src

    for module in (cryptography, onnxruntime, sqlite3, sqlite_vec, src, pip):
        installed(module)
    cipher = AESGCM(AESGCM.generate_key(bit_length=128))
    encrypted = cipher.encrypt(b"0" * 12, b"native-load", b"")
    assert cipher.decrypt(b"0" * 12, encrypted, b"") == b"native-load"
    with sqlite3.connect(":memory:") as db:
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        version = db.execute("select vec_version()").fetchone()[0]
    assert sys.flags.isolated and not sys.flags.no_site
    assert not any(".venv" in str(p) for p in sys.path)
    return {"cryptography": cryptography.__version__, "onnxruntime": onnxruntime.__version__,
            "sqlite": sqlite3.sqlite_version, "sqlite_vec": version, "pip": pip.__version__}


async def browser() -> dict:
    from src.config.schema import BrowserConfig
    from src.desktop.browser_runtime import BrowserRuntime

    runtime = BrowserRuntime(BrowserConfig(enabled=True))
    assert await runtime.start(), runtime.status()
    manager = runtime.manager
    try:
        context, page = await manager._create_page()
        try:
            await page.goto("data:text/html,<title>Windows staged fixture</title>"
                            "<h1>Bundled browser</h1>")
            assert await page.title() == "Windows staged fixture"
            image = await page.screenshot()
            assert image.startswith(b"\x89PNG")
            executable = Path(manager._bundled_executable).resolve()
            assert executable.is_relative_to(Path(sys.prefix).resolve().parent)
            assert executable.suffix.lower() == ".exe"
            bundle = Path(sys.prefix).resolve().parent.parent
            processes = judge_browser(bundle_processes(bundle), bundle)
            return {"browser": manager._browser.version, "executable": str(executable),
                    "screenshot_bytes": len(image), "title": await page.title(),
                    "processes": processes}
        finally:
            await context.close()
    finally:
        await runtime.close()


async def search() -> dict:
    import fastembed.common.model_management as management
    import requests

    import src.search.embedder as engine
    from src.search.bundled_models import bundled_model_roots
    installed(engine)
    roots = bundled_model_roots()
    assert len(roots) == 1 and roots[0].is_dir()

    def forbidden(*args, **kwargs):
        raise AssertionError("offline inference attempted network/download")

    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    socket.create_connection = forbidden
    management.snapshot_download = forbidden
    management.model_info = forbidden
    management.list_repo_tree = forbidden
    requests.sessions.Session.request = forbidden
    before = digest_tree(roots[0])
    embedder = engine.LocalEmbedder()
    first = await embedder.embed("The database transaction committed successfully.")
    second = await embedder.embed("The database transaction committed successfully.")
    other = await embedder.embed("A bright blue painting hangs above the kitchen table.")
    assert first is not None, embedder.unavailable_reason
    assert first == second and other is not None
    assert len(first) == len(other) == 384
    assert all(math.isfinite(v) for vector in (first, other) for v in vector)
    norm = math.sqrt(sum(v * v for v in first))
    assert abs(norm - 1) < .001
    cosine = sum(a * b for a, b in zip(first, other))
    assert cosine < .95
    assert embedder._model.model.model.get_providers() == ["CPUExecutionProvider"]
    assert digest_tree(roots[0]) == before
    return {"dimensions": 384, "norm": norm, "unrelated_cosine": cosine,
            "network_download_attempts": 0, "model": engine.LocalEmbedder.MODEL}


async def pdf() -> dict:
    from src.runtime import pdf_resources
    assert importlib.util.find_spec("fitz") is None, "PDF must be absent before first use"
    lock = pdf_resources._read_lock()
    assert lock["platform"] == "windows-amd64"
    fitz = await pdf_resources.ensure_pdf()
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Odin staged Windows PDF first use")
    encoded = document.tobytes()
    document.close()
    with fitz.open(stream=encoded, filetype="pdf") as readback:
        text = readback[0].get_text()
    assert "Odin staged Windows PDF first use" in text
    assert not Path(fitz.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert await pdf_resources.ensure_pdf() is fitz
    return {"first_use_download_sha256": lock["sha256"], "text": text.strip(),
            "module": str(fitz.__file__), "reuse": True}


class Lease:
    def __init__(self):
        self.target = SimpleNamespace(address="127.0.0.1", ssh_user="u", alias="localhost")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    async def run(self, factory):
        return await factory()


def local_executor():
    from src.desktop.platform.windows_tools import exec_command
    owner = SimpleNamespace(
        bulkheads={}, ssh_pool=None, _ensure_local_workspace=lambda: None,
        _command_shell_mode=lambda: "auto", config=SimpleNamespace(command_timeout_seconds=40),
        _current_user_id="runtime-acceptance", command_governor=None,
        _resolve_default_host=lambda user: "localhost",
        _resolve_host=lambda alias: ("127.0.0.1", "u", "x") if alias == "localhost" else None,
        _acquire_host=lambda alias: Lease() if alias == "localhost" else None)
    owner._exec_command = functools.partial(exec_command, owner)
    return owner


def self_signed_server(work: Path):
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path, cert_path = work / "fixture.key", work / "fixture.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    class Quiet(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"fixture")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def curl(work: Path) -> dict:
    from src.desktop.platform.windows_helpers import curl_exe, run_argv
    from src.desktop.platform.windows_tools import handle_http_probe, handle_validate_action
    executable = Path(curl_exe()).resolve()
    assert executable.is_relative_to(Path(sys.prefix).resolve().parent.parent / "tools")
    code, version = await run_argv([str(executable), "--version"], 20)
    assert code == 0, version
    assert "curl 8.22.0" in version and "LibreSSL/4.3.3" in version, version
    owner = local_executor()
    # This process's first validation, cold, inside the product's default timeout, on every runner.
    start = time.monotonic()
    first = json.loads(await handle_validate_action(owner, {"format": "json", "checks": [{
        "type": "http", "target": "https://example.com/", "timeout_seconds": FIRST_CALL_DEADLINE,
        "expected": 200}]}))["checks"][0]
    first_call = {"seconds": round(time.monotonic() - start, 2), "status": first["status"],
                  "observed": str(first.get("observed", ""))[-300:],
                  "deadline_seconds": FIRST_CALL_DEADLINE}
    print(json.dumps({"first_call": first_call}), flush=True)
    assert first["status"] == "pass", first_call
    server = self_signed_server(work)
    rows = []
    try:
        cases = [("trusted", "https://example.com/", 0),
                 ("untrusted", f"https://localhost:{server.server_address[1]}/", 60),
                 ("hostname-mismatch", "https://wrong.host.badssl.com/", 60)]
        for label, url, expected in cases:
            text, code = await handle_http_probe(owner, {"url": url, "timeout": 30})
            retried = None
            if label != "untrusted" and code in CONNECTION_FAILURES:
                # A public fixture that dropped the connection (a hosted run once got exit 35 from
                # wrong.host.badssl.com): one retry, recorded; the verdict itself isn't relaxed.
                retried = {"exit": code, "output": text[:300]}
                text, code = await handle_http_probe(owner, {"url": url, "timeout": 30})
            assert code == expected, (label, code, text)
            if label == "trusted":
                assert "status_code: 200" in text, text
            if label == "hostname-mismatch":
                words = ("subject name", "hostname", "no alternative certificate")
                assert any(word in text.lower() for word in words), text
            check = {"format": "json", "checks": [{"type": "http", "target": url,
                                                   "timeout_seconds": 30, "expected": 200}]}
            row = json.loads(await handle_validate_action(owner, check))["checks"][0]
            dropped = re.search(r"curl failed \(exit (\d+)\)", str(row.get("error", "")))
            if label != "untrusted" and dropped and int(dropped.group(1)) in CONNECTION_FAILURES:
                retried = {**(retried or {}), "validation": row}  # the same single, recorded retry
                row = json.loads(await handle_validate_action(owner, check))["checks"][0]
            assert row["status"] == ("pass" if expected == 0 else "fail"), row
            if expected:
                assert "curl failed (exit 60)" in row["error"], row
            rows.append({"case": label, "probe_exit": code, "validation": row,
                         **({"retried_after": retried} if retried else {})})
    finally:
        server.shutdown()
        server.server_close()
    return {"version": version.strip(), "executable": str(executable), "cases": rows,
            "first_call": first_call,
            "fixture_dependency": "trusted/hostname-mismatch require public HTTPS fixtures"}


async def ssh(work: Path) -> dict:
    from src.desktop.platform.windows_helpers import run_argv
    from src.desktop.platform.windows_ssh import openssh, restrict_key
    executable = Path(openssh("ssh")).resolve()
    keygen = Path(openssh("ssh-keygen")).resolve()
    tools = Path(sys.prefix).resolve().parent.parent / "tools"
    assert executable.is_relative_to(tools) and keygen.is_relative_to(tools)
    code, version = await run_argv([str(executable), "-V"], 20)
    assert code == 0 and "OpenSSH" in version, version
    key = work / "disposable_ed25519"
    code, output = await run_argv([str(keygen), "-t", "ed25519", "-N", "", "-f", str(key)], 30)
    assert code == 0 and key.is_file(), output
    restrict_key(key)
    code, output = await run_argv([str(keygen), "-y", "-f", str(key)], 20)
    assert code == 0 and output.startswith("ssh-ed25519 "), output
    return {"version": version.strip(), "executable": str(executable),
            "keygen": str(keygen), "private_key_after_acl_restriction_readable": True,
            "limitation": "not remote authentication or negative cross-user ACL qualification"}


def child(mode: str, work: Path) -> dict:
    assert sys.platform == "win32" and sys.flags.isolated
    prefix = Path(sys.prefix).resolve()
    assert prefix.name == "python" and prefix.parent.name == "runtime"
    assert not Path.cwd().resolve().is_relative_to(prefix)
    if mode == "loads":
        result = loads()
    else:
        result = asyncio.run({"browser": browser, "search": search, "pdf": pdf,
                              "curl": lambda: curl(work), "curl-profile": lambda: curl(work),
                              "ssh": lambda: ssh(work)}[mode]())
    return {"case": mode, "status": "pass", "python": sys.executable, **result,
            "modules": own_modules()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--child", choices=("loads", "browser", "search", "pdf", "curl-profile",
                                             "curl", "ssh"))
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.child:
        result = child(args.child, args.work)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return 0
    if sys.platform != "win32":
        parser.error("native Windows required; Linux logic tests are not runtime qualification")
    resources = args.resources.resolve()
    executable = resources / "runtime/python/python.exe"
    assert executable.is_file(), executable
    report = {"status": "running", "resources": str(resources), "cases": [],
              "revision": (os.environ.get("GITHUB_SHA")
                           or os.environ.get("ODIN_ACCEPTANCE_REVISION")),
              "bundle_manifest_sha256": hashlib.sha256(
                  (resources / "bundle-manifest.json").read_bytes()).hexdigest(),
              "remaining": ["Legion Windows 11 clean-system acceptance",
                            "Linux SSH: strict host keys, wrong-key refusal, private-key ACLs",
                            "phase 4b installer/app and phase 4c whole candidate acceptance"]}
    before = digest_tree(resources)
    try:
        with tempfile.TemporaryDirectory(prefix="odin-runtime-acceptance-") as temporary:
            work = Path(temporary)
            copied = work / "acceptance.py"
            shutil.copyfile(__file__, copied)
            for mode in ("loads", "browser", "search", "pdf", "curl-profile", "curl", "ssh"):
                case = work / mode
                case.mkdir()
                if mode == "curl-profile":
                    env = profile_environment(case, resources, os.environ)
                else:
                    env = cold_environment(case, resources, os.environ)
                for name in ("home", "local", "roaming", "temp", "hf", "no-browser-cache"):
                    (case / name).mkdir()
                output = case / "result.json"
                print(f"staged runtime: {mode}", flush=True)
                process = subprocess.run([str(executable), "-I", "-B", str(copied), "--child", mode,
                                          "--work", str(case), "--report", str(output)],
                                         env=env, cwd=case, timeout=300, check=False)
                if process.returncode:
                    raise RuntimeError(f"{mode} child exited {process.returncode}")
                report["cases"].append(json.loads(output.read_text(encoding="utf-8")))
        assert digest_tree(resources) == before, "qualification modified sealed resources"
        report["status"] = "pass"
        report["immutable_resources"] = True
        return 0
    except Exception as exc:
        report.update(status="fail", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
