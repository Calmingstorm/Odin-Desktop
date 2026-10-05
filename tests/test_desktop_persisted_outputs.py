"""D17 transcript content survives real runtime host/policy changes, not evidence."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from src.config.schema import ToolHost, ToolsConfig
from src.desktop.artifacts import ArtifactStore, ResultReadError
from src.desktop.commands import JournalStore
from src.desktop.services import _ReadyPolicy
from src.desktop.tool_details import ToolDetailsStore
from src.tools.executor import ToolExecutor
from src.tools.media_result import BinaryAttachment
from src.tools.output_authorization import host_binding
from src.tools.output_retention import OutputStore
from tests.desktop_adapters.tools_cases import owner_fixture


def executor_for(state, hosts):
    executor = ToolExecutor(
        ToolsConfig(hosts=hosts,
                    local_working_dir=str(state.paths.data_dir / "workspace"),
                    audit_log_path=str(state.paths.data_dir / "audit.jsonl")),
        profile_paths=state.paths, permission_manager=state.manager,
        memory_path=str(state.paths.data_dir / "memory.json"))
    executor.set_builtin_policy(_ReadyPolicy(
        lambda: SimpleNamespace(tools=executor.config),
        lambda: {tool: True for tool in (
            "post_file", "generate_file", "run_command", "get_tool_output")}))
    state.executors.append(executor)
    return executor


def stores_for(state, executor):
    journal = JournalStore(state.paths.data_dir / "journal.sqlite3", "profile")
    evidence = OutputStore(state.paths.data_dir / "evidence.sqlite3")
    artifacts = ArtifactStore(journal, output_store=evidence,
                              authorize=executor._authorize_output)
    details = ToolDetailsStore(journal, output_store=evidence, artifacts=artifacts,
                               authorize=executor._authorize_output)
    return journal, evidence, artifacts, details


def assert_unavailable(read, code):
    with pytest.raises(ResultReadError) as exc:
        read()
    assert exc.value.code == code


@pytest.mark.parametrize("tool", ["post_file", "generate_file"])
@pytest.mark.parametrize("change", ["restart", "edit_host", "disable_origin", "disable_retrieval"])
@pytest.mark.asyncio
async def test_posted_files_and_stored_cards_survive_live_scope_changes(tmp_path, tool, change):
    with owner_fixture(tmp_path) as state:
        owner = state.authority.owner_id
        # A host added during a session has generation 2. Reconstructing the
        # actual registry on restart binds that same host at generation 1.
        executor = executor_for(state, {})
        hosts = {"added": ToolHost(address="localhost")}
        executor.host_registry.publish(hosts)
        original = host_binding(executor.host_registry.get("added"))
        assert executor.host_registry.get("added").generation == 2
        bindings = (original,)
        journal, evidence, artifacts, details = stores_for(state, executor)
        try:
            assert executor._authorize_output(tool, bindings, owner)
            data = b"posted transcript bytes\xff\x00"
            posted = artifacts.publish(
                data, owner=owner, conversation_id="conversation", request_id="request",
                name="saved.bin", mime="application/octet-stream", tool=tool, hosts=bindings)
            text = evidence.retain(
                "retained complete result", owner=owner, channel="conversation",
                tool=tool, hosts=bindings)
            manifest = evidence.retain_binary_bundle(
                [BinaryAttachment(data=b"retained bytes\xff", media_type="application/octet-stream",
                                  content_index=0, kind="file")],
                owner=owner, channel="conversation", tool=tool, hosts=bindings)
            binary_cursor = json.loads(manifest.text)["attachments"][0][
                "retrieval"]["arguments"]["cursor"]
            text_cursor = f"{text.result_id}:0"
            manifest_cursor = f"{manifest.result_id}:0"
            details.record(
                request_id="request", invocation_id="invocation", owner=owner,
                conversation_id="conversation", tool=tool, arguments={"name": "saved.bin"},
                delivered_output="stored preview", hosts=bindings, target="added",
                cursor=text_cursor, attachment_cursor=manifest_cursor)
            details.record(
                request_id="request", invocation_id="command", owner=owner,
                conversation_id="conversation", tool="run_command", arguments={"command": "pwd"},
                delivered_output="stored command receipt", hosts=bindings, target="added")
            retained = details.output(manifest_cursor, 100, owner=owner,
                                      conversation_id="conversation")["attachments"][0]
            assert details.detail("request", "invocation", owner=owner)["output"]["cursor"]
            assert base64.b64decode(artifacts.read(
                retained["ref"], 0, 100, owner=owner)["data_b64"]) == b"retained bytes\xff"

            if change == "restart":
                journal.close()
                executor = executor_for(state, hosts)
                current = executor.host_registry.get("added")
                assert current.generation == 1
                assert host_binding(current) != original
                journal, evidence, artifacts, details = stores_for(state, executor)
            elif change == "edit_host":
                executor.host_registry.publish({"added": ToolHost(address="127.0.0.1")})
                # Registry retirement is scheduled on the running core loop.
                await asyncio.sleep(0)
                current = executor.host_registry.get("added")
                assert current.generation == 3
                assert current.address != "localhost"
                assert host_binding(current) != original
            else:
                executor.config.disabled_tools = [
                    tool if change == "disable_origin" else "get_tool_output"]

            # Real executor policy/host checks refuse the original evidence.
            if change == "disable_retrieval":
                assert not executor._authorize_output("get_tool_output", (), owner)
            else:
                assert not executor._authorize_output(tool, bindings, owner)
            page = artifacts.read(posted["ref"], 0, 100, owner=owner,
                                  conversation_id="conversation")
            assert base64.b64decode(page["data_b64"]) == data
            card = details.detail("request", "invocation", owner=owner,
                                  conversation_id="conversation")
            assert card["tool"] == tool and card["target"] == "added"
            assert card["arguments"] == {"name": "saved.bin"}
            assert card["previews"] == [{"label": "Output preview", "text": "stored preview",
                                         "truncated": False}]
            assert card["output"] == {}
            command = details.detail("request", "command", owner=owner,
                                     conversation_id="conversation")
            assert command["tool"] == "run_command" and command["target"] == "added"
            assert command["previews"][0]["text"] == "stored command receipt"
            assert command["output"] == {}
            for identity, conversation in [("foreign", "conversation"), (owner, "foreign")]:
                assert_unavailable(lambda: artifacts.read(
                    posted["ref"], 0, 100, owner=identity, conversation_id=conversation),
                    "not_found")
                assert_unavailable(lambda: details.detail(
                    "request", "invocation", owner=identity, conversation_id=conversation),
                    "not_found")
            # A core ref must not launder a retained source_cursor into posted
            # bytes. Text, manifest, and direct binary continuations stay fenced.
            assert_unavailable(lambda: artifacts.read(
                retained["ref"], 0, 100, owner=owner, conversation_id="conversation"),
                "unauthorized")
            for cursor in (text_cursor, manifest_cursor, binary_cursor):
                assert_unavailable(lambda: details.output(
                    cursor, 100, owner=owner, conversation_id="conversation"), "unauthorized")
        finally:
            journal.close()
