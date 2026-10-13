"""macOS: the command tools' descriptions name the bash found and say the Mac's tools differ."""
from __future__ import annotations

from src.tools import command_shell

FOOTER = "\n\n[affordances: x]"
TOOLS = [{"name": name, "description": f"{name} does its work.{FOOTER}"}
         for name in ("run_command", "run_command_multi", "manage_process", "validate_action",
                      "read_file")]
MAC = ("on this Mac, where the system's own tools are the BSD versions, not GNU (for example "
       "sed -i needs a suffix argument, and stock macOS has no timeout command)")


def described(monkeypatch, path: str, mode: str = "auto", tools=TOOLS) -> dict[str, str]:
    monkeypatch.setenv("PATH", path)
    return {tool["name"]: tool["description"]
            for tool in command_shell.apply_shell_contracts(tools, mode)}


def test_apples_bash_is_named_with_its_version_and_the_bsd_tools(monkeypatch):
    tools = described(monkeypatch, "/bin:/usr/bin")
    assert tools["run_command"] == (
        f"run_command does its work. Local commands run under Apple's bash 3.2 (/bin/bash) {MAC}; "
        f"remote commands use the remote account's login shell.{FOOTER}")
    assert tools["run_command_multi"].startswith(
        "run_command_multi does its work. Local commands run under Apple's bash 3.2 (/bin/bash) ")
    assert tools["manage_process"] == (
        "manage_process does its work. New local jobs run under Apple's bash 3.2 (/bin/bash) on "
        f"this Mac; remote jobs run under /bin/sh.{FOOTER}")
    assert tools["validate_action"] == (
        "validate_action does its work. Local command checks run under Apple's bash 3.2 "
        "(/bin/bash) on this Mac; remote command checks use the remote account's login shell."
        f"{FOOTER}")
    assert tools["read_file"] == TOOLS[4]["description"]


def test_another_bash_is_named_by_its_path(monkeypatch, tmp_path):
    bash = tmp_path / "bash"
    bash.write_text("#!/bin/sh\nexit 0\n")  # never run: the label comes from the path alone
    bash.chmod(0o755)
    tools = described(monkeypatch, f"{tmp_path}:/bin:/usr/bin")
    assert f" Local commands run under bash ({bash}) {MAC};" in tools["run_command"]


def test_sh_is_named_when_chosen(monkeypatch):
    tools = described(monkeypatch, "/bin:/usr/bin", mode="sh")
    assert f" Local commands run under sh (/bin/sh) {MAC};" in tools["run_command"]


def test_a_decorated_catalog_is_redecorated_cleanly(monkeypatch):
    once = described(monkeypatch, "/bin:/usr/bin")
    again = described(monkeypatch, "/bin:/usr/bin", tools=[
        {"name": name, "description": text} for name, text in once.items()])
    assert again == once
    linux = command_shell.apply_shell_contracts.linux_original(TOOLS)  # Linux's own sentences
    assert described(monkeypatch, "/bin:/usr/bin", tools=linux) == once


def test_a_refusal_reads_as_on_linux(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))  # no bash on PATH
    refused = command_shell.apply_shell_contracts(TOOLS, "bash")
    assert refused == command_shell.apply_shell_contracts.linux_original(TOOLS, "bash")
    assert ("New local commands are refused because bash is required but not installed"
            in refused[0]["description"])
