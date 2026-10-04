"""Frozen neutral tool cases with module-local authentic setup."""

from __future__ import annotations

import ast
import contextvars
import hashlib
import json
import os
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus as corpus
from scripts.maintenance.fixture_corpus import frozen_source, verify_transform
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.permissions.host_access import HostAccessManager
from src.permissions.manager import PermissionManager
from src.permissions.persistence import write_private_atomic
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor as EngineExecutor
from src.tools.skill_manager import SkillManager as EngineSkillManager

ROOT = Path(__file__).resolve().parents[2]
_fixture = contextvars.ContextVar("desktop_tool_test_fixture", default=None)


@contextmanager
def owner_fixture(tmp_path):
    if os.geteuid() == 0:
        raise RuntimeError("use isolated runner as non-root")
    paths = ProfilePaths.from_xdg(
        environ={
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        home=tmp_path,
    )
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    token = manager.set_request_owner(context)
    state = SimpleNamespace(paths=paths, authority=authority, manager=manager, executors=[])
    fixture_token = _fixture.set(state)
    try:
        yield state
    finally:
        for executor in state.executors:
            executor.set_user_context(None)
        _fixture.reset(fixture_token)
        manager.reset_request_owner(token)
        authority.release_runtime()


def owner_id():
    return _fixture.get().authority.owner_id


class ToolExecutor(EngineExecutor):
    def __init__(self, *args, **kwargs):
        state = _fixture.get()
        if state is None:
            raise RuntimeError("adapter requires owner_fixture")
        kwargs.setdefault("profile_paths", state.paths)
        kwargs.setdefault("permission_manager", state.manager)
        kwargs.setdefault("memory_path", str(state.paths.data_dir / "memory.json"))
        super().__init__(*args, **kwargs)
        aliases = list(self.host_registry.configured_aliases())
        policy_path = state.paths.config_dir / f"test-host-policy-{len(state.executors)}.json"
        write_private_atomic(
            policy_path,
            json.dumps(
                {
                    "allowed_hosts": aliases,
                    "default_host": self.host_registry.default_host,
                }
            ),
        )
        self._host_access = HostAccessManager(
            policy_path, available_hosts=aliases, permission_manager=state.manager
        )
        self.readiness = {
            name: True
            for name in (
                "apply_patch",
                "run_command",
                "validate_action",
                "get_tool_output",
                "read_file",
                "fetch_url",
                "email_send",
                "email_search",
                "email_read",
                "email_list_recent",
            )
        }
        self._builtin_policy = BuiltinToolPolicy(
            lambda: SimpleNamespace(tools=self.config), lambda: self.readiness
        )
        self.set_user_context(state.authority.owner_id)
        state.executors.append(self)

    async def execute(self, tool_name, tool_input, *, user_id=None):
        return await super().execute(
            tool_name, tool_input, user_id=owner_id() if user_id is None else user_id
        )


class ImportSurfaces(ast.NodeTransformer):
    def visit_keyword(self, node):
        if isinstance(node.value, ast.Constant):
            if node.arg == "user_id" and node.value.value in ("u", "user"):
                node.value = ast.Call(
                    func=ast.Name(id="desktop_fixture_owner_id", ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
            if node.arg == "tool_name" and node.value.value == "fixture":
                node.value = ast.Constant(value="fetch_url")
        return node

    def visit_ImportFrom(self, node):
        if node.module == "src.tools.skill_manager":
            managers = [alias for alias in node.names if alias.name == "SkillManager"]
            other = [alias for alias in node.names if alias.name != "SkillManager"]
            result = []
            if managers:
                result.append(
                    ast.ImportFrom(
                        module="tests.desktop_adapters.tools_cases", names=managers, level=0
                    )
                )
            if other:
                result.append(ast.ImportFrom(module=node.module, names=other, level=0))
            return [ast.copy_location(item, node) for item in result]
        if node.module == "src.tools.executor":
            executor = [a for a in node.names if a.name == "ToolExecutor"]
            other = [a for a in node.names if a.name != "ToolExecutor"]
            result = []
            if executor:
                result.append(
                    ast.ImportFrom(
                        module="tests.desktop_adapters.tools_cases", names=executor, level=0
                    )
                )
            if other:
                result.append(ast.ImportFrom(module=node.module, names=other, level=0))
            return [ast.copy_location(n, node) for n in result]
        if node.module in ("src.tools", "src.tools.registry"):
            for alias in node.names:
                if alias.name == "get_tool_definitions":
                    alias.name = "get_documentation_tool_definitions"
                    alias.asname = "get_tool_definitions"
                    node.module = "src.tools.registry"
        return node


CORPUS_SELECTIONS = {
    "test_apply_patch": None,
    "test_apply_patch_payload": None,
    "test_email_tools": None,
    "test_email_campaign": None,
    "test_affordances": None,
    "test_agent_wait_description": None,
    "test_type_gate": None,
    "test_coverage_gate": None,
    "test_tool_listing_contracts": {"test_documented_create_skill_example_is_executable"},
    "test_campaign_evidence_review": {
        "test_skill_formatting_cannot_erase_nested_uncertainty",
        "test_direct_agent_typed_failure_retains_uncertainty",
        "test_direct_agent_content_cannot_manufacture_metadata",
        "test_agent_generic_post_dispatch_exception_is_unknown",
        "test_agent_effect_free_wait_exception_stays_definite",
        "test_skill_context_string_wrapper_retains_failure_provenance",
        "test_retention_failure_hashes_hidden_evidence_and_reports_truncation",
        "test_ranked_repetition_equality_and_hidden_inequality",
        "test_binary_ranked_full_body_digest_and_truncation",
        "test_binary_already_delivered_text_preserves_stable_identity",
        "test_runtime_rewrap_preserves_trusted_flags_and_digest",
        "test_short_output_preserves_legacy_string_compatibility",
    },
    "test_hosts_executor_leases": {
        "test_execute_and_run_on_host_hold_a_host_lease_without_transport",
        "test_execute_force_revoke_returns_structured_uncertain_outcome",
        "test_remote_transport_and_retirement_use_the_exact_target",
        "test_handler_failures_are_hermetic_and_classify_as_nonzero",
        "test_validation_exec_acquires_a_lease_and_reports_unknown_alias",
        "test_tool_result_as_dict_emits_all_optional_serializable_fields",
    },
    "test_browser_automation": {
        "TestValidateUrl",
        "TestConstants",
        "TestBrowserManagerInit",
        "TestIsConnectionError",
        "TestOnBrowserDisconnected",
        "TestForceReconnect",
        "TestNewPageCleanup",
        "TestShutdown",
        "TestBrowserRequestGuard",
        "TestEnsureConnected",
        "TestBrowserCallIsolation",
        "test_await_bounded_does_not_wait_for_cancel_suppressing_awaitable",
    },
}
SUITES = CORPUS_SELECTIONS
CORPUS_EXCLUSIONS = {
    "test_affordances": ["TestGetAffordance.test_critical_risk_destructive_tools"],
    "test_browser_automation": ["TestEnsureConnected.test_native_launch_failure_raises"],
}


def frozen_script(name):
    """Load exact gate bytes into isolated fixture storage, never live CI."""
    path = f"scripts/ci/{name}.py"
    archive = ROOT / "maintenance/odin-v4.13.0.tar.gz"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != (
        "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
    ):
        raise AssertionError("baseline archive digest changed")
    with tarfile.open(archive) as bundle:
        source = bundle.extractfile(path).read()
    state = _fixture.get()
    script_path = state.paths.cache_dir / f"{name}.py"
    script_path.write_bytes(source)
    tree = ast.parse(source, filename=path)
    module = ModuleType(f"desktop_frozen_{name}")
    module.__file__ = str(script_path)
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    return module


class FrozenScriptProxy:
    def __init__(self, name):
        object.__setattr__(self, "name", name)

    def _module(self):
        state = _fixture.get()
        if not hasattr(state, "gates"):
            state.gates = {}
        if self.name not in state.gates:
            state.gates[self.name] = frozen_script(self.name)
        return state.gates[self.name]

    def __getattr__(self, key):
        if _fixture.get() is None and key == "parse_finding":
            return lambda *args, **kwargs: self._module().parse_finding(*args, **kwargs)
        return getattr(self._module(), key)

    def __setattr__(self, key, value):
        setattr(self._module(), key, value)


def adapted_suite_tree(name):
    """Verify all setup rewrites before projecting explicitly selected cases."""
    if name not in SUITES:
        raise ValueError("suite has not been audited")
    path = f"tests/{name}.py"
    source = frozen_source(path)
    original = ast.parse(source, filename=path)
    adapted = ImportSurfaces().visit(ast.parse(source, filename=path))
    if name == "test_tool_listing_contracts":
        # Removed transport renderer imports are not recreated. The selected
        # documented SkillManager example has no dependency on those classes.
        adapted.body = [
            node
            for node in adapted.body
            if not (isinstance(node, ast.ImportFrom) and node.module.startswith("src.discord"))
        ]
    if name in ("test_type_gate", "test_coverage_gate"):
        gate_name = name.removeprefix("test_")
        adapted.body = [
            node
            for node in adapted.body
            if not (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "_SPEC" for target in node.targets
                )
                or isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "exec_module"
                or isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Subscript) for target in node.targets)
                or isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == gate_name
                    for target in node.targets
                )
            )
        ]
    verify_transform(path, original, adapted)
    return adapted


def load_suite(name):
    adapted = adapted_suite_tree(name)
    path = f"tests/{name}.py"
    selection = SUITES[name]
    if selection is not None:
        adapted.body = [
            node
            for node in adapted.body
            if not (
                isinstance(node, ast.ClassDef)
                and node.name.startswith("Test")
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
            or node.name in selection
        ]
    ast.fix_missing_locations(adapted)
    for node in adapted.body:
        if isinstance(node, ast.ClassDef):
            node.body = [
                child
                for child in node.body
                if f"{node.name}.{getattr(child, 'name', '')}"
                not in CORPUS_EXCLUSIONS.get(name, [])
            ]
    module = ModuleType(f"desktop_frozen_{name}")
    module.__file__ = str(ROOT / path)
    module.desktop_fixture_owner_id = owner_id
    module.desktop_fixture_browser_path = browser_fixture_path
    if name in ("test_type_gate", "test_coverage_gate"):
        gate_name = name.removeprefix("test_")
        setattr(module, gate_name, FrozenScriptProxy(gate_name))
    exec(compile(adapted, str(ROOT / path), "exec"), module.__dict__)
    return module


def export_suite(namespace, name):
    module = load_suite(name)
    for key, value in vars(module).items():
        if key.startswith("test_"):
            namespace[f"test_{name}_{key[5:]}"] = value
        elif key.startswith("Test"):
            namespace[f"Test_{name}_{key[4:]}"] = value


def browser_fixture_path():
    path = _fixture.get().paths.cache_dir / "inert-browser"
    path.write_text("fixture preflight only, never executable input\n")
    path.chmod(0o700)
    return str(path)


class SkillManager(EngineSkillManager):
    """Give legacy mocked skill fixtures real owner admission, not admin stubs."""

    def __init__(self, skill_dir, executor, *args, **kwargs):
        real_executor = ToolExecutor()
        # The inherited mock stays the nested tool transport; real executor
        # check_permission and manager selected-skill admission are untouched.
        real_executor.execute = executor.execute
        super().__init__(skill_dir, real_executor, *args, **kwargs)

    async def execute(self, *args, requester_id=None, **kwargs):
        return await super().execute(
            *args, requester_id=(owner_id() if requester_id is None else requester_id), **kwargs
        )
