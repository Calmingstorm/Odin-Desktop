"""PR 2 code/baseline and machine-readable plan checks; no document wording tests."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PHASE2_SET_SHA256 = "a4bcf41b3ee1660c991df903cccbda1583497c2ec01cea6bb2be6425ba43888f"
GOVERNOR_SUITES = (
    "tests/test_risk_classifier.py",
    "tests/test_governor_policy_floor.py",
    "tests/test_governor_shape_fixtures.py",
    "tests/test_governor_shape_matrix.py",
)


def test_all_326_phase2_suites_are_frozen_in_the_machine_readable_plan():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    paths = plan["phase2"]
    assert len(paths) == len(set(paths)) == 326
    assert set(paths) == {
        entry["path"] for entry in plan["entries"] if entry["classification"] == "phase2"
    }
    encoded = ("\n".join(sorted(paths)) + "\n").encode()
    assert hashlib.sha256(encoded).hexdigest() == PHASE2_SET_SHA256
    for required in (
        "tests/characterization/test_chat_tool_loop.py",
        "tests/test_recovery.py",
        "tests/test_tool_loop_helpers.py",
        "tests/test_codex_replay_boundaries.py",
        "tests/test_codex_replay_matrix.py",
    ):
        assert required in paths


def test_governor_manual_gates_remain_explicit_in_the_machine_readable_plan():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    records = {entry["path"]: entry for entry in plan["entries"]}
    for path in GOVERNOR_SUITES:
        assert path in plan["safety_manual_gated"]
        assert records[path]["classification"] == "safety_manual_gated"


def test_governor_and_imports_keep_the_bytes_supported_by_upstream_ci():
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz") as archive:
        for path in (
            "src/tools/risk_classifier.py",
            "src/tools/command_shapes.py",
            "src/tools/command_authority.py",
        ):
            stream = archive.extractfile(path)
            assert stream is not None
            assert (ROOT / path).read_bytes() == stream.read(), path


def _definition_section(source, path):
    """Evaluate only the import-free definition slices, never engine composition."""
    tree = ast.parse(source, filename=path)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    scope = {}
    exec(compile(tree, path, "exec"), scope)
    return scope["TOOLS_SECTION"]


def test_every_changed_catalog_name_description_and_schema_is_exact_c1_c3():
    paths = (
        "agents", "browser_web", "channel_process_loops", "integrations_email",
        "media_scheduling", "memory_skills", "output_delivery", "tasks_knowledge",
    )
    retired = {"set_permission", "add_reaction", "create_poll", "purge_messages"}
    description_substitutions = {
        "browser_screenshot": ("posts to Discord.", "posts to the conversation."),
        "post_file": ("a Discord attachment.", "a conversation attachment."),
        "generate_file": ("a Discord attachment.", "a conversation attachment."),
        "generate_image": ("posts it to Discord.", "posts it to the conversation."),
        "delegate_task": ("posting progress to Discord.", "posting progress to the conversation."),
        "search_history": (
            "full channel message logs from all users.",
            "full conversation message logs in this profile.",
        ),
        "get_tool_output": ("Original caller, channel,", "Original caller, conversation,"),
        "update_schedule": (
            "steps, channel_id, report_format, or paused.",
            "steps, conversation_id, report_format, or paused.",
        ),
    }
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz") as archive:
        for module in paths:
            path = f"src/tools/defs/{module}.py"
            baseline = _definition_section(archive.extractfile(path).read(), path)
            expected = []
            for original in baseline:
                tool = copy.deepcopy(original)
                name = tool["name"]
                if name in retired:
                    continue
                if name in description_substitutions:
                    old, new = description_substitutions[name]
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, new, 1)
                if name == "spawn_agent":
                    tool["description"] = tool["description"].replace(
                        "Results are NOT posted to Discord",
                        "Results are NOT posted to the conversation",
                    ).replace("Max 5/channel", "Max 5/conversation")
                if name == "read_channel":
                    tool["name"] = "read_conversation"
                    tool["description"] = (
                        "Reads recent messages from the CURRENT conversation into your context. "
                        "Returns visible conversation history from all recorded participants. "
                        "The conversation is the one this request came from; "
                        "do NOT pass a conversation ID. "
                        "The returned messages are for YOUR eyes only — do NOT paste or echo them. "
                        "Read, understand, then respond with your own summary, analysis, or action."
                    )
                    del tool["input_schema"]["properties"]["channel_id"]
                if name in {"schedule_task", "update_schedule"}:
                    properties = tool["input_schema"]["properties"]
                    properties["report_format"]["description"] = properties["report_format"][
                        "description"
                    ].replace(
                        "paginated Discord embed renderer",
                        "paginated conversation report renderer",
                    )
                    if name == "update_schedule":
                        destination = properties.pop("channel_id")
                        destination["description"] = "New conversation ID for notifications"
                        properties["conversation_id"] = destination
                expected.append(tool)
            actual = _definition_section((ROOT / path).read_bytes(), path)
            assert actual == expected, path


def test_d18_preamble_covers_normal_and_thread_without_other_changes():
    path = ROOT / "src/discord/tool_loop.py"
    tree = ast.parse(path.read_text())
    prepare = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_prepare_chat_turn"
    )
    start = next(
        i for i, node in enumerate(prepare.body)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_ch"
    )
    construction = ast.Module(body=prepare.body[start:start + 3], type_ignores=[])
    for conversation in (
        SimpleNamespace(name="ordinary", id="1"),
        SimpleNamespace(name="child", id="2", parent=SimpleNamespace(name="parent")),
        SimpleNamespace(name=None, id="3"),
    ):
        scope = {"message": SimpleNamespace(channel=conversation)}
        exec(compile(construction, str(path), "exec"), scope)
        assert scope["channel_ctx"] == f"Conversation: {conversation.name or conversation.id}"
    call = next(
        node for node in ast.walk(prepare)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "build_request_preamble"
    )
    context = next(
        keyword.value for keyword in call.keywords if keyword.arg == "channel_description"
    )
    assert isinstance(context, ast.Name) and context.id == "channel_ctx"


def test_d18_is_named_in_the_exact_tool_loop_delta_not_generic_adaptation():
    entries = json.loads((ROOT / "maintenance/desktop-deltas.json").read_text())["entries"]
    entry = next(item for item in entries if item["path"] == "src/discord/tool_loop.py")
    assert "D18" in entry["reason"]
    assert "Conversation: <name>" in entry["contract"]
    assert "Channel: #<parent>" in entry["contract"]
    assert "tests/test_desktop_round2_acceptance.py" in entry["tests"]


def test_config_prompt_and_checkpoint_labels_are_exact_approved_c4():
    tree = ast.parse((ROOT / "src/config/apply_registry.py").read_text())
    strings = {node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "Chat, conversation, and loop prompts" in strings
    assert "Checkpoint conversation turns so they survive an outage." in strings
    assert "Conversational turns and loop prompts" not in strings
    assert "Checkpoint conversational turns so they survive an outage." not in strings


def test_http_probe_handler_restores_entire_upstream_module_without_new_policy():
    path = "src/tools/handlers/browser_web.py"
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz") as archive:
        assert (ROOT / path).read_bytes() == archive.extractfile(path).read()
