"""The installed-core acceptance's scripted model (portable; native results come from Windows)."""
import importlib.util
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/packaging/windows-installed-core-acceptance.py"
SPEC = importlib.util.spec_from_file_location("windows_installed_core_acceptance", SCRIPT)
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)

TOOLS = [{"type": "function", "function": {"name": "run_command", "parameters": {}}}]


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
