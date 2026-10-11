"""The installed-core acceptance's scripted model (portable; native results come from Windows)."""
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/packaging/windows-installed-core-acceptance.py"
SPEC = importlib.util.spec_from_file_location("windows_installed_core_acceptance", SCRIPT)
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)

TOOLS = [{"type": "function", "function": {"name": "run_command", "parameters": {}}}]
NAMES = CORE.probe("0a1b2c3d")


def ask(server, body: dict) -> dict:
    """One streamed answer, folded into its delta and finish reason."""
    url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    request = urllib.request.Request(url, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["Content-Type"] == "text/event-stream"
        lines = [line[6:] for line in response.read().decode().splitlines()
                 if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    frames = [json.loads(line) for line in lines[:-1]]
    return {"delta": frames[0]["choices"][0]["delta"],
            "finish": frames[1]["choices"][0]["finish_reason"]}


def test_the_scripted_model_answers_the_judge_the_tool_turn_and_a_plain_turn(tmp_path):
    marker = tmp_path / "it's here.txt"  # a quote in the path stays inside the command's quotes
    server = CORE.scripted_model(marker)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/v1/models",
                                    timeout=10) as response:
            assert json.loads(response.read())["data"][0]["id"] == CORE.MODEL
        judge = ask(server, {"messages": [{"role": "user", "content": CORE.PROMPT}]})
        assert judge == {"delta": {"role": "assistant", "content": "COMPLETE"}, "finish": "stop"}

        call = ask(server, {"tools": TOOLS, "messages": [
            {"role": "user", "content": [{"type": "text", "text": CORE.PROMPT}]}]})
        assert call["finish"] == "tool_calls"
        function = call["delta"]["tool_calls"][0]["function"]
        assert function["name"] == "run_command"
        quoted = str(marker).replace("'", "''")
        command = f"Set-Content -LiteralPath '{quoted}' -Value '{CORE.MARK}'"
        assert json.loads(function["arguments"]) == {"host": "localhost", "command": command}

        reply = ask(server, {"tools": TOOLS, "messages": [
            {"role": "user", "content": CORE.PROMPT}, {"role": "assistant", "tool_calls": []},
            {"role": "tool", "content": "ok"}]})
        assert reply == {"delta": {"role": "assistant", "content": CORE.REPLY}, "finish": "stop"}

        plain = ask(server, {"tools": TOOLS, "messages": [{"role": "user", "content": "hello"}]})
        assert plain["delta"]["content"] == "Scripted reply: installed core."
    finally:
        server.shutdown()
        server.server_close()


def test_both_probe_packages_install_with_pip_from_the_loopback_index(tmp_path):
    # The wheel installs as it is; the source package is built by pip through its in-tree backend.
    server = CORE.package_index({NAMES.package: CORE.probe_wheel(tmp_path, NAMES),
                                 NAMES.source: CORE.probe_sdist(tmp_path, NAMES)})
    try:
        target = tmp_path / "target"
        index = f"http://127.0.0.1:{server.server_address[1]}/simple/"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             "--no-cache-dir", "--target", str(target), "--index-url", index,
             f"{NAMES.package}=={NAMES.version}", f"{NAMES.source}=={NAMES.version}"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PIP_CONFIG_FILE": os.devnull})
        assert result.returncode == 0, result.stderr
        module = (target / NAMES.module / "__init__.py").read_text()
        assert module == f'MARK = "{NAMES.mark}"\n'
        built = (target / NAMES.source_module / "__init__.py").read_text()
        assert built == f"MARK = {NAMES.source_mark!r}\n"
    finally:
        server.shutdown()
        server.server_close()


def test_the_probe_skill_declares_its_runs_package():
    namespace = {}
    exec(compile(CORE.skill_code(NAMES), "skill", "exec"), namespace)  # noqa: S102 - our own source
    definition = namespace["SKILL_DEFINITION"]
    assert definition["name"] == NAMES.skill
    assert definition["dependencies"] == [f"{NAMES.package}=={NAMES.version}",
                                          f"{NAMES.source}=={NAMES.version}"]
    assert CORE.probe("ffff0000").skill != NAMES.skill  # each run names its own



def test_the_required_checks_are_listed_for_the_consumer(capsys):
    assert CORE.main(["--list-checks"]) == 0
    assert json.loads(capsys.readouterr().out) == list(CORE.REQUIRED)


def test_an_interrupted_run_reports_itself_incomplete(monkeypatch, tmp_path):
    # Odin's round 5 reproduction: one successful check, then an interruption.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    async def interrupted(run, work):
        run.check(CORE.REQUIRED[0], True)
        raise KeyboardInterrupt

    monkeypatch.setattr(CORE, "acceptance", interrupted)
    report = tmp_path / "core.json"
    assert CORE.main(["--report", str(report)]) == 1
    written = json.loads(report.read_text())
    assert written["completed"] is False and written["failed"] == 1
    assert [item["check"] for item in written["checks"]] == [CORE.REQUIRED[0], CORE.ENDED]
    assert written["checks"][-1]["detail"].startswith("KeyboardInterrupt")


def test_a_check_outside_the_required_list_fails_the_run(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    async def misnamed(run, work):
        run.check("a check nobody listed", True)

    monkeypatch.setattr(CORE, "acceptance", misnamed)
    report = tmp_path / "core.json"
    assert CORE.main(["--report", str(report)]) == 1
    written = json.loads(report.read_text())
    assert written["completed"] is False
    assert "a check outside REQUIRED" in written["checks"][-1]["detail"]
