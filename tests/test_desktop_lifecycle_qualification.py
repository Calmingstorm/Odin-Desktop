"""Driver evidence is data, not native/engine acceptance or document wording."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parents[1] / "scripts/qualification/lifecycle.py"


def driver():
    spec = importlib.util.spec_from_file_location("lifecycle_qualification_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("code", [0, 1])
def test_driver_retains_failed_or_successful_gate_and_hashes_without_inheriting_session(
    tmp_path, monkeypatch, code,
):
    module = driver()
    repository = tmp_path / "repo"
    fake_script = repository / "scripts/qualification/lifecycle.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(module, "__file__", str(fake_script))
    files = {
        "app/out/main/index.js": b"main",
        "app/out/preload/index.js": b"preload",
        "app/out/renderer/index.html": b"renderer",
        "app/package-lock.json": b"lock",
        "uv.lock": b"python lock",
    }
    for relative, content in files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    output = tmp_path / "evidence"
    monkeypatch.setattr("sys.argv", [str(DRIVER), "--output", str(output), "lifecycle"])
    monkeypatch.setenv("DISPLAY", ":active-session")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/active-session")
    monkeypatch.setenv("ODIN_DESKTOP_CORE_CMD", "ambient core override")
    monkeypatch.setenv("NODE_OPTIONS", "ambient flags")
    captured = {}

    class Process:
        stdout = io.StringIO("case evidence\n")

        def wait(self):
            return code

    def launch(command, **kwargs):
        captured.update(command=command, **kwargs)
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: "test-sha\n")
    assert module.main() == code
    assert captured["cwd"] == repository
    assert captured["command"][-1] == "lifecycle"
    for key in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "ODIN_DESKTOP_CORE_CMD", "NODE_OPTIONS"):
        assert key not in captured["env"]
    evidence = json.loads((output / "qualification.json").read_text())
    assert evidence["exit_code"] == code
    assert evidence["source_sha"] == "test-sha"
    assert evidence["artifacts_sha256"] == {
        relative: hashlib.sha256(content).hexdigest() for relative, content in files.items()
    }
    assert (output / "qualification.log").read_text() == "case evidence\n"
    assert evidence["native_d11"].startswith("open:")
    assert evidence["package_paths"].startswith("open:")


def test_driver_rejects_evidence_inside_checkout_before_launch(tmp_path, monkeypatch):
    module = driver()
    fake_script = tmp_path / "scripts/qualification/lifecycle.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(module, "__file__", str(fake_script))
    monkeypatch.setattr("sys.argv", [str(DRIVER), "--output", str(tmp_path / "app/evidence")])
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *a, **kw: pytest.fail("must reject before launch"),
    )
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
