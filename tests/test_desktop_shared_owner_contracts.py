"""Real-owner requalification of frozen neutral evidence and failure cases."""

import ast
import hashlib
import json
import os
import shlex
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from src.permissions.manager import PermissionManager
from src.permissions.persistence import write_private_atomic
from src.tools.media_result import BinaryAttachment
from src.tools.output_authorization import (
    accessed_hosts,
    host_access_capture,
    host_binding,
    request_delivery_channel,
    request_host_authorizer,
    request_scope_authorizer,
    request_scope_id,
    request_tool_scope,
)
from src.tools.output_delivery import delivery_scope
from src.tools.output_retention import RetentionError
from src.tools.result_validator import ToolResult
from src.tools.runtime_delivery import deliver_runtime_result, execution_delivery_scope
from tests.desktop_adapters.owner_cases import (
    CORPUS_SELECTIONS,
    ToolExecutor,
    export_suite,
    transformed_tree,
    triage_hunks,
)
from tests.desktop_adapters.tools_cases import ROOT, corpus, frozen_source, owner_fixture, owner_id


@pytest.fixture(autouse=True)
def desktop_contract_owner(tmp_path_factory, monkeypatch, request):
    with owner_fixture(tmp_path_factory.mktemp("desktop-owner-contract")):
        # The upstream probe regression used real curl/network. This module-local
        # transport yields deterministic receipts and never spawns a process.
        async def inert_transport(self, address, command, *args, **kwargs):
            if shlex.split(command)[-1] == "http://127.0.0.1:9/":
                return 7, "status_code: 000"
            return 0, "status_code: 200"

        if "test_tool_failure_reporting" in request.node.name:
            monkeypatch.setattr(ToolExecutor, "_exec_command", inert_transport)
        yield


@pytest.mark.parametrize("name", list(CORPUS_SELECTIONS))
def test_owner_frozen_assertions_and_parameter_corpus_unchanged(name):
    assert corpus(ast.parse(frozen_source(f"tests/{name}.py"))) == corpus(transformed_tree(name)[0])


def test_owner_setup_hunks_match_pending_review_seals():
    triage = json.loads((ROOT / "maintenance/owner-suite-triage.json").read_text())
    records = []
    for row in triage_hunks():
        records.append(
            {
                "suite": row["suite"],
                "source_sha256": row["source_sha256"],
                "hunk_count": len(row["hunks"]),
                "exact_hunks_sha256": hashlib.sha256(
                    json.dumps(row["hunks"], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
    assert records == triage["ast_hunk_records"]
    assert triage["status"] == "pending-independent-review-not-accepted"


def emit_owner_historical_failure_accounting():
    """Emit exact handoff without claiming authority over the parent's ledger."""
    state = ROOT / ".test-state"
    accounting = json.loads((ROOT / "maintenance/case-accounting.json").read_text())
    collection = json.loads((state / "qualification-collected.json").read_text())["cases"]
    triage = json.loads((ROOT / "maintenance/owner-suite-triage.json").read_text())
    replacements = {row["original"]: row for row in triage["superseded_cases"]}
    aliases = defaultdict(list)
    for row in collection:
        aliases[row["original"]].append(row["executable"])
    executed = set()
    evidence = state / "owner-cross-suite-final.xml"
    for case in ET.parse(evidence).findall(".//testcase"):
        assert case.find("failure") is None and case.find("error") is None
        classname = case.attrib["classname"].split(".")
        end = next(i for i, part in enumerate(classname) if part.startswith("test_")) + 1
        path = "/".join(classname[:end]) + ".py"
        executed.add("::".join([path, *classname[end:], case.attrib["name"]]))
    suites = {
        "memory_fail_closed",
        "output_authorization",
        "mcp_media_retention_checkpoint",
        "successful_retry_provenance",
        "tool_failure_reporting",
        "registry_schema",
        "result_validator",
        "campaign_execution_validation",
        "handlers_state_lists",
        "state_handlers",
    }
    rows = []
    for historical in accounting["historical_failures"]:
        original = historical["original"]
        suite = original.split("::")[0].removeprefix("tests/test_").removesuffix(".py")
        if suite not in suites:
            continue
        assert (
            hashlib.sha256(frozen_source(original.split("::")[0])).hexdigest()
            == historical["source_sha256"]
        )
        replacement = replacements.get(original)
        cases = (
            replacement["replacement_cases"]
            if replacement
            else [case for case in aliases[original] if case in executed]
        )
        assert cases, f"Unmapped owner neutral case: {original}"
        assert set(cases) <= executed, f"Missing passing execution: {original}"
        rows.append(
            {
                "original": original,
                "source_sha256": historical["source_sha256"],
                "disposition": "removed-surface-replacement" if replacement else "executable",
                "executable": [] if replacement else cases,
                "replacement_cases": cases if replacement else [],
                "run_evidence": str(evidence.relative_to(ROOT)),
                "triage_source": "maintenance/owner-suite-triage.json",
                "blocks_phase1": False,
                "independent_review": "pending",
            }
        )
    assert len(rows) == len({row["original"] for row in rows}) == 67
    handoff = {
        "schema_version": 1,
        "artifact": "Exact owner-scope historical case accounting handoff",
        "status": "pending-independent-review-parent-merge-required",
        "requested_count": 115,
        "observed_named_scope_historical_cases": 67,
        "count_limitation": (
            "The named ten owner suites contain 67 of259 historical failures, not115. "
            "Other48 requested cases require exact parent population selectors, "
            "not manufactured counts."
        ),
        "historical_junit": accounting["historical_junit"],
        "historical_junit_sha256": accounting["historical_junit_sha256"],
        "run_evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "cases": rows,
        "unmapped_cases": [],
    }
    (state / "owner-case-accounting-handoff.json").write_text(json.dumps(handoff, indent=2) + "\n")


async def test_unknown_unpublished_name_denies_before_handler_dispatch():
    executor = ToolExecutor()
    executor._handle_nonexistent_tool = AsyncMock(side_effect=AssertionError("must not dispatch"))
    result = await executor.execute("nonexistent_tool", {})
    assert not result.ok and result.error == "tool_unavailable"
    executor._handle_nonexistent_tool.assert_not_awaited()


@pytest.mark.parametrize("identity", [None, "", "payload-reader", "owner-looking-argument"])
async def test_owner_gate_rejects_untrusted_request_identity(identity):
    executor = ToolExecutor()
    handler = AsyncMock(side_effect=AssertionError("untrusted identity must not dispatch"))
    executor._handle_fetch_url = handler
    # Call the real base dispatch so a missing request cannot use fixture defaults.
    from src.tools.executor import ToolExecutor as EngineExecutor

    result = await EngineExecutor.execute(executor, "fetch_url", {}, user_id=identity)
    assert result.error == "permission_denied" and not result.ok
    handler.assert_not_awaited()


@pytest.mark.parametrize("context_mode", ["missing", "forged-seal", "wrong-uid", "stale-runtime"])
async def test_owner_gate_rechecks_sealed_context_at_dispatch(context_mode, tmp_path):
    with owner_fixture(tmp_path / "nested-owner") as state:
        executor = ToolExecutor()
        handler = AsyncMock(return_value="trusted receipt")
        executor._handle_fetch_url = handler
        context = state.authority.authenticate_local(peer_uid=os.geteuid())
        altered = {
            "missing": None,
            "forged-seal": replace(context, _seal=object()),
            "wrong-uid": replace(context, owner_uid=os.geteuid() + 1),
            "stale-runtime": replace(context, runtime_id="retired-runtime"),
        }[context_mode]
        token = PermissionManager.set_request_owner(altered)
        try:
            result = await executor.execute("fetch_url", {})
            assert not result.ok and result.error == "permission_denied"
            handler.assert_not_awaited()
        finally:
            PermissionManager.reset_request_owner(token)
        accepted = await executor.execute("fetch_url", {})
        assert accepted.ok and accepted.output == "trusted receipt"
        handler.assert_awaited_once()


@pytest.mark.parametrize(
    "fence",
    [
        "owner-context",
        "origin-readiness",
        "retrieval-readiness",
        "live-tool-scope",
        "live-host-scope",
        "host-grant",
    ],
)
def test_owner_retained_body_is_not_loaded_after_live_revocation(tmp_path, monkeypatch, fence):
    from src.config.schema import ToolHost, ToolsConfig

    executor = ToolExecutor(
        config=ToolsConfig(hosts={"local-fixture": ToolHost(address="127.0.0.1")})
    )
    store = executor._ensure_output_store()
    binding = host_binding(executor.host_registry.get("local-fixture"))
    manifest = store.retain_binary_bundle(
        [BinaryAttachment(1, "resource", "application/octet-stream", b"private-body")],
        owner=owner_id(),
        channel="neutral-test",
        tool="run_command",
        hosts=(binding,),
    )
    cursor = f"{manifest.result_id}:0"
    calls = []
    original = store._db
    from contextlib import contextmanager

    @contextmanager
    def traced_db():
        with original() as db:
            db.set_trace_callback(calls.append)
            yield db

    monkeypatch.setattr(store, "_db", traced_db)
    tokens = []
    if fence == "owner-context":
        tokens.append(
            (PermissionManager.reset_request_owner, PermissionManager.set_request_owner(None))
        )
    elif fence == "origin-readiness":
        executor.readiness["run_command"] = False
    elif fence == "retrieval-readiness":
        executor.readiness["get_tool_output"] = False
    elif fence == "live-tool-scope":
        tokens.append((request_scope_authorizer.reset, request_scope_authorizer.set(lambda: set())))
    elif fence == "live-host-scope":
        tokens.append(
            (request_host_authorizer.reset, request_host_authorizer.set(lambda alias: False))
        )
    else:
        write_private_atomic(
            executor._host_access._path, json.dumps({"allowed_hosts": [], "default_host": ""})
        )
    try:
        with pytest.raises(RetentionError, match="Permission denied"):
            store.read(
                cursor,
                owner=owner_id(),
                channel="neutral-test",
                authorize=lambda tool, hosts: (
                    executor._authorize_output(tool, hosts, owner_id())
                    and executor._authorize_output("get_tool_output", (), owner_id())
                ),
            )
        assert not any("SELECT *" in query.upper() for query in calls)
    finally:
        for reset, token in reversed(tokens):
            reset(token)


@pytest.mark.parametrize("boundary", ["exception", "nested-task", "cancelled-task"])
async def test_owner_scope_cleanup_after_exception_and_task_boundary(boundary):
    import asyncio

    variables = (
        delivery_scope,
        request_tool_scope,
        accessed_hosts,
        request_scope_id,
        request_scope_authorizer,
        request_host_authorizer,
        request_delivery_channel,
    )
    before = tuple(variable.get() for variable in variables)

    async def worker():
        with execution_delivery_scope(owner_id(), "neutral-test", allowed_tools={"read_file"}):
            assert delivery_scope.get() == (owner_id(), "neutral-test")
            assert request_tool_scope.get() == {"read_file"}
            with host_access_capture():
                assert accessed_hosts.get() is not None
            if boundary == "exception":
                raise RuntimeError("synthetic boundary")
            if boundary == "cancelled-task":
                raise asyncio.CancelledError()

    if boundary == "exception":
        with pytest.raises(RuntimeError, match="synthetic boundary"):
            await worker()
    elif boundary == "nested-task":
        await asyncio.create_task(worker())
    else:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(worker())
    assert tuple(variable.get() for variable in variables) == before


@pytest.mark.parametrize("settled_ok,uncertain", [(True, True), (False, True), (False, False)])
def test_owner_retention_denial_preserves_prior_effect_outcome(settled_ok, uncertain):
    executor = ToolExecutor()
    executor.readiness["get_tool_output"] = False
    settled = ToolResult(
        "provider settled response",
        ok=settled_ok,
        error=None if settled_ok else "provider failure",
        uncertain_outcome=uncertain,
        attachments=(BinaryAttachment(1, "resource", "application/octet-stream", b"prior-effect"),),
    )
    with execution_delivery_scope(owner_id(), "neutral-test"):
        delivered = deliver_runtime_result(
            executor,
            settled,
            tool_name="fetch_url",
            tool_input={},
            user_id=owner_id(),
            channel_id="neutral-test",
        )
    assert delivered.ok is settled_ok
    assert delivered.uncertain_outcome is uncertain
    assert delivered.error == settled.error
    pointer = json.loads(str(delivered.output).split("[output retention] ", 1)[1])
    assert pointer["retention"] == "failed" and pointer["cursor"] is None
    assert "Do not replay the tool." in pointer["error"]
    assert delivered.attachments == ()


async def test_owner_list_guards_and_cross_owner_dispatch_denial(tmp_path):
    executor = ToolExecutor()
    executor.readiness["manage_list"] = True
    for parameters, needle in (
        ({"action": "show", "list_name": ""}, "list_name is required"),
        ({"action": "frobnicate", "list_name": "x"}, "Unknown action"),
        ({"action": "list_all"}, "No lists exist yet"),
    ):
        result = await executor.execute("manage_list", parameters)
        assert needle in result.output
    created = await executor.execute(
        "manage_list", {"action": "add", "list_name": "secret", "items": ["x"]}
    )
    assert created.ok
    denied = await executor.execute(
        "manage_list", {"action": "show", "list_name": "secret"}, user_id="intruder"
    )
    assert not denied.ok and denied.error == "permission_denied"
    denied_listing = await executor.execute(
        "manage_list", {"action": "list_all"}, user_id="intruder"
    )
    assert not denied_listing.ok and denied_listing.error == "permission_denied"
    assert "secret" not in denied_listing.output


async def test_owner_profile_ignores_legacy_grocery_import(tmp_path):
    executor = ToolExecutor(memory_path=str(tmp_path / "memory.json"))
    executor.readiness["manage_list"] = True
    legacy = tmp_path / "grocery_list.json"
    legacy.write_text(json.dumps({"items": [{"name": "Bread", "added_by": "legacy-user"}]}))
    before = legacy.read_bytes()
    result = await executor.execute("manage_list", {"action": "show", "list_name": "grocery"})
    assert "Bread" not in result.output
    assert legacy.read_bytes() == before
    assert not (tmp_path / "lists.json").exists()


for _suite in CORPUS_SELECTIONS:
    export_suite(globals(), _suite)
