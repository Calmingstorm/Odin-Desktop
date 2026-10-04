"""Frozen neutral tool corpus with authentic Desktop setup."""

import ast
import shutil
import subprocess
import sys

import pytest

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source, verify_transform
from tests.desktop_adapters.tools_cases import (
    SUITES,
    adapted_suite_tree,
    export_suite,
    owner_fixture,
)


@pytest.fixture(autouse=True)
def desktop_tool_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("desktop-owner")):
        yield


@pytest.mark.parametrize("name", list(SUITES))
def test_frozen_assertions_and_parameter_corpus_are_unchanged(name):
    source = frozen_source(f"tests/{name}.py")
    adapted = adapted_suite_tree(name)
    assert corpus(ast.parse(source)) == corpus(adapted)
    assert verify_transform(f"tests/{name}.py", ast.parse(source), adapted)


@pytest.mark.parametrize("mutation", ["body", "assertion", "signature", "parameter"])
def test_strict_setup_verifier_rejects_unadmitted_tool_mutations(mutation):
    path = "tests/test_apply_patch.py"
    original = ast.parse(frozen_source(path))
    adapted = adapted_suite_tree("test_apply_patch")
    function = next(
        node
        for node in ast.walk(adapted)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )
    if mutation == "body":
        function.body.insert(0, ast.Expr(value=ast.Constant(value="unadmitted setup")))
    elif mutation == "assertion":
        function.body.append(ast.Assert(test=ast.Constant(value=True)))
    elif mutation == "signature":
        function.args.args.append(ast.arg(arg="unadmitted_fixture"))
    else:
        function.decorator_list.append(
            ast.Call(
                func=ast.Attribute(
                    value=ast.Attribute(
                        value=ast.Name(id="pytest", ctx=ast.Load()), attr="mark", ctx=ast.Load()
                    ),
                    attr="parametrize",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Constant(value="case"),
                    ast.List(elts=[ast.Constant(value=1)], ctx=ast.Load()),
                ],
                keywords=[],
            )
        )
    with pytest.raises(ValueError):
        verify_transform(path, original, adapted)


def test_frozen_tool_verification_in_checkout_without_git_refs(tmp_path):
    """The static helper and frozen archive suffice in an exported checkout."""
    checkout = tmp_path / "checkout"
    for relative in (
        "scripts/maintenance/fixture_corpus.py",
        "maintenance/fixture-corpus.json",
        "maintenance/odin-v4.13.0.tar.gz",
        "tests/test_apply_patch.py",
    ):
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    adapted_path = checkout / "adapted.py"
    adapted_path.write_text(ast.unparse(adapted_suite_tree("test_apply_patch")))
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import ast, pathlib, runpy; "
            "root=pathlib.Path.cwd(); "
            "h=runpy.run_path(str(root/'scripts/maintenance/fixture_corpus.py')); "
            "p='tests/test_apply_patch.py'; "
            "s=h['frozen_source'](p, root=root); "
            "a=ast.parse((root/'adapted.py').read_text()); "
            "assert h['verify_transform'](p, ast.parse(s), a, root=root); "
            "print('offline frozen transform verified')",
        ],
        cwd=checkout,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert not (checkout / ".git").exists()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "offline frozen transform verified"


for _suite in SUITES:
    export_suite(globals(), _suite)


def test_retained_destructive_tool_affordances():
    from src.tools.affordances import Risk, get_affordance

    for name in ("delete_knowledge", "delete_schedule", "delete_skill"):
        assert get_affordance(name).risk == Risk.CRITICAL


def test_adapter_does_not_authorize_payload_or_revoked_readiness():
    from tests.desktop_adapters.tools_cases import ToolExecutor, owner_id

    executor = ToolExecutor()
    assert executor.check_permission("fetch_url", "forged-owner")
    assert executor.check_permission("fetch_url", owner_id()) is None
    executor.readiness["fetch_url"] = False
    assert not executor._builtin_policy.is_available("fetch_url")


@pytest.mark.asyncio
async def test_explicit_bundled_browser_launch_failure_is_reported():
    from unittest.mock import AsyncMock

    from src.tools.browser import BrowserManager
    from tests.desktop_adapters.tools_cases import browser_fixture_path

    manager = BrowserManager(bundled_executable=browser_fixture_path())
    manager._playwright = AsyncMock()
    manager._playwright.chromium.launch.side_effect = RuntimeError("fixture launch refusal")
    with pytest.raises(RuntimeError, match="Failed to launch required bundled Chromium"):
        await manager._ensure_connected()
    manager._playwright.chromium.launch.assert_awaited_once()


@pytest.mark.asyncio
async def test_neutral_skill_listing_loaded_disabled_and_load_error(tmp_path):
    from tests.desktop_adapters.tools_cases import SkillManager, ToolExecutor

    module = (
        'SKILL_DEFINITION = {"name": "%s", "description": "demo", '
        '"input_schema": {"type": "object", "properties": {}}}\n'
        'async def execute(inp, context):\n    return "ok"\n'
    )
    (tmp_path / "enabled.py").write_text(module % "enabled")
    (tmp_path / "disabled.py").write_text(module % "disabled")
    (tmp_path / "broken.py").write_text("invalid Python fixture\n")
    manager = SkillManager(str(tmp_path), ToolExecutor())
    manager.disable_skill("disabled")
    manager = SkillManager(str(tmp_path), ToolExecutor())
    assert {entry["name"]: entry["status"] for entry in manager.list_skills()} == {
        "enabled": "loaded",
        "disabled": "disabled",
        "broken": "error",
    }
    assert not manager.has_skill("broken")
    assert {entry["name"] for entry in manager.get_tool_definitions()} == {"enabled"}
    assert await manager.execute("enabled", {}) == "ok"


@pytest.mark.parametrize("identity", [None, "", "payload-owner"])
def test_real_owner_host_fences_reject_ambient_or_payload_identity(identity):
    from tests.desktop_adapters.tools_cases import ToolExecutor

    executor = ToolExecutor()
    alias = executor.host_registry.default_host
    executor.set_user_context(identity)
    assert executor._resolve_host(alias) is None
    assert executor._acquire_host(alias) is None
    assert executor.acquire_host_for_user(alias, identity) is None
    assert executor._resolve_default_host(identity) == ""
    assert executor.system_tools._host_registry is executor.host_registry


@pytest.mark.asyncio
async def test_real_owner_persisted_grant_revocation_fences_host_access(tmp_path):
    from src.config.schema import ToolHost
    from src.tools.hosts import HostRegistry
    from tests.desktop_adapters.tools_cases import ToolExecutor, owner_id

    executor = ToolExecutor(
        host_registry=HostRegistry(
            {"alpha": ToolHost(address="127.0.0.1")},
            default_host="alpha",
            trust_dir=tmp_path / "trust",
        )
    )
    access = executor._host_access
    alias = executor.host_registry.default_host
    assert executor._resolve_default_host(owner_id()) == alias
    assert executor._resolve_host(alias) is not None
    await access.set_policy(owner_id(), [])
    assert executor._resolve_host(alias) is None
    assert executor._acquire_host(alias) is None
    assert executor.acquire_host_for_user(alias, owner_id()) is None
    assert executor._resolve_default_host(owner_id()) == ""


def test_missing_governor_is_denied_without_dispatch():
    from tests.desktop_adapters.tools_cases import ToolExecutor

    executor = ToolExecutor()
    executor.command_governor = None
    allowed, denial, note = executor._govern_command("echo not-dispatched")
    assert allowed is False
    assert "governor is not configured" in denial
    assert note == ""


@pytest.mark.parametrize("identity", [None, "", "payload-owner"])
def test_originating_output_requires_real_owner_before_retention(identity, monkeypatch):
    from unittest.mock import Mock

    from src.desktop.errors import CapabilityUnavailable
    from tests.desktop_adapters.tools_cases import ToolExecutor

    executor = ToolExecutor()
    retain = Mock(side_effect=AssertionError("unauthorized output reached retention"))
    monkeypatch.setattr(executor, "_ensure_output_store", retain)
    with pytest.raises(CapabilityUnavailable):
        executor.deliver_output(
            "private evidence" * 5000, tool_name="fetch_url", tool_input={}, user_id=identity
        )
    retain.assert_not_called()


def test_private_fixture_legacy_memory_migration_preserves_values(tmp_path):
    import json

    from tests.desktop_adapters.tools_cases import ToolExecutor

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(json.dumps({"old": "value"}))
    executor = ToolExecutor(memory_path=str(memory_path))
    assert executor._load_all_memory() == {"global": {"old": "value"}}
    assert json.loads(memory_path.read_text()) == {"global": {"old": "value"}}
