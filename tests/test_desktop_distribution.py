"""Packaging and approved-wording boundaries, without starting a core or desktop."""

from __future__ import annotations

import ast
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def baseline(path: str) -> str:
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz", "r:gz") as archive:
        stream = archive.extractfile(path)
        assert stream is not None
        return stream.read().decode("utf-8")


def test_engine_requires_python312_and_bundled_capabilities():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = metadata["project"]
    assert project["name"] == "odin-desktop-engine"
    assert project["requires-python"] == ">=3.12,<3.13"
    requirements = [item.lower() for item in project["dependencies"]]
    for required in ("playwright", "fastembed", "python-xlib", "dbus-next"):
        assert any(item.startswith(required) for item in requirements)
    assert not any(item.startswith("pymupdf") for item in requirements)
    for removed in ("discord.py", "sqlalchemy", "asyncpg", "odin-bot"):
        assert not any(removed in item for item in requirements)
    extras = project.get("optional-dependencies", {})
    assert set(extras) == {"dev", "pdf"}
    assert extras["pdf"] == ["PyMuPDF>=1.24.0"]
    assert not project.get("scripts")


def test_prompt_is_exactly_the_nine_approved_d7_substitutions():
    path = "src/llm/system_prompt.py"
    substitutions = (
        ("- For Discord: bold for emphasis", "- In chat: bold for emphasis"),
        ("- For Discord: code blocks for output", "- In chat: code blocks for output"),
        ("- For Discord: use formatting", "- In chat: use formatting"),
        ("You are {bot_name}, an autonomous execution agent on Discord.",
         "You are {bot_name}, an autonomous execution agent."),
        ("Never write code inline in Discord.", "Never write code inline in chat."),
        ("- **Discord channel context unclear** → `read_channel` before answering.",
         "- **Conversation context unclear** → `read_conversation` before answering."),
        ("2. Keep responses concise — this is Discord. Code blocks for output. "
         "One update per task, not per tool call. Fenced code blocks (```) MUST start at "
         "column 0 — indented fences render as inline code in Discord.",
         "2. Keep responses concise. Code blocks for output. "
         "One update per task, not per tool call. "
         "Fenced code blocks (```) MUST start at column 0."),
        ("You are {bot_name}, an AI assistant Discord bot.",
         "You are {bot_name}, an AI assistant."),
        ("2. Keep responses concise — this is Discord, not a document.",
         "2. Keep responses concise — this is a chat, not a document."),
    )
    expected = baseline(path)
    for old, new in substitutions:
        assert expected.count(old) == 1
        expected = expected.replace(old, new, 1)
    assert (ROOT / path).read_bytes() == expected.encode()


def test_response_guard_only_changes_the_two_approved_lines():
    path = "src/discord/response_guards.py"
    expected = baseline(path)
    for old, new in (
        ("# Additional patterns for scrubbing LLM responses before Discord delivery.",
         "# Additional patterns for scrubbing LLM responses before conversation delivery."),
        ("Scrub potential secrets from LLM responses before sending to Discord.",
         "Scrub potential secrets from LLM responses before sending to the conversation."),
    ):
        assert expected.count(old) == 1
        expected = expected.replace(old, new, 1)
    assert (ROOT / path).read_bytes() == expected.encode()


def test_no_removed_third_party_transport_or_moderation_imports():
    violations = []
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(name.split(".")[0] in {"discord", "sqlalchemy", "asyncpg"}
                   for name in names):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, violations


def test_dependency_lock_excludes_removed_distributions():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    names = {package["name"] for package in lock["package"]}
    assert not names.intersection({"sqlalchemy", "asyncpg"})
    packages = {package["name"]: package for package in lock["package"]}
    project = packages["odin-desktop-engine"]
    runtime, pending = set(), [dependency["name"] for dependency in project["dependencies"]]
    while pending:
        name = pending.pop()
        if name in runtime:
            continue
        runtime.add(name)
        pending.extend(dependency["name"] for dependency in packages[name].get("dependencies", []))
    assert not runtime.intersection({"discord-py", "discord.py", "sqlalchemy", "asyncpg"})
    # The original pinned executor needs its unchanged Discord imports only
    # inside the fresh-install parity test. It must not enter a shipped runtime.
    dev = {dependency["name"] for dependency in project["optional-dependencies"]["dev"]}
    assert "discord-py" in dev
    assert packages["discord-py"]["version"] == "2.7.1"
