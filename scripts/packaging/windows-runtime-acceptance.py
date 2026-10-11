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
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace


def cold_environment(work: Path, resources: Path, ambient: dict[str, str]) -> dict[str, str]:
    system = ambient.get("SystemRoot", r"C:\Windows")
    env = {key: ambient[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in ambient}
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


def digest_tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def installed(module):
    path = Path(module.__file__).resolve()
    if not path.is_relative_to(Path(sys.prefix).resolve()):
        raise AssertionError(f"module escaped staged interpreter: {module.__name__}: {path}")


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
            return {"browser": manager._browser.version, "executable": str(executable),
                    "screenshot_bytes": len(image), "title": await page.title(),
                    "limitation": "browser launch/render; no Windows sandbox-token audit"}
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
    server = self_signed_server(work)
    rows = []
    try:
        cases = [("trusted", "https://example.com/", 0),
                 ("untrusted", f"https://localhost:{server.server_address[1]}/", 60),
                 ("hostname-mismatch", "https://wrong.host.badssl.com/", 60)]
        for label, url, expected in cases:
            text, code = await handle_http_probe(owner, {"url": url, "timeout": 30})
            assert code == expected, (label, code, text)
            if label == "trusted":
                assert "status_code: 200" in text, text
            if label == "hostname-mismatch":
                words = ("subject name", "hostname", "no alternative certificate")
                assert any(word in text.lower() for word in words), text
            report = json.loads(await handle_validate_action(owner, {
                "format": "json", "checks": [{"type": "http", "target": url,
                                               "timeout_seconds": 30, "expected": 200}]}))
            row = report["checks"][0]
            assert row["status"] == ("pass" if expected == 0 else "fail"), row
            if expected:
                assert "curl failed (exit 60)" in row["error"], row
            rows.append({"case": label, "probe_exit": code, "validation": row})
    finally:
        server.shutdown()
        server.server_close()
    return {"version": version.strip(), "executable": str(executable), "cases": rows,
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
                              "curl": lambda: curl(work), "ssh": lambda: ssh(work)}[mode]())
    return {"case": mode, "status": "pass", "python": sys.executable, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--child", choices=("loads", "browser", "search", "pdf", "curl", "ssh"))
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
              "revision": os.environ.get("GITHUB_SHA"),
              "remaining": ["Legion Windows 11 clean-system acceptance",
                            "Linux SSH: strict host keys, wrong-key refusal, private-key ACLs",
                            "phase 4b installer/app and phase 4c whole candidate acceptance"]}
    before = digest_tree(resources)
    try:
        with tempfile.TemporaryDirectory(prefix="odin-runtime-acceptance-") as temporary:
            work = Path(temporary)
            copied = work / "acceptance.py"
            shutil.copyfile(__file__, copied)
            for mode in ("loads", "browser", "search", "pdf", "curl", "ssh"):
                case = work / mode
                case.mkdir()
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
