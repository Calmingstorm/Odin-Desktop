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
    restored = plan.get("phase2_restored", [])
    retired = plan.get("phase2_retired", [])
    paths = plan["phase2"] + restored + retired
    assert len(paths) == len(set(paths)) == 326
    assert set(paths) == {
        entry["path"] for entry in plan["entries"]
        if entry["classification"] == "phase2" or entry["path"] in restored + retired
    }
    assert all(entry["classification"] == "safe_pass_now"
               for entry in plan["entries"] if entry["path"] in restored)
    assert set(restored).isdisjoint(plan["phase2"])
    assert all(entry["classification"] == "retired"
               for entry in plan["entries"] if entry["path"] in retired)
    assert set(retired).isdisjoint(plan["phase2"] + restored + plan["safe_pass_now"])
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


# Desktop 1.1 carries Odin 4.14's governor fix (#638): the classifier is Odin v4.14.0's file,
# byte for byte (sha256 of `git show v4.14.0:src/tools/risk_classifier.py` in Odin's repository).
ODIN_V4_14_0_GOVERNOR_SHA256 = "6d38578f2bde09a3715e2c9d78e420aeacb11e3ecd88ff2818d73eaef8830249"


def test_governor_and_imports_keep_the_bytes_supported_by_upstream_ci():
    governor = (ROOT / "src/tools/risk_classifier.py").read_bytes()
    assert hashlib.sha256(governor).hexdigest() == ODIN_V4_14_0_GOVERNOR_SHA256
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz") as archive:
        for path in (
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
                    # Odin 4.19, carried: spawners name the agents' report tool.
                    old = "injected near iteration limit."
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, (
                        "injected near iteration limit. When you want interim reports, tell "
                        "spawned agents to use their agent-only report_to_parent tool, not "
                        "send_to_agent. Reports may arrive at later steps without waking waits or "
                        "interrupting work; reply with send_to_agent only if needed. Still "
                        "collect final results."), 1)
                    # Odin 4.25.0 (#743), carried: gpt-6.1-terra between gpt-6.1-sol and gpt-6-sol.
                    terra = ("capable model, slightly less capable than gpt-6.1-sol but cheaper; "
                             "use for cost-sensitive coding and agentic work, escalating to "
                             "gpt-6.1-sol for harder problems")
                    old = "gpt-6-sol (bal"
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(
                        old, f"gpt-6.1-terra ({terra}), {old}", 1)
                    model = tool["input_schema"]["properties"]["model"]
                    old = "gpt-6-sol = bal"
                    assert model["description"].count(old) == 1
                    model["description"] = model["description"].replace(
                        old, f"gpt-6.1-terra = {terra}; {old}", 1)
                if name == "send_to_agent":  # Odin 4.19, carried: reports route elsewhere
                    tool["description"] += (
                        " For interim reports to your spawner, use report_to_parent, "
                        "not this tool.")
                if name == "get_tool_output":  # Odin 4.19.1, carried: retention is up to 24 hours
                    old = ("Evidence expires 24 hours after capture (fixed TTL), with "
                           "per-result/global quotas. ")
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, (
                        "Evidence lasts up to 24 hours after capture, with per-result/global "
                        "quotas; reads do not extend it, and the oldest is removed earlier when "
                        "the global quota needs room. "), 1)
                if name == "manage_list":  # Odin 4.14 (#641), carried: delete removes a list
                    old = "Supports mark_done/mark_undone."
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(
                        old, old + " 'clear' empties a list; 'delete' removes it.", 1)
                    actions = tool["input_schema"]["properties"]["action"]["enum"]
                    actions.insert(actions.index("clear") + 1, "delete")
                if name == "validate_action":  # Odin 4.15 (#655), carried: launchd targets
                    old = ("  service         target=systemd unit name, "
                           "expected='active' or list of states\n")
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, (
                        "  service         target=systemd unit name on Linux; on macOS use a "
                        "launchd label (defaults to system/label), system/label, or "
                        "gui/UID/label. expected='active' or list of states; 'active' maps to "
                        "'running' on macOS\n"), 1)
                if name == "kill_agent":  # Odin 4.20.0, carried: a kill stops the agents' jobs
                    old = "Terminates a running agent immediately."
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, (
                        "Terminates a running agent (and its running descendants) immediately "
                        "and stops the background jobs they started."), 1)
                if name == "search_audit":  # Odin 4.20.0, carried: one result per call
                    old = ("Searches audit log of tool executions. Returns '[date] tool_name by "
                           "user (status, Nms)'.")
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, (
                        "Searches audit log of tool executions, one result per call: '[date] "
                        "tool_name by user (approved or denied, Nms, outcome)'."), 1)
                    properties = tool["input_schema"]["properties"]
                    for field, before, after in (
                        ("keyword", "Free-text search across all fields",
                         "Free-text search across a call's records, including its result "
                         "text; command and script bodies are not stored"),
                        ("status", "Filter by status (e.g. 'error', 'success')",
                         "Filter by outcome: succeeded, failed, denied, cancelled, "
                         "outcome_unknown or started ('error' and 'success' also work)"),
                        ("limit", "Max results (default 20)", "Max calls returned (default 20)"),
                    ):
                        assert properties[field]["description"] == before
                        properties[field]["description"] = after
                if name == "wait_for_agents":  # Odin 4.26.0 (#748), carried: any + fuller previews
                    old = ("Returns status snapshots with up to 800 UTF-8 bytes of result preview "
                           "per agent, possibly less under the aggregate budget. ")
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, (
                        "With return_when='any' it returns as soon as any requested agent has "
                        "finished, including one that finished earlier, so leave out the IDs you "
                        "have already handled before waiting again; no agent is cancelled. "
                        "Each snapshot previews as much of the agent's result as the aggregate "
                        "budget allows, up to 8,000 UTF-8 bytes per agent. "), 1)
                    properties = tool["input_schema"]["properties"]
                    assert list(properties) == ["agent_ids", "timeout"]
                    properties["return_when"] = {
                        "type": "string",
                        "enum": ["all", "any"],
                        "description": "'all' (default) = when every agent has finished; "
                                       "'any' = when any agent has finished",
                    }
                if name == "post_file":  # Odin 4.24.0 (#737), carried: post a file a tool returned
                    old = "Max 25MB. "
                    assert tool["description"].count(old) == 1
                    tool["description"] = tool["description"].replace(old, old + (
                        "To post a file a tool returned (an MCP result's file), read its "
                        "attachment manifest with get_tool_output and pass that file's entry "
                        "cursor (it ends in ':0') as attachment, instead of host and path. "), 1)
                    tool["input_schema"]["properties"]["attachment"] = {
                        "type": "string",
                        "description": (
                            "Instead of host and path: one retained file's cursor, from its "
                            "entry in a tool attachment manifest (not the manifest's own "
                            "cursor)"),
                    }
                    assert tool["input_schema"]["required"] == ["host", "path"]
                    tool["input_schema"]["required"] = []
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
