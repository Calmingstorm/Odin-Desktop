"""Offline supplemental schema checks, NOT restoration of the frozen matrix."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.docs.generate_tool_reference import tool_sections
from scripts.maintenance.fixture_corpus import ARCHIVE_SHA256, frozen_source
from src.llm.strict_tool_adapter import compile_catalog
from src.tools.registry import get_documentation_tool_definitions, get_tool_definitions

ROOT = Path(__file__).resolve().parents[1]
REMOVED = {"purge_messages", "set_permission", "read_channel", "add_reaction", "create_poll"}


def frozen_inputs():
    tree = ast.parse(frozen_source("tests/test_codex_replay_matrix.py"))
    assignment = next(
        n for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "BUILTIN_INPUTS" for t in n.targets)
    )
    # Only names needed for the unchanged equality guard; do not edit its inputs.
    return {ast.literal_eval(key) for key in assignment.value.keys}


def archived_removed():
    """Read canonical legacy schemas from the real hash-pinned section producers.

    These four sections are literal-only. No historical code is executed, no
    invented wire schemas, no production registry or builtin classification edits.
    """
    data = (ROOT / "maintenance/odin-v4.13.0.tar.gz").read_bytes()
    assert hashlib.sha256(data).hexdigest() == ARCHIVE_SHA256
    result = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for section in ("system_files", "media_scheduling", "browser_web", "channel_process_loops"):
            path = f"src/tools/defs/{section}.py"
            matches = [m for m in archive.getmembers() if m.name == path]
            assert len(matches) == 1 and matches[0].isfile()
            tree = ast.parse(archive.extractfile(matches[0]).read())
            assignment = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                              and isinstance(n.target, ast.Name) and n.target.id == "TOOLS_SECTION")
            result.extend(t for t in ast.literal_eval(assignment.value) if t["name"] in REMOVED)
    assert {t["name"] for t in result} == REMOVED
    return result


def test_current_documentation_and_reference_producers_preserve_real_catalog_gap():
    docs = get_documentation_tool_definitions()
    reference = [t for _, section in tool_sections() for t in section]
    assert [t["name"] for t in reference] == [t["name"] for t in docs]
    assert [t["input_schema"] for t in reference] == [t["input_schema"] for t in docs]
    names = {t["name"] for t in docs}
    assert len(names) == 63 and len(frozen_inputs()) == 67
    assert frozen_inputs() - names == REMOVED
    assert names - frozen_inputs() == {"read_conversation"}
    # The real producers have no reference-only retired-name union.
    assert names.isdisjoint(REMOVED)
    assert get_tool_definitions() == []


LEGACY_INPUTS = {
    "purge_messages": {}, "set_permission": {"user_id": "123", "tier": "guest"},
    "read_channel": {}, "add_reaction": {"message_id": "123", "emoji": "fixture"},
    "create_poll": {"question": "fixture?", "options": ["one", "two"], "multiple": False},
}


@pytest.mark.parametrize("name", sorted(REMOVED))
def test_archived_schema_real_compiler_is_external_envelope_not_inherited_builtin(name):
    adapter = compile_catalog(archived_removed())
    assert adapter.report[name]["mode"] == "external_envelope"
    expected = LEGACY_INPUTS[name]
    assert adapter.accept(name, {"json": json.dumps(expected)}) == expected
    with pytest.raises(ValueError):
        adapter.accept(name, expected)
    with pytest.raises(ValueError):
        compile_catalog(get_documentation_tool_definitions()).accept(
            name, {"json": json.dumps(expected)}
        )


@pytest.mark.parametrize("wire,expected", [
    ({"limit": None}, {}), ({"limit": 0}, {"limit": 0}), ({"limit": 100}, {"limit": 100}),
])
def test_read_conversation_real_strict_normalizer(wire, expected):
    adapter = compile_catalog(get_documentation_tool_definitions())
    assert adapter.report["read_conversation"]["mode"] == "builtin_strict"
    assert adapter.accept("read_conversation", wire) == expected


@pytest.mark.parametrize("wire", [
    {}, {"limit": "10"}, {"limit": False}, {"limit": 10, "channel_id": "other"},
    {"limit": 10, "conversation_id": "other"},
])
def test_read_conversation_rejects_invalid_wire_and_foreign_scope(wire):
    adapter = compile_catalog(get_documentation_tool_definitions())
    with pytest.raises(ValueError):
        adapter.accept("read_conversation", wire)
